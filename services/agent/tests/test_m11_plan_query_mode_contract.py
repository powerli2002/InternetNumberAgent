from __future__ import annotations

from typing import Any, Dict

from agent.runtime.langgraph_orchestrator import LangGraphOrchestrator


class _TracePassthrough:
    """用于单测节点方法的最小桩对象。"""

    def _trace_node(self, _name: str, _state: Dict[str, Any], fn):
        return fn()


def test_validate_plan_fills_missing_query_mode_to_other() -> None:
    """nl2sql 步骤缺失 query_mode 时应回填 OTHER。"""
    helper = _TracePassthrough()
    state = {
        "plan_steps": [
            {
                "step_id": "s1",
                "objective": "核验关系",
                "tool": "nl2sql",
                "arguments": {"question": "AS9808和AS56046是否存在关系"},
                "depends_on": [],
            }
        ],
        "available_tools": {"nl2sql": True, "rag": True, "graph": True, "todo": True, "none": True},
        "plan_reason": "测试",
        "max_replans": 1,
    }

    out = LangGraphOrchestrator._validate_plan_node(helper, state)
    assert out["plan_steps"][0]["arguments"]["query_mode"] == "OTHER"


def test_validate_plan_normalizes_invalid_query_mode_to_other() -> None:
    """非法 query_mode 应归一为 OTHER。"""
    helper = _TracePassthrough()
    state = {
        "plan_steps": [
            {
                "step_id": "s1",
                "objective": "审计统计",
                "tool": "nl2sql",
                "arguments": {"question": "做一致性审计", "query_mode": "AGGREGATE_REQUIRED"},
                "depends_on": [],
            }
        ],
        "available_tools": {"nl2sql": True, "rag": True, "graph": True, "todo": True, "none": True},
        "plan_reason": "测试",
        "max_replans": 1,
    }

    out = LangGraphOrchestrator._validate_plan_node(helper, state)
    assert out["plan_steps"][0]["arguments"]["query_mode"] == "OTHER"


def test_validate_plan_keeps_valid_query_mode() -> None:
    """合法 query_mode 应保持并统一大写。"""
    helper = _TracePassthrough()
    state = {
        "plan_steps": [
            {
                "step_id": "s1",
                "objective": "做分组统计",
                "tool": "nl2sql",
                "arguments": {"question": "按国家分组", "query_mode": "group_by"},
                "depends_on": [],
            }
        ],
        "available_tools": {"nl2sql": True, "rag": True, "graph": True, "todo": True, "none": True},
        "plan_reason": "测试",
        "max_replans": 1,
    }

    out = LangGraphOrchestrator._validate_plan_node(helper, state)
    assert out["plan_steps"][0]["arguments"]["query_mode"] == "GROUP_BY"
