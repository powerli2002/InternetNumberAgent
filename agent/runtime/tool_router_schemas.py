"""Function Calling 路由 schema。"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


def tool_router_schema() -> Dict[str, Any]:
    """规划阶段 schema：只输出计划，不直接绑定工具。"""
    # 该 schema 直接传给 LLM 的 tools 参数，要求模型先给出任务分解计划。
    return {
        "type": "function",
        "function": {
            "name": "route_plan",
            "description": "根据用户问题输出执行计划（plan），每步只描述目标与约束，不直接选择工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    # plan 是可执行动作列表，每一项代表一步任务目标。
                    "plan": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                # objective 是该步自然语言目标，后续 step router 将基于它选工具。
                                "objective": {"type": "string"},
                                "constraints": {
                                    "type": "object",
                                    "properties": {
                                        # 可用表范围，后续执行器会做白名单收敛。
                                        "tables": {"type": "array", "items": {"type": "string"}},
                                        "top_k": {"type": "integer"},
                                        "enable_column_retrieval": {"type": "boolean"},
                                    },
                                    "additionalProperties": True,
                                },
                                "expected_output": {"type": "string"},
                                "budget": {
                                    "type": "object",
                                    "properties": {
                                        "max_tokens": {"type": "integer"},
                                        "max_time_ms": {"type": "integer"},
                                    },
                                    "additionalProperties": True,
                                },
                            },
                            # 规划阶段至少需要目标。
                            "required": ["objective"],
                        },
                    },
                    # reason 记录规划依据，便于审计与排错。
                    "reason": {"type": "string"},
                    "max_turns": {"type": "integer"},
                },
                "required": ["plan", "reason"],
            },
        },
    }


def _normalize_tools(tools_allowed: Iterable[str] | None) -> List[str]:
    base = {"nl2sql", "rag", "todo", "none"}
    if tools_allowed is None:
        return sorted(base)
    normalized = [tool for tool in tools_allowed if tool in base]
    if not normalized:
        return sorted(base)
    return sorted(set(normalized))


def step_router_schema(tools_allowed: Iterable[str] | None = None) -> Dict[str, Any]:
    """执行阶段 schema：针对单个计划步骤选择工具并给出参数。"""
    tool_enum = _normalize_tools(tools_allowed)
    return {
        "type": "function",
        "function": {
            "name": "route_step_tool",
            "description": "针对单个计划步骤选择一个工具，并输出该工具的调用参数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool": {
                        "type": "string",
                        "enum": tool_enum,
                        "description": "本步骤选择的工具。",
                    },
                    "objective": {
                        "type": "string",
                        "description": "当前步骤的执行目标，可与计划目标一致或更具体。",
                    },
                    "arguments": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "query": {"type": "string"},
                            "tables": {"type": "array", "items": {"type": "string"}},
                            "top_k": {"type": "integer"},
                            "enable_column_retrieval": {"type": "boolean"},
                        },
                        "additionalProperties": True,
                        "description": "工具参数对象。tool=none 时可为空对象。",
                    },
                    "reason": {"type": "string"},
                },
                "required": ["tool"],
            },
        },
    }
