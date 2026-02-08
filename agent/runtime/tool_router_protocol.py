"""主代理工具路由协议。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


_ALLOWED_TOOL_NAMES = {"nl2sql", "rag", "todo", "none"}


def _ensure_str(value: Any, field_name: str) -> str:
    if value is None:
        raise ValueError(f"缺少字段: {field_name}")
    if not isinstance(value, str):
        raise TypeError(f"字段 {field_name} 必须为字符串")
    if not value.strip():
        raise ValueError(f"字段 {field_name} 不能为空")
    return value


def _ensure_dict(value: Any, field_name: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"字段 {field_name} 必须为对象")
    return value


def _ensure_optional_str(value: Any, field_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"字段 {field_name} 必须为字符串")
    return value.strip()


def _ensure_list(value: Any, field_name: str) -> List[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"字段 {field_name} 必须为数组")
    return value


@dataclass
class ToolPlanStep:
    """规划阶段的单步计划（不包含具体工具）。"""

    objective: str
    constraints: Dict[str, Any] = field(default_factory=dict)
    expected_output: str = "结构化结果 + 证据摘要"
    budget: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective": self.objective,
            "constraints": self.constraints,
            "expected_output": self.expected_output,
            "budget": self.budget,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolPlanStep":
        return cls(
            objective=_ensure_str(data.get("objective"), "objective"),
            constraints=_ensure_dict(data.get("constraints"), "constraints"),
            expected_output=data.get("expected_output") or "结构化结果 + 证据摘要",
            budget=_ensure_dict(data.get("budget"), "budget"),
        )


@dataclass
class ToolActionStep:
    """执行阶段的单步动作（选择具体工具并给出参数）。"""

    tool: str
    objective: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool,
            "objective": self.objective,
            "arguments": self.arguments,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolActionStep":
        tool = _ensure_str(data.get("tool"), "tool")
        if tool not in _ALLOWED_TOOL_NAMES:
            raise ValueError(f"未知工具: {tool}")
        return cls(
            tool=tool,
            objective=_ensure_optional_str(data.get("objective"), "objective"),
            arguments=_ensure_dict(data.get("arguments"), "arguments"),
        )


@dataclass
class ToolRouterDecision:
    """主代理工具路由输出。"""

    plan: List[ToolPlanStep]
    reason: str
    max_turns: int = 2

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolRouterDecision":
        plan_data = _ensure_list(data.get("plan"), "plan")
        plan = [ToolPlanStep.from_dict(item) for item in plan_data]
        if not plan:
            raise ValueError("ToolRouterDecision.plan 不能为空")
        max_turns = data.get("max_turns") or len(plan)
        try:
            max_turns = max(1, int(max_turns))
        except Exception:
            max_turns = len(plan)
        return cls(
            plan=plan,
            reason=_ensure_str(data.get("reason"), "reason"),
            max_turns=max_turns,
        )


def allowed_tool_names() -> List[str]:
    """返回允许的工具名称列表。"""
    return sorted(_ALLOWED_TOOL_NAMES)
