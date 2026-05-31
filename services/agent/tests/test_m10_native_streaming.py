from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
import pytest

import agent.runtime.langgraph_orchestrator as orchestrator_module
from agent.runtime.langgraph_orchestrator import LangGraphOrchestrator


class _StreamingNodeHelper:
    """用于测试 generate_answer 节点流式输出的最小桩对象。"""

    class _LLM:
        @staticmethod
        def chat_stream(_messages):
            yield "最终"
            yield "回答"

    llm = _LLM()

    def _trace_node(self, _name, _state, fn):
        return fn()


def test_generate_answer_node_emits_custom_stream_events(monkeypatch) -> None:
    """generate_answer 节点应通过 LangGraph custom stream 输出增量文本。"""
    streamed_events: List[Dict[str, Any]] = []
    monkeypatch.setattr(
        orchestrator_module,
        "get_stream_writer",
        lambda: lambda payload: streamed_events.append(payload),
    )

    out = LangGraphOrchestrator._generate_answer_node(
        _StreamingNodeHelper(), {"context": "上下文"}
    )  # type: ignore[misc]

    assert out["answer"] == "最终回答"
    assert isinstance(out["messages"][0], AIMessage)
    assert out["messages"][0].content == "最终回答"
    assert streamed_events == [
        {
            "event": "messages",
            "role": "assistant",
            "content": "最终",
            "node": "generate_answer",
        },
        {
            "event": "messages",
            "role": "assistant",
            "content": "回答",
            "node": "generate_answer",
        },
    ]
    assert out["_trace_outputs"]["business_output"]["chunk_count"] == 2


class _FakeGraph:
    """模拟 LangGraph stream/get_state 行为。"""

    def __init__(self) -> None:
        self.invoke_calls: List[Dict[str, Any]] = []
        self.stream_calls: List[Dict[str, Any]] = []
        self.get_state_calls: List[Dict[str, Any]] = []

    def invoke(self, init_state, *, config=None):
        self.invoke_calls.append(
            {
                "init_state": init_state,
                "config": config,
            }
        )
        return {
            "answer": "答案",
            "sources": ["rag"],
            "conflicts": [],
            "replan_count": 0,
            "evidences": [],
            "plan_reason": "无需检索",
        }

    def stream(self, init_state, *, config=None, stream_mode=None):
        self.stream_calls.append(
            {
                "init_state": init_state,
                "config": config,
                "stream_mode": stream_mode,
            }
        )
        yield (
            "custom",
            {
                "event": "messages",
                "role": "assistant",
                "content": "答",
                "node": "generate_answer",
            },
        )
        yield ("updates", {"generate_answer": {"answer": "答案"}})

    def get_state(self, config):
        self.get_state_calls.append(config)
        return SimpleNamespace(
            values={
                "answer": "答案",
                "sources": ["rag"],
                "conflicts": [],
                "replan_count": 0,
                "evidences": [],
                "plan_reason": "无需检索",
            }
        )


class _StreamingOrchestratorHelper:
    """用于测试 stream_response 的最小桩对象。"""

    def __init__(self) -> None:
        self.graph = _FakeGraph()
        self.finalize_calls: List[Dict[str, Any]] = []

    def _turn_setup_middleware(self, user_message: str, thread_id: str | None):
        resolved_thread_id = str(thread_id or "thread-test")
        return SimpleNamespace(
            user_message=user_message,
            thread_id=resolved_thread_id,
            thread_config={"configurable": {"thread_id": resolved_thread_id}},
            trace_id="trace-test",
            init_state={"messages": [HumanMessage(content=user_message)]},
            main_flow_trace={"stage": "main_flow_start"},
        )

    def _trace_scope_middleware(self, _turn_context: Any):
        return nullcontext(SimpleNamespace())

    def _node_audit_middleware(self):
        return nullcontext([])

    def _finalize_middleware(self, **kwargs):
        self.finalize_calls.append(kwargs["final_state"])
        turn_context = kwargs["turn_context"]
        return "答案", {
            "trace_id": turn_context.trace_id,
            "thread_id": turn_context.thread_id,
            "sources": ["rag"],
            "conflicts": [],
            "plan_reason": "无需检索",
            "replan_count": 0,
            "evidence_count": 0,
            "evidence_sources": [],
        }


