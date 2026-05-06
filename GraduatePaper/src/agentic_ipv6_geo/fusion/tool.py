from __future__ import annotations

from itertools import combinations
from typing import Any

from agentic_ipv6_geo.common.geo import Point, clamp, haversine_km, weighted_mean_point
from agentic_ipv6_geo.common.models import Cost, GeoResult, Location


class FusionTool:
    name = "Fusion"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.tool_reliability = self.config.get("tool_reliability", {})
        self.conflict_penalty_km = float(self.config.get("conflict_penalty_km", 500.0))

    def run(self, results: list[GeoResult]) -> GeoResult:
        ok_results = [item for item in results if item.is_ok()]
        coord_results = [item for item in ok_results if item.location and item.location.has_coordinate]
        if not coord_results:
            return GeoResult(
                tool=self.name,
                status="unavailable",
                failure_reason="没有可融合的坐标级工具结果",
                evidence={"input_tools": [item.tool for item in results]},
            )

        weighted = []
        for result in coord_results:
            reliability = float(self.tool_reliability.get(result.tool, 0.5))
            weight = max(0.0, result.confidence * reliability)
            point = Point(result.location.lat, result.location.lon)  # type: ignore[arg-type]
            weighted.append((point, weight, result))

        point = weighted_mean_point((point, weight) for point, weight, _ in weighted)
        if not point:
            return GeoResult(tool=self.name, status="unavailable", failure_reason="融合权重总和为 0")

        conflicts = []
        for left, right in combinations(coord_results, 2):
            a = Point(left.location.lat, left.location.lon)  # type: ignore[arg-type]
            b = Point(right.location.lat, right.location.lon)  # type: ignore[arg-type]
            conflicts.append({"tools": [left.tool, right.tool], "distance_km": haversine_km(a, b)})

        max_conflict = max((item["distance_km"] for item in conflicts), default=0.0)
        base_confidence = sum(result.confidence for result in coord_results) / len(coord_results)
        penalty = min(0.45, max_conflict / self.conflict_penalty_km * 0.2)
        confidence = clamp(base_confidence - penalty + 0.04 * min(len(coord_results) - 1, 2))

        return GeoResult(
            tool=self.name,
            status="ok",
            location=Location(lat=point.lat, lon=point.lon),
            granularity="coordinate",
            confidence=confidence,
            cost=Cost(
                time_ms=sum(item.cost.time_ms for item in results),
                probe_count=sum(item.cost.probe_count for item in results),
                tool_calls=sum(item.cost.tool_calls for item in results),
            ),
            evidence={
                "used_tools": [result.tool for _, _, result in weighted],
                "conflicts": conflicts,
                "penalty": penalty,
                "context": [item.to_dict() for item in ok_results if item.tool == "WhoisBGP"],
            },
        )
