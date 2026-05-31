from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage

import agent.runtime.langgraph_orchestrator as orchestrator_module
from agent.runtime.langgraph_orchestrator import (
    LangGraphOrchestrator,
    _resolve_query_and_history_from_messages,
)


def test_resolve_query_and_history_from_messages() -> None:
    """messages 应拆分为当前 query 与历史对话。"""
    query, history = _resolve_query_and_history_from_messages(
        [
            HumanMessage(content="上一个问题"),
            AIMessage(content="上一个回答"),
            HumanMessage(content="当前问题"),
        ]
    )

    assert query == "当前问题"
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[0].content == "上一个问题"
    assert history[1].role == "assistant"
    assert history[1].content == "上一个回答"


def test_resolve_query_and_history_from_rich_text_messages() -> None:
    """富文本块消息应先展开为纯文本，再参与 query/history 推导。"""
    query, history = _resolve_query_and_history_from_messages(
        [
            HumanMessage(content=[{"type": "text", "text": "上一个问题"}]),
            AIMessage(content=[{"type": "text", "text": "上一个回答"}]),
            HumanMessage(
                content=[{"type": "text", "text": "再次查询一下，不太对，应该是电信。"}]
            ),
        ]
    )

    assert query == "再次查询一下，不太对，应该是电信。"
    assert len(history) == 2
    assert history[0].content == "上一个问题"
    assert history[1].content == "上一个回答"


class _TracePassthrough:
    """用于测试节点输出的最小桩对象。"""

    class _LLM:
        @staticmethod
        def chat_stream(_messages):
            yield "最终"
            yield "回答"

    llm = _LLM()

    @staticmethod
    def _emit_stream_event(*_args, **_kwargs):
        return None

    def _trace_node(self, _name, _state, fn):
        return fn()


class _NoToolRetrievalPassthrough:
    """用于测试纯 none 计划不会触发额外检索。"""

    def __init__(self) -> None:
        self.memory_calls = 0
        self.note_calls = 0
        self.memory_manager = SimpleNamespace(search=self._search)
        self.mcp_client = SimpleNamespace(call_tool=self._call_tool)

    def _search(self, _query, top_k=5):
        self.memory_calls += 1
        return [f"memory-top-{top_k}"]

    def _call_tool(self, _name, _payload, trace_id=""):
        self.note_calls += 1
        return {"notes": [trace_id or "note"]}

    def _trace_node(self, _name, _state, fn):
        return fn()


class _BuildContextPassthrough:
    """用于测试 build_context 是否保留历史对话。"""

    def __init__(self) -> None:
        self.calls = []
        self.context_builder = SimpleNamespace(build_with_trace=self._build_with_trace)

    def _build_with_trace(self, **kwargs):
        self.calls.append(kwargs)
        return "拼装后的上下文", {"token_stats": {}}

    def _build_context_evidences(self, _state):
        return []

    @staticmethod
    def _emit_stream_event(*_args, **_kwargs):
        return None

    def _trace_node(self, _name, _state, fn):
        return fn()


class _ConversationAnswerPassthrough:
    """用于测试纯 none 计划会按对话消息调用 LLM。"""

    def __init__(self) -> None:
        self.captured_messages = []
        parent = self

        class _LLM:
            @staticmethod
            def chat_stream(messages):
                parent.captured_messages = list(messages)
                yield "最终"
                yield "回答"

        self.llm = _LLM()

    @staticmethod
    def _emit_stream_event(*_args, **_kwargs):
        return None

    def _trace_node(self, _name, _state, fn):
        return fn()


def test_generate_answer_node_appends_ai_message(monkeypatch) -> None:
    """回答节点应把最终回答追加到 messages。"""
    state = {"context": "上下文内容"}
    helper = _TracePassthrough()
    monkeypatch.setattr(
        orchestrator_module, "get_stream_writer", lambda: lambda _payload: None
    )

    out = LangGraphOrchestrator._generate_answer_node(helper, state)  # type: ignore[misc]

    assert out["answer"] == "最终回答"
    assert len(out["messages"]) == 1
    assert isinstance(out["messages"][0], AIMessage)
    assert out["messages"][0].content == "最终回答"


