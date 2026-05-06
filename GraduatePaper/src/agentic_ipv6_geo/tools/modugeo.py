from __future__ import annotations

import ipaddress
import math
from collections import defaultdict
from typing import Any

from agentic_ipv6_geo.common.geo import Point, clamp, haversine_km, mean_point, weighted_mean_point
from agentic_ipv6_geo.common.models import Cost, GeoResult, Location, Target
from agentic_ipv6_geo.tools.base import BaseGeoTool


class ModuGeoTool(BaseGeoTool):
    """ModuGeo 的可复现实验封装。

    真实 ModuGeo 是多尺度前缀、语义属性、last-hop/RTT 条件调制的学习模型。
    本工具保留同样的输入边界和证据组织方式：先用训练集构建多尺度前缀先验，
    再融合 ASN/运营商语义质心与 last-hop 地标残差信号。若后续已有深度模型预测，
    可以在同一输出协议下替换 `_run` 内部实现，而不影响调度和评测。
    """

    name = "ModuGeo"

    def __init__(self, repo, config: dict[str, Any] | None = None):
        super().__init__(repo, config)
        self.prefix_lengths = list(self.config.get("prefix_lengths", [64, 56, 48, 40, 32]))
        self.min_prefix_samples = int(self.config.get("min_prefix_samples", 1))
        self.semantic_weight = float(self.config.get("semantic_weight", 0.25))
        self.landmark_weight = float(self.config.get("landmark_weight", 0.25))
        self.use_external_predictions = bool(self.config.get("use_external_predictions", True))
        self.default_external_confidence = float(self.config.get("default_external_confidence", 0.72))
        self._prefix_points: dict[tuple[int, str], list[Point]] = defaultdict(list)
        self._asn_points: dict[str, list[Point]] = defaultdict(list)
        self._operator_points: dict[str, list[Point]] = defaultdict(list)
        self._fitted = False

    def fit(self, targets: list[Target]) -> None:
        self._prefix_points.clear()
        self._asn_points.clear()
        self._operator_points.clear()
        for target in targets:
            if not target.location.has_coordinate:
                continue
            point = Point(target.location.lat, target.location.lon)  # type: ignore[arg-type]
            for length in self.prefix_lengths:
                key = self._prefix_key(target.ip, length)
                self._prefix_points[(length, key)].append(point)
            if target.asn:
                self._asn_points[target.asn].append(point)
            if target.operator:
                self._operator_points[target.operator].append(point)
        self._fitted = True

    def _run(self, target: Target) -> GeoResult:
        if self.use_external_predictions:
            external = self.repo.modugeo_prediction_for(target.ip)
            if external and external.location.has_coordinate:
                return GeoResult(
                    tool=self.name,
                    status="ok",
                    location=external.location,
                    granularity="coordinate",
                    confidence=clamp(external.confidence if external.confidence is not None else self.default_external_confidence),
                    evidence={
                        "source": "external_prediction",
                        "method": external.method or "TrustGeo prediction",
                        "note": "复用 TrustGeo 已有核心模型预测；置信度不使用真实误差反推，避免评测泄漏",
                    },
                )

        if not self._fitted:
            return GeoResult(tool=self.name, status="unavailable", failure_reason="ModuGeoTool 尚未 fit 训练目标")

        candidates: list[tuple[Point, float, str]] = []
        prefix_evidence = None
        for length in self.prefix_lengths:
            points = self._prefix_points.get((length, self._prefix_key(target.ip, length)), [])
            if len(points) >= self.min_prefix_samples:
                point = mean_point(points)
                if point:
                    weight = 0.45 + 0.45 * (length / 64.0) + 0.05 * math.log1p(len(points))
                    candidates.append((point, weight, f"/{length} 前缀样本 {len(points)} 个"))
                    prefix_evidence = {"prefix_length": length, "sample_count": len(points)}
                    break

        if target.asn and target.asn in self._asn_points:
            point = mean_point(self._asn_points[target.asn])
            if point:
                candidates.append((point, self.semantic_weight, f"ASN {target.asn} 语义质心"))

        if target.operator and target.operator in self._operator_points:
            point = mean_point(self._operator_points[target.operator])
            if point:
                candidates.append((point, self.semantic_weight, f"运营商 {target.operator} 语义质心"))

        landmark_point, landmark_reason, probe_count = self._last_hop_landmark_signal(target)
        if landmark_point:
            candidates.append((landmark_point, self.landmark_weight, landmark_reason))

        point = weighted_mean_point((candidate, weight) for candidate, weight, _ in candidates)
        if not point:
            return GeoResult(
                tool=self.name,
                status="unavailable",
                failure_reason="缺少可用前缀、语义或 last-hop 地标证据",
            )

        main_weight = max((weight for _, weight, _ in candidates), default=0.0)
        confidence = clamp(0.35 + 0.35 * main_weight + 0.08 * len(candidates))
        return GeoResult(
            tool=self.name,
            status="ok",
            location=Location(lat=point.lat, lon=point.lon, region=None, city=None),
            granularity="coordinate",
            confidence=confidence,
            cost=Cost(probe_count=probe_count),
            evidence={
                "prefix": prefix_evidence,
                "signals": [reason for _, _, reason in candidates],
            },
        )

    def _last_hop_landmark_signal(self, target: Target) -> tuple[Point | None, str, int]:
        by_probe: dict[str, list] = defaultdict(list)
        for hop in self.repo.traces_for(target.ip):
            by_probe[hop.probe_id].append(hop)
        points = []
        for hops in by_probe.values():
            hops.sort(key=lambda item: item.hop_index)
            last = hops[-1]
            landmark = self.repo.landmark_for(last.hop_ip)
            if landmark and landmark.location.has_coordinate:
                points.append(Point(landmark.location.lat, landmark.location.lon))  # type: ignore[arg-type]
        point = mean_point(points)
        return point, f"last-hop 地标 {len(points)} 个", len(points)

    @staticmethod
    def _prefix_key(ip: str, length: int) -> str:
        network = ipaddress.ip_network(f"{ip}/{length}", strict=False)
        return str(network.network_address)


def estimate_confidence_from_training_error(predicted: Point, neighbors: list[Point]) -> float:
    if not neighbors:
        return 0.0
    errors = [haversine_km(predicted, neighbor) for neighbor in neighbors]
    median = sorted(errors)[len(errors) // 2]
    return clamp(1.0 - median / 1000.0)
