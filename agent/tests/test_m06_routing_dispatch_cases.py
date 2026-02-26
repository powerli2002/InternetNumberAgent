from __future__ import annotations

from typing import Any, Dict, List

import pytest

from agent.runtime.langgraph_orchestrator import LangGraphOrchestrator


class _TracePassthrough:
    """用于测试节点函数的最小桩对象。"""

    def _trace_node(self, _name: str, _state: Dict[str, Any], fn):
        return fn()


class _ExecuteRouterFake:
    """用于验证工具路由分发是否命中正确执行器。"""

    def __init__(self) -> None:
        self.called: List[str] = []

    def _run_nl2sql_step(self, *args, **kwargs):
        self.called.append("nl2sql")
        return {"status": "ok", "result": {"tool": "nl2sql"}, "evidences": [], "sources": ["nl2sql"]}

    def _run_rag_step(self, *args, **kwargs):
        self.called.append("rag")
        return {"status": "ok", "result": {"tool": "rag"}, "evidences": [], "sources": ["rag"]}

    def _run_graph_step(self, *args, **kwargs):
        self.called.append("graph")
        return {"status": "ok", "result": {"tool": "graph"}, "evidences": [], "sources": ["neo4j"]}

    def _run_todo_subgraph(self, *args, **kwargs):
        self.called.append("todo")
        return {"status": "ok", "result": {"tool": "todo"}, "evidences": [], "sources": ["todo"]}


CLASSIFY_CASES = [
    ("AS4134有多少IPv6前缀", "ip_query"),
    ("ASN 4837 的上游有哪些", "as_query"),
    ("这个域名属于哪个组织", "domain_query"),
]


@pytest.mark.parametrize("query,expected", CLASSIFY_CASES)
def test_classify_question_records(query: str, expected: str) -> None:
    """自然语言分类结果应稳定，便于路由规划。"""
    assert LangGraphOrchestrator._classify_question(query) == expected


def test_validate_plan_downgrade_unavailable_tools() -> None:
    """规划步骤中不可用工具应被降级到可用工具或 none。"""
    state = {
        "plan_steps": [
            {
                "step_id": "s1",
                "objective": "图查询任务",
                "tool": "graph",
                "arguments": {"cypher": "MATCH (n) RETURN n LIMIT 1"},
                "depends_on": [],
            },
            {
                "step_id": "s2",
                "objective": "待办任务",
                "tool": "todo",
                "arguments": {},
                "depends_on": [],
            },
        ],
        "available_tools": {
            "nl2sql": True,
            "rag": True,
            "graph": False,
            "todo": False,
            "none": True,
        },
        "plan_reason": "测试降级",
        "max_replans": 1,
    }
    helper = _TracePassthrough()
    out = LangGraphOrchestrator._validate_plan_node(helper, state)

    step_map = {step["step_id"]: step for step in out["plan_steps"]}
    assert step_map["s1"]["tool"] == "rag"
    assert step_map["s2"]["tool"] == "none"


def test_dispatch_dependency_resolution() -> None:
    """调度器应只派发依赖满足的步骤。"""
    helper = _TracePassthrough()

    state_first = {
        "pending_ids": ["step_1", "step_2"],
        "completed_ids": [],
        "plan_steps": [
            {"step_id": "step_1", "depends_on": []},
            {"step_id": "step_2", "depends_on": ["step_1"]},
        ],
        "conflicts": [],
    }
    out_first = LangGraphOrchestrator._dispatch_node(helper, state_first)
    assert out_first["ready_ids"] == ["step_1"]

    state_second = {
        "pending_ids": ["step_2"],
        "completed_ids": ["step_1"],
        "plan_steps": [
            {"step_id": "step_1", "depends_on": []},
            {"step_id": "step_2", "depends_on": ["step_1"]},
        ],
        "conflicts": [],
    }
    out_second = LangGraphOrchestrator._dispatch_node(helper, state_second)
    assert out_second["ready_ids"] == ["step_2"]


def test_execute_single_step_routes_to_expected_tool_runner() -> None:
    """执行器应按 tool 字段路由到对应方法。"""
    fake = _ExecuteRouterFake()
    state = {"trace_id": "trace-routing-test", "available_tools": {}}

    tool_to_expected = {
        "nl2sql": "nl2sql",
        "rag": "rag",
        "graph": "graph",
        "todo": "todo",
    }

    for tool_name, expected in tool_to_expected.items():
        step = {
            "step_id": f"step_{tool_name}",
            "objective": "测试任务",
            "tool": tool_name,
            "arguments": {},
        }
        result = LangGraphOrchestrator._execute_single_step(fake, step, state, None)
        assert fake.called[-1] == expected
        assert result["status"] == "ok"