def test_respond_uses_turn_middlewares_and_returns_final_metadata() -> None:
    """respond 应通过 turn middleware 骨架执行 graph.invoke 并统一收尾。"""
    helper = _StreamingOrchestratorHelper()

    answer, metadata = LangGraphOrchestrator.respond(  # type: ignore[misc]
        helper,
        "测试问题",
        thread_id="thread-1",
    )

    assert answer == "答案"
    assert helper.graph.invoke_calls == [
        {
            "init_state": {"messages": [HumanMessage(content="测试问题")]},
            "config": {"configurable": {"thread_id": "thread-1"}},
        }
    ]
    assert helper.finalize_calls[0]["answer"] == "答案"
    assert metadata["trace_id"] == "trace-test"
    assert metadata["thread_id"] == "thread-1"
    assert metadata["sources"] == ["rag"]


def test_stream_response_uses_langgraph_native_stream_and_updates_metadata() -> None:
    """stream_response 应直接消费 graph.stream，并在结束后补齐最终 metadata。"""
    helper = _StreamingOrchestratorHelper()

    stream_iter, metadata = LangGraphOrchestrator.stream_response(  # type: ignore[misc]
        helper,
        "测试问题",
        thread_id="thread-1",
    )

    assert metadata["trace_id"] == "trace-test"
    assert metadata["sources"] == []

    events = list(stream_iter)

    assert events == [
        (
            "custom",
            {
                "event": "messages",
                "role": "assistant",
                "content": "答",
                "node": "generate_answer",
            },
        ),
        ("updates", {"generate_answer": {"answer": "答案"}}),
    ]
    assert helper.graph.stream_calls[0]["stream_mode"] == ["custom", "updates"]
    assert helper.graph.get_state_calls == [{"configurable": {"thread_id": "thread-1"}}]
    assert helper.finalize_calls[0]["answer"] == "答案"
    assert metadata["sources"] == ["rag"]
    assert metadata["plan_reason"] == "无需检索"


class _FakeStore:
    """替代 HTTP 层线程存储，避免测试依赖真实数据库。"""

    def update_metadata(self, _thread_id: str, _updates: Dict[str, Any]) -> None:
        return None


class _FakeStreamingAgent:
    """替代 HTTP 层 agent，输出原生 LangGraph 流事件。"""

    def stream_response(self, _user_message: str, thread_id: str | None = None):
        assert thread_id == "thread-1"
        return (
            iter(
                [
                    (
                        "custom",
                        {
                            "event": "messages",
                            "role": "assistant",
                            "content": "答",
                            "node": "generate_answer",
                        },
                    ),
                    ("updates", {"generate_answer": {"answer": "答案"}}),
                ]
            ),
            {"trace_id": "trace-1"},
        )

    def get_state(self, thread_id: str):
        assert thread_id == "thread-1"
        return SimpleNamespace(
            values={"answer": "答案", "messages": [AIMessage(content="答案")]}
        )


def test_http_stream_endpoint_forwards_native_custom_and_updates(monkeypatch) -> None:
    """HTTP SSE 应把 custom/updates 事件转成前端可消费的消息流。"""
    try:
        import agent.services.http.server as server_module
    except RuntimeError as exc:
        pytest.skip(f"测试环境缺少 HTTP 服务依赖: {exc}")

    monkeypatch.setattr(server_module, "store", _FakeStore())
    monkeypatch.setattr(server_module, "agent", _FakeStreamingAgent())

    client = TestClient(server_module.app)
    with client.stream(
        "POST",
        "/threads/thread-1/runs/stream",
        json={
            "assistant_id": "fusion-agent",
            "input": {"message": "测试问题"},
            "stream_mode": ["messages", "updates", "values"],
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: metadata" in body
    assert "event: messages" in body
    assert '"content": "答"' in body
    assert "event: updates" in body
    assert "event: values" in body
