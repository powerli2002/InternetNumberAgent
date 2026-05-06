from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Location:
    lat: float | None = None
    lon: float | None = None
    region: str | None = None
    city: str | None = None

    @property
    def has_coordinate(self) -> bool:
        return self.lat is not None and self.lon is not None


@dataclass(frozen=True)
class Cost:
    time_ms: float = 0.0
    probe_count: int = 0
    tool_calls: int = 1


@dataclass
class GeoResult:
    tool: str
    status: str
    location: Location | None = None
    granularity: str = "none"
    confidence: float = 0.0
    cost: Cost = field(default_factory=Cost)
    evidence: dict[str, Any] = field(default_factory=dict)
    failure_reason: str | None = None

    def is_ok(self) -> bool:
        return self.status == "ok" and self.location is not None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Target:
    ip: str
    location: Location
    asn: str | None = None
    operator: str | None = None
    observed_at: str | None = None


@dataclass(frozen=True)
class TraceHop:
    target_ip: str
    probe_id: str
    hop_ip: str
    hop_index: int
    rtt_ms: float | None = None
    measured_at: str | None = None


@dataclass(frozen=True)
class Probe:
    probe_id: str
    location: Location
    operator: str | None = None
    network_type: str | None = None


@dataclass(frozen=True)
class Metadata:
    prefix: str
    bgp_prefix: str | None = None
    asn: str | None = None
    org: str | None = None
    operator: str | None = None
    registered_region: str | None = None
    registered_city: str | None = None


@dataclass(frozen=True)
class RDnsRecord:
    ip: str
    hostname: str
    resolved_at: str | None = None


@dataclass(frozen=True)
class Landmark:
    ip: str
    location: Location
    rtt_ms: float | None = None


@dataclass(frozen=True)
class ExternalPrediction:
    ip: str
    location: Location
    confidence: float | None = None
    method: str | None = None
    pred_available: bool = True