def test_collect_memory_and_notes_node_skips_retrieval_for_none_plan() -> None:
    """纯 none 计划应跳过记忆检索与 note 工具调用。"""
    helper = _NoToolRetrievalPassthrough()
    state = {
        "messages": [
            HumanMessage(content="上一个问题"),
            AIMessage(content="上一个回答"),
            HumanMessage(content="谢谢"),
        ],
        "plan_steps": [{"step_id": "step_1", "tool": "none", "arguments": {}}],
        "available_tools": {"note": True},
    }

    out = LangGraphOrchestrator._collect_memory_and_notes_node(helper, state)  # type: ignore[misc]

    assert out["memories"] == []
    assert out["notes"] == []
    assert helper.memory_calls == 0
    assert helper.note_calls == 0
    assert out["_trace_outputs"]["business_input"]["skip_context_retrieval"] is True


def test_build_context_node_keeps_history_for_none_plan() -> None:
    """纯 none 计划仍应把历史对话带入上下文构建。"""
    helper = _BuildContextPassthrough()
    state = {
        "messages": [
            HumanMessage(content="AS4134 属于谁？"),
            AIMessage(content="上一轮回答"),
            HumanMessage(content="谢谢"),
        ],
        "plan_steps": [{"step_id": "step_1", "tool": "none", "arguments": {}}],
        "memories": [],
        "notes": [],
    }

    out = LangGraphOrchestrator._build_context_node(helper, state)  # type: ignore[misc]

    assert out["context"] == "拼装后的上下文"
    assert len(helper.calls) == 1
    call = helper.calls[0]
    assert call["user_query"] == "谢谢"
    assert [turn.content for turn in call["history"]] == [
        "AS4134 属于谁？",
        "上一轮回答",
    ]


def test_generate_answer_node_uses_llm_for_none_plan(monkeypatch) -> None:
    """纯 none 计划也应走上下文生成，而不是直接短路回复。"""
    streamed = []
    state = {
        "messages": [
            HumanMessage(
                content="统计 as_entity 中活跃 AS 的总量，并按国家前 10 排名。"
            ),
            AIMessage(content="上一轮回答"),
            HumanMessage(content="你好"),
        ],
        "plan_steps": [{"step_id": "step_1", "tool": "none", "arguments": {}}],
        "context": "这里是已包含历史对话的上下文。",
    }
    helper = _ConversationAnswerPassthrough()
    monkeypatch.setattr(
        orchestrator_module,
        "get_stream_writer",
        lambda: lambda payload: streamed.append(payload),
    )

    out = LangGraphOrchestrator._generate_answer_node(helper, state)  # type: ignore[misc]

    assert out["answer"] == "最终回答"
    assert len(out["messages"]) == 1
    assert isinstance(out["messages"][0], AIMessage)
    assert [payload["content"] for payload in streamed] == ["最终", "回答"]
    assert [
        (message.role, message.content) for message in helper.captured_messages
    ] == [
        ("system", orchestrator_module.SYSTEM_PROMPT),
        ("user", "统计 as_entity 中活跃 AS 的总量，并按国家前 10 排名。"),
        ("assistant", "上一轮回答"),
        ("user", "你好"),
    ]
    assert out["_trace_outputs"]["business_input"]["answer_mode"] == "conversation"
    assert out["_trace_outputs"]["business_input"]["context_length"] == len(
        state["context"]
    )


def test_build_python_input_bundle_uses_csv_files_and_lightweight_manifest() -> None:
    """Python 输入应把真实表格写成 CSV 文件，元数据中只保留摘要。"""
    helper = object.__new__(LangGraphOrchestrator)
    step_results = {
        "1": {
            "tool": "nl2sql",
            "objective": "按 AS 统计 IPv4 宣告数量",
            "result": {
                "sql": "SELECT asn, ipv4_count FROM demo",
                "result": {
                    "columns": ["asn", "ipv4_count"],
                    "rows": [[9808, 9867], [4538, 5148]],
                    "row_count": 2,
                },
            },
        }
    }

    input_data, input_files = LangGraphOrchestrator._build_python_input_bundle(  # type: ignore[misc]
        helper,
        task="绘制柱状图",
        raw_context="",
        depends_on=["1"],
        step_results=step_results,
    )

    assert input_data["datasets"][0]["format"] == "csv"
    assert input_data["datasets"][0]["file_path"].endswith(".csv")
    assert input_data["datasets"][0]["row_count"] == 2
    assert input_data["datasets"][0]["preview_rows"] == [[9808, 9867], [4538, 5148]]
    assert input_data["dependencies"][0]["result_summary"]["result"]["row_count"] == 2
    assert "rows" not in input_data["dependencies"][0]["result_summary"]["result"]
    assert len(input_files) == 1
    assert input_files[0]["path"].startswith("/workspace/input/datasets/")
    assert "9808,9867" in input_files[0]["content"]


