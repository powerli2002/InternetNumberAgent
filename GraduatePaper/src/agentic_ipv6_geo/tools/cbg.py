from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from agentic_ipv6_geo.common.geo import Point, clamp, haversine_km, weighted_mean_point
from agentic_ipv6_geo.common.models import Cost, GeoResult, Location, Target
from agentic_ipv6_geo.tools.base import BaseGeoTool


class CBGGeoTool(BaseGeoTool):
    """约束式主动定位工具。

    CBG 的核心假设是 RTT 给出目标到探针或地标的距离上界。MVP 中先用训练样本估计
    km/ms 上界，再保留满足约束较好的探针，以 1 / slack 加权求可行区域质心。
    约束少于 3 个时直接 unavailable，避免把测距不足硬凑成坐标。
    """

    name = "CBG"

    def __init__(self, repo, config: dict[str, Any] | None = None):
        super().__init__(repo, config)
        self.min_constraints = int(self.config.get("min_constraints", 3))
        self.default_km_per_ms = float(self.config.get("default_km_per_ms", 80.0))
        self.upper_bound_quantile = float(self.config.get("upper_bound_quantile", 0.9))
        self.km_per_ms = self.default_km_per_ms

    def fit(self, targets: list[Target]) -> None:
        target_by_ip = {target.ip: target for target in targets if target.location.has_coordinate}
        ratios = []
        for target in target_by_ip.values():
            for probe, rtt_ms in self._constraints(target):
                if rtt_ms and rtt_ms > 0:
                    distance = haversine_km(
                        Point(target.location.lat, target.location.lon),  # type: ignore[arg-type]
                        Point(probe.location.lat, probe.location.lon),  # type: ignore[arg-type]
                    )
                    ratios.append(distance / rtt_ms)
        if ratios:
            ratios.sort()
            index = min(len(ratios) - 1, int(len(ratios) * self.upper_bound_quantile))
            self.km_per_ms = max(ratios[index], 1.0)

    def _run(self, target: Target) -> GeoResult:
        constraints = self._constraints(target)
        if len(constraints) < self.min_constraints:
            return GeoResult(
                tool=self.name,
                status="unavailable",
                failure_reason=f"有效 RTT 约束少于 {self.min_constraints} 个",
                cost=Cost(probe_count=len(constraints)),
                evidence={"constraint_count": len(constraints)},
            )

        weighted = []
        evidence = []
        for probe, rtt_ms in constraints:
            radius = max(rtt_ms, 1.0) * self.km_per_ms
            probe_point = Point(probe.location.lat, probe.location.lon)  # type: ignore[arg-type]
            # 质心法无法直接求圆交集，因此用半径倒数作为粗粒度可行区域权重。
            weight = 1.0 / max(radius, 1.0)
            weighted.append((probe_point, weight))
            evidence.append({"probe_id": probe.probe_id, "rtt_ms": rtt_ms, "radius_km": radius})

        point = weighted_mean_point(weighted)
        if not point:
            return GeoResult(tool=self.name, status="unavailable", failure_reason="CBG 加权质心求解失败")

        radii = [item["radius_km"] for item in evidence]
        spread = statistics.median(radii) if radii else 9999.0
        confidence = clamp(0.75 - spread / 5000.0 + 0.04 * min(len(constraints), 5))
        return GeoResult(
            tool=self.name,
            status="ok",
            location=Location(lat=point.lat, lon=point.lon),
            granularity="coordinate",
            confidence=confidence,
            cost=Cost(probe_count=len(constraints)),
            evidence={"km_per_ms": self.km_per_ms, "constraints": evidence},
        )

    def _constraints(self, target: Target) -> list[tuple[Any, float]]:
        by_probe: dict[str, list] = defaultdict(list)
        for hop in self.repo.traces_for(target.ip):
            if hop.rtt_ms is not None:
                by_probe[hop.probe_id].append(hop)

        constraints = []
        for probe_id, hops in by_probe.items():
            probe = self.repo.probe_for(probe_id)
            if not probe or not probe.location.has_coordinate or not hops:
                continue
            target_hits = [hop.rtt_ms for hop in hops if hop.hop_ip == target.ip and hop.rtt_ms is not None]
            if target_hits:
                rtt_ms = min(target_hits)
            else:
                # CBG 需要目标方向的端到端 RTT；traceroute 未到达目标时，取最后可见跳 RTT
                # 作为保守替代，而不是取近端最小 RTT，避免把第一跳误当成目标距离。
                last_hop = max(hops, key=lambda item: item.hop_index)
                rtt_ms = last_hop.rtt_ms
            if rtt_ms is not None:
                constraints.append((probe, rtt_ms))
        return constraints
