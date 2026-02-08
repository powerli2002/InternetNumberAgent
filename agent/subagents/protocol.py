"""
子代理协议定义模块

提供 TaskEnvelope / ResultEnvelope / RouterDecision 等协议结构，
用于 Supervisor 与子代理之间的稳定编排与校验。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


_ALLOWED_AGENT_NAMES = {"sql_facts", "rag_docs", "graph_relations", "verifier"}


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


def _ensure_list(value: Any, field_name: str) -> List[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"字段 {field_name} 必须为数组")
    return value


@dataclass
class TaskEnvelope:
    """主代理发给子代理的任务信封。"""

    objective: str
    constraints: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    expected_output: str = "结构化结果 + 证据摘要"
    budget: Dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    task_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective": self.objective,
            "constraints": self.constraints,
            "context": self.context,
            "expected_output": self.expected_output,
            "budget": self.budget,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskEnvelope":
        return cls(
            objective=_ensure_str(data.get("objective"), "objective"),
            constraints=_ensure_dict(data.get("constraints"), "constraints"),
            context=_ensure_dict(data.get("context"), "context"),
            expected_output=data.get("expected_output") or "结构化结果 + 证据摘要",
            budget=_ensure_dict(data.get("budget"), "budget"),
            trace_id=data.get("trace_id") or "",
            task_id=data.get("task_id"),
        )


@dataclass
class PlanStep:
    """路由计划中的单步动作。"""

    agent: str
    objective: str
    constraints: Dict[str, Any] = field(default_factory=dict)
    expected_output: str = "结构化结果 + 证据摘要"
    budget: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "objective": self.objective,
            "constraints": self.constraints,
            "expected_output": self.expected_output,
            "budget": self.budget,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanStep":
        agent = _ensure_str(data.get("agent"), "agent")
        if agent not in _ALLOWED_AGENT_NAMES:
            raise ValueError(f"未知子代理: {agent}")
        return cls(
            agent=agent,
            objective=_ensure_str(data.get("objective"), "objective"),
            constraints=_ensure_dict(data.get("constraints"), "constraints"),
            expected_output=data.get("expected_output") or "结构化结果 + 证据摘要",
            budget=_ensure_dict(data.get("budget"), "budget"),
        )


@dataclass
class RouterDecision:
    """Supervisor 输出的路由决策。"""

    plan: List[PlanStep]
    reason: str
    max_turns: int = 4

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan": [step.to_dict() for step in self.plan],
            "reason": self.reason,
            "max_turns": self.max_turns,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RouterDecision":
        plan_data = _ensure_list(data.get("plan"), "plan")
        plan = [PlanStep.from_dict(item) for item in plan_data]
        if not plan:
            raise ValueError("RouterDecision.plan 不能为空")
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


@dataclass
class ResultEvidence:
    """子代理返回的证据条目。"""

    source: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "content": self.content, "metadata": self.metadata}


@dataclass
class ResultEnvelope:
    """子代理返回的结果信封。"""

    status: str
    result: Dict[str, Any] = field(default_factory=dict)
    evidence: List[ResultEvidence] = field(default_factory=list)
    next_actions: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    agent: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "result": self.result,
            "evidence": [item.to_dict() for item in self.evidence],
            "next_actions": self.next_actions,
            "errors": self.errors,
            "metrics": self.metrics,
            "trace_id": self.trace_id,
            "agent": self.agent,
        }

    @classmethod
    def ok(
        cls,
        agent: str,
        result: Dict[str, Any],
        evidence: Optional[List[ResultEvidence]] = None,
        trace_id: str = "",
        metrics: Optional[Dict[str, Any]] = None,
    ) -> "ResultEnvelope":
        return cls(
            status="ok",
            result=result,
            evidence=evidence or [],
            metrics=metrics or {},
            trace_id=trace_id,
            agent=agent,
        )

    @classmethod
    def error(cls, agent: str, error: str, trace_id: str = "") -> "ResultEnvelope":
        return cls(status="error", errors=[error], trace_id=trace_id, agent=agent)


def allowed_agent_names() -> List[str]:
    """返回允许的子代理名称列表。"""
    return sorted(_ALLOWED_AGENT_NAMES)
