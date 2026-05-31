from __future__ import annotations

from typing import Any, Dict, List

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
    assert step_map["s2"]["tool"] == "rag"


def test_validate_plan_splits_count_and_example_nl2sql_request() -> None:
    """混合“数量+示例”的单步 NL2SQL 请求应拆成两个独立步骤。"""
    helper = _TracePassthrough()
    state = {
        "plan_steps": [
            {
                "step_id": "s1",
                "objective": "给出 org_entity 中名称包含 telecom 的组织数量，并列出前 5 个示例。",
                "tool": "nl2sql",
                "arguments": {
                    "question": "给出 org_entity 中名称包含 telecom 的组织数量，并列出前 5 个示例。",
                },
                "depends_on": [],
            }
        ],
        "available_tools": {"nl2sql": True, "rag": True, "graph": True, "none": True},
        "plan_reason": "测试拆分",
        "max_replans": 1,
    }

    out = LangGraphOrchestrator._validate_plan_node(helper, state)

    assert [step["step_id"] for step in out["plan_steps"]] == ["s1", "s1_examples"]
    assert out["plan_steps"][0]["arguments"]["query_mode"] == "COUNT"
    assert "只返回满足条件的总数量" in out["plan_steps"][0]["arguments"]["question"]
    assert out["plan_steps"][1]["arguments"]["query_mode"] == "OTHER"
    assert "只列出前 5 个示例" in out["plan_steps"][1]["arguments"]["question"]


def test_reset_turn_state_clears_volatile_runtime_fields() -> None:
    """新 turn 入口应清空上一轮遗留的执行态，但不改动历史消息。"""
    helper = _TracePassthrough()
    state = {
        "messages": ["历史消息", "当前消息"],
        "trace_id": "trace-current",
        "available_tools": {"nl2sql": True},
        "plan_steps": [{"step_id": "s1"}],
        "plan_reason": "旧计划",
        "max_replans": 3,
        "replan_count": 2,
        "pending_ids": ["s1"],
        "completed_ids": ["s0"],
        "ready_ids": ["s1"],
        "step_results": {"s0": {"status": "ok", "result": {"rows": [["巨量结果"]]}}},
        "evidences": ["旧证据"],
        "sources": ["nl2sql"],
        "memories": ["旧记忆"],
        "notes": ["旧笔记"],
        "conflicts": ["旧冲突"],
        "need_replan": True,
        "context": "旧上下文",
        "answer": "旧回答",
        "metadata": {"old": True},
        "error": "旧错误",
    }

    out = LangGraphOrchestrator._reset_turn_state_node(helper, state)

    assert out["available_tools"] == {}
    assert out["plan_steps"] == []
    assert out["plan_reason"] == ""
    assert out["max_replans"] == 1
    assert out["replan_count"] == 0
    assert out["pending_ids"] == []
    assert out["completed_ids"] == []
    assert out["ready_ids"] == []
    assert out["step_results"] == {}
    assert out["evidences"] == []
    assert out["sources"] == []
    assert out["memories"] == []
    assert out["notes"] == []
    assert out["conflicts"] == []
    assert out["need_replan"] is False
    assert out["context"] == ""
    assert out["answer"] == ""
    assert out["metadata"] == {}
    assert out["error"] == ""
    assert "messages" not in out


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
    }

    for tool_name, expected in tool_to_expected.items():
        step = {
            "step_id": f"step_{tool_name}",
            "objective": "测试任务",
            "tool": tool_name,
            "arguments": {},
        }
        result = LangGraphOrchestrator._execute_single_step(fake, step, state)
        assert fake.called[-1] == expected
        assert result["status"] == "ok"

    unsupported_step = {
        "step_id": "step_todo",
        "objective": "测试任务",
        "tool": "todo",
        "arguments": {},
    }
    called_before = list(fake.called)
    unsupported_result = LangGraphOrchestrator._execute_single_step(fake, unsupported_step, state)
    assert fake.called == called_before
    assert unsupported_result["status"] == "ok"
    assert unsupported_result["result"]["tool"] == "none"
