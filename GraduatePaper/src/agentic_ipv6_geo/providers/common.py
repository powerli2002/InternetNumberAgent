from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentic_ipv6_geo.common.models import Probe


@dataclass(frozen=True)
class ProbeConstraint:
    probe: Probe
    rtt_ms: float
    source: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProbeCollectionResult:
    status: str
    constraints: list[ProbeConstraint] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    failure_reason: str | None = None

    def is_ok(self) -> bool:
        return self.status == "ok" and bool(self.constraints)