class _NL2SQLMCPClient:
    """用于测试 NL2SQL 证据组装的最小桩对象。"""

    def __init__(self) -> None:
        self.calls = 0
        self.payloads = []

    def call_tool(self, _name, _payload, trace_id=""):
        self.calls += 1
        self.payloads.append(_payload)
        assert trace_id == "trace-test"
        if self.calls == 1:
            return {
                "sql": "SELECT org_name FROM asn_entity WHERE asn = 4134 LIMIT 200",
                "result": {
                    "columns": ["org_name"],
                    "rows": [["China Telecom"]],
                    "row_count": 1,
                },
            }
        return {
            "sql": "SELECT asn, org_name FROM asn_entity WHERE asn = 4134 LIMIT 1",
            "result": {
                "columns": ["asn", "org_name"],
                "rows": [[4134, "China Telecom"]],
                "row_count": 1,
            },
        }


def test_run_nl2sql_step_includes_result_preview_in_multi_query_evidence() -> None:
    """多条 NL2SQL 成功结果应把结果预览写入证据，避免只有 SQL 没有值。"""
    helper = SimpleNamespace(
        mcp_client=_NL2SQLMCPClient(),
        _normalize_text_list=LangGraphOrchestrator._normalize_text_list,
        _normalize_query_mode=LangGraphOrchestrator._normalize_query_mode,
        _build_retry_question=LangGraphOrchestrator._build_retry_question,
        _build_nl2sql_retry_instruction=LangGraphOrchestrator._build_nl2sql_retry_instruction,
        _detect_nl2sql_semantic_mismatch=LangGraphOrchestrator._detect_nl2sql_semantic_mismatch,
    )

    result = LangGraphOrchestrator._run_nl2sql_step(  # type: ignore[misc]
        helper,
        "step-1",
        "查询 AS4134 的运营商信息",
        {
            "questions": ["查询运营商", "补充确认"],
            "query_mode": "OTHER",
            "tables": ["asn_entity"],
        },
        "trace-test",
    )

    evidence = result["evidences"][0]
    assert evidence.source == "nl2sql"
    assert "China Telecom" in evidence.content
    assert "result=" in evidence.content


def test_run_nl2sql_step_does_not_append_objective_as_second_question() -> None:
    """已提供 question 时，不应再把 objective 自动追加成第二个子问题。"""
    fake_client = _NL2SQLMCPClient()
    helper = SimpleNamespace(
        mcp_client=fake_client,
        _normalize_text_list=LangGraphOrchestrator._normalize_text_list,
        _normalize_query_mode=LangGraphOrchestrator._normalize_query_mode,
        _build_retry_question=LangGraphOrchestrator._build_retry_question,
        _build_nl2sql_retry_instruction=LangGraphOrchestrator._build_nl2sql_retry_instruction,
        _detect_nl2sql_semantic_mismatch=LangGraphOrchestrator._detect_nl2sql_semantic_mismatch,
    )

    result = LangGraphOrchestrator._run_nl2sql_step(  # type: ignore[misc]
        helper,
        "step-1",
        "查询所有运营商名称为 China Telecom 的 AS 号",
        {"question": "列出 China Telecom 的所有 AS 号", "query_mode": "OTHER"},
        "trace-test",
    )

    assert fake_client.calls == 1
    assert fake_client.payloads[0]["question"] == "列出 China Telecom 的所有 AS 号"
    assert result["result"]["sql"].startswith("SELECT")
