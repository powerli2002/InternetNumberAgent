from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agentic_ipv6_geo.common.models import GeoResult, Location


ALLOWED_ACTIONS = {
    "inspect_tool_applicability",
    "query_tool",
    "query_rdns",
    "run_active_solver",
    "query_passive_evidence",
    "inspect_result_quality",
    "compare_candidates",
    "finalize",
    "abstain",
}

TOOL_ALIASES = {
    "query_rdns": "rdns",
    "run_active_solver": "active_triangulation",
    "query_passive_evidence": "passive_ipdb",
}


@dataclass(frozen=True)
class CandidateLocation:
    candidate_id: str
    source_tool: str
    location: Location
    granularity: str
    confidence: float

    @property
    def has_coordinate(self) -> bool:
        return self.location.has_coordinate

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CandidateLocation":
        return cls(
            candidate_id=str(payload["candidate_id"]),
            source_tool=str(payload["source_tool"]),
            location=Location(**payload["location"]),
            granularity=str(payload["granularity"]),
            confidence=float(payload["confidence"]),
        )


@dataclass(frozen=True)
class ToolObservation:
    tool_id: str
    status: str
    applicability: str
    failure_type: str | None
    failure_reason: str | None
    candidate: CandidateLocation | None
    quality: dict[str, Any] = field(default_factory=dict)
    cost: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ToolObservation":
        candidate = CandidateLocation.from_dict(payload["candidate"]) if payload.get("candidate") else None
        return cls(
            tool_id=str(payload["tool_id"]),
            status=str(payload["status"]),
            applicability=str(payload["applicability"]),
            failure_type=payload.get("failure_type"),
            failure_reason=payload.get("failure_reason"),
            candidate=candidate,
            quality=dict(payload.get("quality") or {}),
            cost=dict(payload.get("cost") or {}),
            evidence=dict(payload.get("evidence") or {}),
        )

    @classmethod
    def from_geo_result(cls, task_id: str, tool_id: str, result: GeoResult) -> "ToolObservation":
        candidate = None
        if result.is_ok() and result.location is not None:
            candidate = CandidateLocation(
                candidate_id=f"{task_id}:{tool_id}",
                source_tool=tool_id,
                location=result.location,
                granularity=result.granularity,
                confidence=result.confidence,
            )
        quality = {
            "confidence": result.confidence,
            "granularity": result.granularity,
            **_quality_features(result),
        }
        failure_type = classify_failure(result)
        applicability = "applicable" if result.status == "ok" else "not_applicable"
        if result.status == "ok" and result.confidence < 0.45:
            applicability = "conditional"
        return cls(
            tool_id=tool_id,
            status=result.status,
            applicability=applicability,
            failure_type=failure_type,
            failure_reason=result.failure_reason,
            candidate=candidate,
            quality=quality,
            cost=asdict(result.cost),
            evidence=result.evidence,
        )


@dataclass(frozen=True)
class AgentAction:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.name not in ALLOWED_ACTIONS:
            raise ValueError(f"非法 Agent 动作：{self.name}")
        if not isinstance(self.arguments, dict):
            raise ValueError("Agent 动作 arguments 必须是对象")

    def tool_id(self) -> str | None:
        if self.name in TOOL_ALIASES:
            return TOOL_ALIASES[self.name]
        if self.name in {"query_tool", "inspect_tool_applicability", "inspect_result_quality"}:
            tool_id = self.arguments.get("tool")
            return str(tool_id) if tool_id else None
        return None


@dataclass(frozen=True)
class PrivateTruth:
    task_id: str
    location: Location

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "truth": asdict(self.location)}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PrivateTruth":
        return cls(task_id=str(payload["task_id"]), location=Location(**payload["truth"]))


@dataclass(frozen=True)
class RewardBreakdown:
    total: float
    geo: float = 0.0
    improve: float = 0.0
    applicability: float = 0.0
    cost_penalty: float = 0.0
    invalid_penalty: float = 0.0
    unsupported_penalty: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_failure(result: GeoResult) -> str | None:
    if result.status == "ok":
        return None
    text = (result.failure_reason or "").lower()
    if any(token in text for token in ("文件不存在", "未配置", "缺少 maxminddb", "无法导入")):
        return "input_missing"
    if any(token in text for token in ("未命中", "缺少目标 ip", "no ptr", "没有记录")):
        return "coverage_miss"
    if any(token in text for token in ("约束少于", "无可用交集", "算法", "未找到满足")):
        return "assumption_violation"
    if any(token in text for token in ("低质量", "不可靠")):
        return "low_quality"
    return "unavailable"


def _quality_features(result: GeoResult) -> dict[str, Any]:
    evidence = result.evidence
    constraints = evidence.get("constraints")
    rows: dict[str, Any] = {}
    if isinstance(constraints, list):
        rows["constraint_count"] = len(constraints)
        radii = [item.get("radius_km") for item in constraints if isinstance(item, dict) and item.get("radius_km") is not None]
        if radii:
            rows["median_radius_km"] = sorted(float(value) for value in radii)[len(radii) // 2]
    if evidence.get("circle_count") is not None:
        rows["circle_count"] = evidence["circle_count"]
    if evidence.get("algorithm") is not None:
        rows["algorithm"] = evidence["algorithm"]
    if evidence.get("hostname") is not None:
        rows["hostname_available"] = True
    if evidence.get("failures") is not None:
        rows["source_failure_count"] = len(evidence["failures"])
    return rows
