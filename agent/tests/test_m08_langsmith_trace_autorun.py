from __future__ import annotations

import asyncio
import contextvars
from typing import Any, Dict, List

import pytest

import agent.core.tracing as tracing_module
from agent.core.tracing import LangSmithTracer
from agent.runtime.langgraph_orchestrator import LangGraphOrchestrator, _NODE_RECORDS_CTX
from agent.services.mcp.client import MCPToolClient


_STEP_CTX: contextvars.ContextVar[str] = contextvars.ContextVar("step_ctx", default="")
_MCP_CTX: contextvars.ContextVar[str] = contextvars.ContextVar("mcp_ctx", default="")


class _TraceNodePassthrough:
    """测试 _execute_ready_node 的最小桩对象。"""

    def _trace_node(self, _name: str, _state: Dict[str, Any], fn):
        return fn()

    def _execute_single_step(self, step: Dict[str, Any], _state: Dict[str, Any], _root_run=None) -> Dict[str, Any]:
        return {
            "step_id": str(step.get("step_id") or ""),
            "status": "ok",
            "result": {"ctx": _STEP_CTX.get()},
            "evidences": [],
            "sources": ["ctx-test"],
        }


class _DummyRun:
    """模拟 LangSmith run 上下文。"""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def add_outputs(self, _outputs=None):
        return None


def test_trace_node_collects_records_without_manual_subrun() -> None:
    """_trace_node 应仅记录节点聚合信息，不再创建 graph_node:* 子 run。"""
    state = {
        "trace_id": "trace-test",
        "query": "测试问题",
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
    token = _NODE_RECORDS_CTX.set(records)
    try:
        out = LangGraphOrchestrator._trace_node(  # type: ignore[misc]
            object(),
            "plan",
            state,
            lambda: {
                "plan_steps": [],
                "_trace_outputs": {"prompt_records": [{"stage": "plan_request"}], "flag": "ok"},
            },
        )
    finally:
        _NODE_RECORDS_CTX.reset(token)

    assert out == {"plan_steps": []}
    assert len(records) == 1
    assert records[0]["node_name"] == "plan"
    assert records[0]["prompt_records"] == [{"stage": "plan_request"}]
    assert records[0]["trace_extras"]["flag"] == "ok"


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


def test_tracer_sampling_is_request_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    """采样应按请求一次决策，子 run 不可独立采样。"""
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_WORKSPACE_ID", "ws-test")
    monkeypatch.setenv("LANGSMITH_PROJECT", "proj-test")

    calls: List[Dict[str, Any]] = []

    def _fake_trace(**kwargs):
        calls.append(kwargs)
        return _DummyRun()

    monkeypatch.setattr(tracing_module, "Client", lambda *args, **kwargs: object())
    monkeypatch.setattr(tracing_module, "trace", _fake_trace)

    # 场景一：根 run 未采样，子 run 不应被独立采样。
    monkeypatch.setenv("LANGSMITH_SAMPLE_RATE", "0")
    tracer = LangSmithTracer(project_name="proj-test")
    with tracer.start_run(name="root", run_type="chain") as root:
        with tracer.start_run(name="child", run_type="chain", parent=root):
            pass
    assert len(calls) == 0

    # 场景二：根 run 采样时，子 run 继承同一请求采样结果。
    monkeypatch.setenv("LANGSMITH_SAMPLE_RATE", "1")
    tracer2 = LangSmithTracer(project_name="proj-test")
    with tracer2.start_run(name="root2", run_type="chain") as root2:
        with tracer2.start_run(name="child2", run_type="chain", parent=root2):
            pass
    assert len(calls) == 2
    assert calls[0]["name"] == "root2"
    assert calls[1]["name"] == "child2"
