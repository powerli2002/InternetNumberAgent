from __future__ import annotations

import asyncio
import contextvars
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from langchain_core.messages import HumanMessage

import agent.core.tracing as tracing_module
import agent.runtime.langgraph_orchestrator as orchestrator_module
import agent.services.mcp.client as mcp_client_module
from agent.core.tracing import LangSmithTracer
from agent.runtime.langgraph_orchestrator import LangGraphOrchestrator, _NODE_RECORDS_CTX
from agent.services.mcp.client import MCPToolClient


_STEP_CTX: contextvars.ContextVar[str] = contextvars.ContextVar("step_ctx", default="")
_MCP_CTX: contextvars.ContextVar[str] = contextvars.ContextVar("mcp_ctx", default="")


class _TraceNodePassthrough:
    """测试 _execute_ready_node 的最小桩对象。"""

    def _trace_node(self, _name: str, _state: Dict[str, Any], fn):
        return fn()

    def _execute_single_step(self, step: Dict[str, Any], _state: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "step_id": str(step.get("step_id") or ""),
            "status": "ok",
            "result": {"ctx": _STEP_CTX.get()},
            "evidences": [],
            "sources": ["ctx-test"],
        }


class _RecordingRun:
    """记录 add_inputs/add_outputs 调用的测试 run。"""

    def __init__(self) -> None:
        self.inputs: List[Dict[str, Any]] = []
        self.outputs: List[Dict[str, Any]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def add_inputs(self, inputs=None):
        if isinstance(inputs, dict):
            self.inputs.append(inputs)

    def add_outputs(self, outputs=None):
        if isinstance(outputs, dict):
            self.outputs.append(outputs)

class _FakeRunTree:
    """模拟 LangSmith 当前 run tree，用于测试 headers 透传。"""

    def __init__(self, headers: Dict[str, str]) -> None:
        self._headers = headers

    def to_headers(self) -> Dict[str, str]:
        return dict(self._headers)


def test_trace_node_writes_complete_node_audit_to_current_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """_trace_node 应把完整节点审计写入当前自动节点 run。"""
    state = {
        "trace_id": "trace-test",
        "messages": [HumanMessage(content="测试问题")],
        "pending_ids": [],
        "completed_ids": [],
        "ready_ids": [],
        "plan_steps": [],
        "sources": [],
        "conflicts": [],
        "replan_count": 0,
        "need_replan": False,
    }
    records: List[Dict[str, Any]] = []
    run = _RecordingRun()
    monkeypatch.setattr(orchestrator_module, "get_current_run_tree", lambda: run)
    token = _NODE_RECORDS_CTX.set(records)
    try:
        out = LangGraphOrchestrator._trace_node(  # type: ignore[misc]
            object(),
            "plan",
            state,
            lambda: {
                "plan_steps": [],
                "_trace_outputs": {
                    "business_input": {"query": "测试问题"},
                    "prompt_records": [{"stage": "plan_request"}],
                    "context_payload": {"planner_payload": {"query": "测试问题"}},
                    "business_output": {"plan_steps": []},
                    "flag": "ok",
                },
            },
        )
    finally:
        _NODE_RECORDS_CTX.reset(token)

    assert out == {"plan_steps": []}
    assert len(records) == 1
    assert records[0]["node_name"] == "plan"
    assert records[0]["prompt_records"] == [{"stage": "plan_request"}]
    assert records[0]["business_input"] == {"query": "测试问题"}
    assert records[0]["context_payload"] == {"planner_payload": {"query": "测试问题"}}
    assert records[0]["business_output"] == {"plan_steps": []}
    assert records[0]["trace_extras"]["flag"] == "ok"
    assert len(run.inputs) == 1
    assert run.inputs[0]["prompt_records"] == [{"stage": "plan_request"}]
    assert run.inputs[0]["context_payload"] == {"planner_payload": {"query": "测试问题"}}
    assert len(run.outputs) == 1
    assert run.outputs[0]["business_output"] == {"plan_steps": []}
    assert run.outputs[0]["trace_extras"]["flag"] == "ok"


def test_execute_ready_thread_pool_inherits_contextvars() -> None:
    """并发步骤执行应继承父上下文，避免在线程中丢失 tracing parent。"""
    helper = _TraceNodePassthrough()
    state = {
        "ready_ids": ["step_1", "step_2"],
        "pending_ids": ["step_1", "step_2"],
        "completed_ids": [],
        "plan_steps": [
            {"step_id": "step_1", "depends_on": []},
            {"step_id": "step_2", "depends_on": []},
        ],
        "step_results": {},
        "evidences": [],
        "sources": [],
    }
    token = _STEP_CTX.set("parent-value")
    try:
        out = LangGraphOrchestrator._execute_ready_node(helper, state)  # type: ignore[misc]
    finally:
        _STEP_CTX.reset(token)

    assert out["step_results"]["step_1"]["result"]["ctx"] == "parent-value"
    assert out["step_results"]["step_2"]["result"]["ctx"] == "parent-value"


def test_mcp_run_sync_preserves_context_in_running_loop() -> None:
    """_run_sync 在已有事件循环场景下应显式复制 contextvars。"""

    async def _read_ctx() -> str:
        return _MCP_CTX.get()

    async def _outer() -> str:
        token = _MCP_CTX.set("trace-parent")
        try:
            return MCPToolClient._run_sync(_read_ctx())
        finally:
            _MCP_CTX.reset(token)

    assert asyncio.run(_outer()) == "trace-parent"


def test_mcp_tool_propagates_langsmith_headers_without_manual_subrun(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP 客户端应只透传当前 LangSmith headers，不再手工创建客户端子 run。"""

    class _FakeTransport:
        def __init__(self, *, url: str, headers: Dict[str, str] | None = None) -> None:
            self.url = url
            self.headers = headers

    class _FakeClient:
        calls: List[Dict[str, Any]] = []

        def __init__(self, transport, *_args, **_kwargs) -> None:
            self.transport = transport

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def call_tool(self, **kwargs):
            kwargs["headers"] = dict(self.transport.headers or {})
            _FakeClient.calls.append(kwargs)
            return SimpleNamespace(data={"ok": True, "tool": kwargs.get("name")})

    monkeypatch.setattr(mcp_client_module, "StreamableHttpTransport", _FakeTransport)
    monkeypatch.setattr(mcp_client_module, "Client", _FakeClient)
    monkeypatch.setattr(
        mcp_client_module,
        "get_current_run_tree",
        lambda: _FakeRunTree({"x-langsmith-trace": "trace-header", "x-langsmith-parent": "node-run"}),
    )

    client = MCPToolClient(server_url="http://127.0.0.1:2032/mcp")

    payload = client.call_tool(
        name="rag_search",
        arguments={"query": "测试"},
        trace_id="trace-1",
    )
    assert payload["ok"] is True
    assert payload["tool"] == "rag_search"
    assert _FakeClient.calls[0]["meta"]["trace_id"] == "trace-1"
    assert _FakeClient.calls[0]["headers"] == {
        "x-langsmith-trace": "trace-header",
        "x-langsmith-parent": "node-run",
    }

    _FakeClient.calls.clear()
    monkeypatch.setattr(mcp_client_module, "get_current_run_tree", lambda: None)
    payload_no_parent = client.call_tool(
        name="rag_search",
        arguments={"query": "测试"},
        trace_id="trace-2",
    )
    assert payload_no_parent["ok"] is True
    assert _FakeClient.calls[0]["meta"]["trace_id"] == "trace-2"
    assert _FakeClient.calls[0]["headers"] == {}


def test_tracer_builds_tags_and_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """LangSmithTracer 应只负责配置加载与 tags/metadata 合并。"""
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_WORKSPACE_ID", "ws-test")
    monkeypatch.setenv("LANGSMITH_PROJECT", "proj-test")
    monkeypatch.setenv("LANGSMITH_DEFAULT_TAGS", "fusion,langgraph")

    monkeypatch.setattr(tracing_module, "Client", lambda *args, **kwargs: object())
    tracer = LangSmithTracer(project_name="proj-test")

    assert tracer.enabled is True
    assert tracer.project_name == "proj-test"
    assert tracer.client is not None
    assert tracer.build_tags(["langgraph", "qa"]) == ["fusion", "langgraph", "qa"]
    metadata = tracer.build_metadata({"trace_id": "trace-1"})
    assert metadata["service"] == "fusion-agent"
    assert metadata["trace_id"] == "trace-1"
    assert metadata["timezone"] == tracer.timezone
    assert "local_time" in metadata
