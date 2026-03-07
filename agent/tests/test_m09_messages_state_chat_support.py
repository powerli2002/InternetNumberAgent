from __future__ import annotations

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


class _TracePassthrough:
    """用于测试节点输出的最小桩对象。"""

    class _LLM:
        @staticmethod
        def chat_stream(_messages):
            yield "最终"
            yield "回答"

    llm = _LLM()

    def _trace_node(self, _name, _state, fn):
        return fn()


def test_generate_answer_node_appends_ai_message(monkeypatch) -> None:
    """回答节点应把最终回答追加到 messages。"""
    state = {"context": "上下文内容"}
    helper = _TracePassthrough()
    monkeypatch.setattr(orchestrator_module, "get_stream_writer", lambda: lambda _payload: None)

    out = LangGraphOrchestrator._generate_answer_node(helper, state)  # type: ignore[misc]

    assert out["answer"] == "最终回答"
    assert len(out["messages"]) == 1
    assert isinstance(out["messages"][0], AIMessage)
    assert out["messages"][0].content == "最终回答"
