"""LangGraph 规划/核验 Function Calling schema。"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _normalize_tools(tools: Iterable[str]) -> List[str]:
    valid = {"nl2sql", "rag", "graph", "todo", "none"}
    normalized = [tool for tool in tools if tool in valid]
    if not normalized:
        return ["none"]
    return sorted(set(normalized))


def build_main_plan_schema(tools_allowed: Iterable[str]) -> Dict[str, Any]:
    """主流程规划 schema。"""
    tool_enum = _normalize_tools(tools_allowed)
    return {
        "type": "function",
        "function": {
            "name": "create_execution_plan",
            "description": "基于问题生成可执行计划，步骤需包含工具、依赖和参数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "step_id": {"type": "string"},
                                "objective": {"type": "string"},
                                "tool": {"type": "string", "enum": tool_enum},
                                "arguments": {"type": "object", "additionalProperties": True},
                                "depends_on": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "can_parallel": {"type": "boolean"},
                                "is_complex": {"type": "boolean"},
                                "expected_output": {"type": "string"},
                                "budget": {"type": "object", "additionalProperties": True},
                            },
                            "required": ["objective", "tool"],
                        },
                    },
                    "reason": {"type": "string"},
                    "max_replans": {"type": "integer"},
                },
                "required": ["steps", "reason"],
            },
        },
    }


def build_todo_subplan_schema(tools_allowed: Iterable[str]) -> Dict[str, Any]:
    """复杂任务子计划 schema。"""
    tool_enum = [tool for tool in _normalize_tools(tools_allowed) if tool not in {"todo", "none"}]
    if not tool_enum:
        tool_enum = ["rag"]
    return {
        "type": "function",
        "function": {
            "name": "create_todo_subplan",
            "description": "把复杂目标拆解为可执行的子步骤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "step_id": {"type": "string"},
                                "objective": {"type": "string"},
                                "tool": {"type": "string", "enum": tool_enum},
                                "arguments": {"type": "object", "additionalProperties": True},
                                "depends_on": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "can_parallel": {"type": "boolean"},
                            },
                            "required": ["objective", "tool"],
                        },
                    },
                    "reason": {"type": "string"},
                },
                "required": ["steps", "reason"],
            },
        },
    }


def build_conflict_schema() -> Dict[str, Any]:
    """冲突核验 schema。"""
    return {
        "type": "function",
        "function": {
            "name": "check_evidence_conflict",
            "description": "检查多工具证据是否存在冲突。",
            "parameters": {
                "type": "object",
                "properties": {
                    "verdict": {
                        "type": "string",
                        "enum": ["pass", "conflict", "unknown"],
                    },
                    "conflicts": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "notes": {"type": "string"},
                },
                "required": ["verdict", "conflicts"],
            },
        },
    }
