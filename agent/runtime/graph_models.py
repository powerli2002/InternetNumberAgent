"""LangGraph 运行时数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal


ToolName = Literal["nl2sql", "rag", "graph", "todo", "none"]


@dataclass
class GraphPlanStep:
    """图编排中的执行步骤。"""

    step_id: str
    objective: str
    tool: ToolName
    arguments: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    can_parallel: bool = True
    is_complex: bool = False
    expected_output: str = "结构化结果 + 证据摘要"
    budget: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "objective": self.objective,
            "tool": self.tool,
            "arguments": self.arguments,
            "depends_on": self.depends_on,
            "can_parallel": self.can_parallel,
            "is_complex": self.is_complex,
            "expected_output": self.expected_output,
            "budget": self.budget,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], idx: int) -> "GraphPlanStep":
        raw_step_id = str(data.get("step_id") or "").strip()
        step_id = raw_step_id or f"step_{idx + 1}"
        objective = str(data.get("objective") or "").strip()
        if not objective:
            raise ValueError(f"步骤 {step_id} 缺少 objective")

        tool = str(data.get("tool") or "none").strip().lower()
        if tool not in {"nl2sql", "rag", "graph", "todo", "none"}:
            tool = "none"

        arguments = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
        depends_on_raw = data.get("depends_on") if isinstance(data.get("depends_on"), list) else []
        depends_on = [str(x).strip() for x in depends_on_raw if str(x).strip()]
        expected_output = str(data.get("expected_output") or "结构化结果 + 证据摘要").strip()
        budget = data.get("budget") if isinstance(data.get("budget"), dict) else {}

        return cls(
            step_id=step_id,
            objective=objective,
            tool=tool,  # type: ignore[arg-type]
            arguments=arguments,
            depends_on=depends_on,
            can_parallel=bool(data.get("can_parallel", True)),
            is_complex=bool(data.get("is_complex", False)),
            expected_output=expected_output,
            budget=budget,
        )


@dataclass
class GraphPlan:
    """LangGraph 主计划。"""

    steps: List[GraphPlanStep]
    reason: str
    max_replans: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "steps": [step.to_dict() for step in self.steps],
            "reason": self.reason,
            "max_replans": self.max_replans,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphPlan":
        raw_steps = data.get("steps") if isinstance(data.get("steps"), list) else []
        steps = [
            GraphPlanStep.from_dict(item, idx)
            for idx, item in enumerate(raw_steps)
            if isinstance(item, dict)
        ]
        if not steps:
            raise ValueError("计划 steps 不能为空")
        reason = str(data.get("reason") or "未提供规划理由").strip() or "未提供规划理由"
        try:
            max_replans = max(0, int(data.get("max_replans", 1)))
        except Exception:
            max_replans = 1
        return cls(steps=steps, reason=reason, max_replans=max_replans)

    def sanitize_dependencies(self) -> None:
        """清理不存在的依赖，避免调度死锁。"""
        known_ids = {step.step_id for step in self.steps}
        for step in self.steps:
            step.depends_on = [dep for dep in step.depends_on if dep in known_ids and dep != step.step_id]
