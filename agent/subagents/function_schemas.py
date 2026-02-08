"""子代理路由 Function schema。"""

from __future__ import annotations

from typing import Any, Dict, List


def subagent_router_schema(allowed_agents: List[str]) -> Dict[str, Any]:
    """返回子代理路由的 Function schema。"""
    return {
        "type": "function",
        "function": {
            "name": "route_subagents",
            "description": "根据任务选择最少数量的子代理执行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "agent": {"type": "string", "enum": allowed_agents},
                                "objective": {"type": "string"},
                                "constraints": {"type": "object", "additionalProperties": True},
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
                            "required": ["agent", "objective"],
                        },
                    },
                    "reason": {"type": "string"},
                    "max_turns": {"type": "integer"},
                },
                "required": ["plan", "reason"],
            },
        },
    }
