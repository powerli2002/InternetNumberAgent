from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from agentic_ipv6_geo.common.geo import Point, clamp
from agentic_ipv6_geo.common.models import Cost, GeoResult, Location, Target
from agentic_ipv6_geo.providers import RipeAtlasProvider, ScamperTraceProvider
from agentic_ipv6_geo.tools.base import BaseGeoTool


class ActiveTriangulationTool(BaseGeoTool):
    """基于 cbgtool 的主动三角定位工具。

    默认启用 CBG 约束圆交集方法。NCR 与 NCR-CBG 属于同一类主动三角定位
    的备选实验方法，可通过配置切换，但不会进入默认调度策略。
    """

    name = "ActiveTriangulation"
    CBG_ALIASES = {"cbg", "ori", "original"}
    NCR_ALIASES = {"ncr", "ncrgeo", "ncr_geo"}
    NCR_CBG_ALIASES = {"ncr-cbg", "ncr_cbg", "ncrcbg", "cbgncr", "ncr_ori"}

    def __init__(self, repo, config: dict[str, Any] | None = None):
        super().__init__(repo, config)
        self.algorithm = str(self.config.get("algorithm", "cbg")).lower()
        self.min_constraints = int(self.config.get("min_constraints", 3))
        self.delta = float(self.config.get("delta", 0.398))
        self.sort_circles = int(self.config.get("sort_circles", 0))
        self.cbgtool_root = Path(self.config.get("cbgtool_root", "ipgeotools/cbgtool"))
        self.active_probe_config = self.config.get("active_probe", {})
        self._constraint_evidence_by_probe: dict[str, dict[str, Any]] = {}

    def fit(self, targets: list[Target]) -> None:
        # CBG 方法不需要监督训练；保留 fit 接口，便于注册系统统一调用。
        _ = targets

    def _run(self, target: Target) -> GeoResult:
        helpers = self._load_cbg_helpers()
        if helpers is None:
            return GeoResult(
                tool=self.name,
                status="unavailable",
                failure_reason="无法导入 cbgtool 的圆交集工具函数",
                evidence={"cbgtool_root": str(self.cbgtool_root)},
            )

        constraints = self._constraints(target)
        if len(constraints) < self.min_constraints:
            return GeoResult(
                tool=self.name,
                status="unavailable",
                failure_reason=f"有效主动测距约束少于 {self.min_constraints} 个",
                cost=Cost(probe_count=len(constraints)),
                evidence={"constraint_count": len(constraints), "algorithm": self.algorithm},
            )

        if self.algorithm in self.CBG_ALIASES:
            return self._run_cbg(target, constraints, helpers, ncr_delta=None, algorithm="cbg")
        if self.algorithm in self.NCR_ALIASES:
            return self._run_ncr(target, constraints, helpers)
        if self.algorithm in self.NCR_CBG_ALIASES:
            return self._run_ncr_cbg(target, constraints, helpers)

        return GeoResult(
            tool=self.name,
            status="unavailable",
            failure_reason=f"未知主动三角定位算法：{self.algorithm}",
            cost=Cost(probe_count=len(constraints)),
            evidence={"algorithm": self.algorithm},
        )

    def _run_cbg(
        self,
        target: Target,
        constraints: list[tuple[Any, float]],
        helpers: dict[str, Any],
        ncr_delta: float | None,
        algorithm: str,
    ) -> GeoResult:
        vp_coordinates = {}
        rtts = {}
        evidence_constraints = self._constraint_evidence(constraints, ncr_delta or self.delta)
        for probe, rtt_ms in constraints:
            vp_coordinates[probe.probe_id] = (probe.location.lon, probe.location.lat)
            rtts[probe.probe_id] = float(rtt_ms)

        try:
            guessed = helpers["select_best_guess_centroid"](
                target.ip,
                vp_coordinates,
                rtts,
                sort_circles=self.sort_circles,
                ncr_delta=ncr_delta or self.delta,
            )
        except Exception as exc:
            return GeoResult(
                tool=self.name,
                status="unavailable",
                failure_reason=f"cbgtool {algorithm} 求解失败: {exc}",
                cost=Cost(probe_count=len(constraints)),
                evidence={"algorithm": algorithm, "constraints": evidence_constraints},
            )

        if guessed is None:
            return GeoResult(
                tool=self.name,
                status="unavailable",
                failure_reason=f"{algorithm} 约束圆无可用交集或质心",
                cost=Cost(probe_count=len(constraints)),
                evidence={"algorithm": algorithm, "constraints": evidence_constraints},
            )

        centroid, circles = guessed
        lon, lat = centroid
        median_radius = sorted(item["radius_km"] for item in evidence_constraints)[len(evidence_constraints) // 2]
        confidence = clamp(0.35 + 0.06 * min(len(constraints), 5) - median_radius / 6000.0)
        return GeoResult(
            tool=self.name,
            status="ok",
            location=Location(lat=float(lat), lon=float(lon)),
            granularity="coordinate",
            confidence=confidence,
            cost=Cost(probe_count=len(constraints)),
            evidence={
                "algorithm": algorithm,
                "source": helpers.get("source", "GraduatePaper/ipgeotools/cbgtool/scripts/utils/helpers.py"),
                "constraints": evidence_constraints,
                "circle_count": len(circles),
                "delta": ncr_delta or self.delta,
                "sort_circles": self.sort_circles,
            },
        )

    def _run_ncr(self, target: Target, constraints: list[tuple[Any, float]], helpers: dict[str, Any]) -> GeoResult:
        ncr_result = self._compute_ncr(target, constraints, helpers)
        if ncr_result["status"] != "ok":
            return GeoResult(
                tool=self.name,
                status="unavailable",
                failure_reason=ncr_result["failure_reason"],
                cost=Cost(probe_count=len(constraints)),
                evidence=ncr_result["evidence"],
            )
        lon, lat = ncr_result["location"]
        confidence = clamp(0.38 + 0.05 * min(len(constraints), 5) - 0.015 * ncr_result["iter_times"])
        return GeoResult(
            tool=self.name,
            status="ok",
            location=Location(lat=float(lat), lon=float(lon)),
            granularity="coordinate",
            confidence=confidence,
            cost=Cost(probe_count=len(constraints)),
            evidence=ncr_result["evidence"],
        )

    def _run_ncr_cbg(self, target: Target, constraints: list[tuple[Any, float]], helpers: dict[str, Any]) -> GeoResult:
        ncr_result = self._compute_ncr(target, constraints, helpers)
        if ncr_result["status"] != "ok":
            fallback = self._run_cbg(target, constraints, helpers, ncr_delta=None, algorithm="ncr-cbg-fallback-cbg")
            fallback.evidence["ncr_failure_reason"] = ncr_result["failure_reason"]
            return fallback

        # cbgtool 原实现将 NCR 求得的距离-时延系数换算为 CBG 圆半径系数。
        ncr_delta_for_cbg = ncr_result["delta"] / 300
        if ncr_result["iter_times"] <= 0 or ncr_result["iter_times"] >= 3:
            fallback = self._run_cbg(target, constraints, helpers, ncr_delta=None, algorithm="ncr-cbg-fallback-cbg")
            fallback.evidence["ncr_delta"] = ncr_result["delta"]
            fallback.evidence["ncr_iter_times"] = ncr_result["iter_times"]
            return fallback

        result = self._run_cbg(target, constraints, helpers, ncr_delta=ncr_delta_for_cbg, algorithm="ncr-cbg")
        result.evidence["ncr_delta"] = ncr_result["delta"]
        result.evidence["ncr_delta_for_cbg"] = ncr_delta_for_cbg
        result.evidence["ncr_iter_times"] = ncr_result["iter_times"]
        return result

    def _compute_ncr(self, target: Target, constraints: list[tuple[Any, float]], helpers: dict[str, Any]) -> dict[str, Any]:
        vp_coordinates = {}
        rtts = {}
        for probe, rtt_ms in constraints:
            vp_coordinates[probe.probe_id] = (probe.location.lon, probe.location.lat)
            rtts[probe.probe_id] = float(rtt_ms)

        compute_by_ncrgeo = helpers.get("compute_by_NCRGeo")
        if compute_by_ncrgeo is None:
            import_error = helpers.get("ncr_import_error")
            return {
                "status": "unavailable",
                "failure_reason": f"无法导入 cbgtool 的 NCRGeo 计算函数；如需使用 NCR/NCR-CBG，请安装 active 依赖：{import_error}",
                "evidence": {
                    "algorithm": self.algorithm,
                    "source": "GraduatePaper/ipgeotools/cbgtool/scripts/analysis/analysis.py",
                    "import_error": str(import_error),
                },
            }
        try:
            result, iter_times = compute_by_ncrgeo(target.ip, vp_coordinates, rtts)
        except Exception as exc:
            return {
                "status": "unavailable",
                "failure_reason": f"cbgtool NCRGeo 求解失败: {exc}",
                "evidence": {"algorithm": self.algorithm, "constraints": self._constraint_evidence(constraints, self.delta)},
            }

        guessed = result[2] if result and len(result) > 2 else None
        delta = result[4] if result and len(result) > 4 else None
        if guessed is None or delta is None:
            return {
                "status": "unavailable",
                "failure_reason": "NCRGeo 未找到满足三角约束的位置",
                "evidence": {
                    "algorithm": self.algorithm,
                    "iter_times": iter_times,
                    "constraints": self._constraint_evidence(constraints, self.delta),
                },
            }
        return {
            "status": "ok",
            "location": guessed,
            "delta": float(delta),
            "iter_times": int(iter_times),
            "evidence": {
                "algorithm": "ncr" if self.algorithm in self.NCR_ALIASES else "ncr-cbg",
                "source": "GraduatePaper/ipgeotools/cbgtool/scripts/analysis/analysis.py",
                "constraints": self._constraint_evidence(constraints, self.delta),
                "ncr_delta": float(delta),
                "ncr_iter_times": int(iter_times),
            },
        }

    def _constraint_evidence(self, constraints: list[tuple[Any, float]], delta: float) -> list[dict[str, Any]]:
        rows = []
        for probe, rtt_ms in constraints:
            extra = self._constraint_evidence_by_probe.get(probe.probe_id, {})
            rows.append(
                {
                    "probe_id": probe.probe_id,
                    "lat": probe.location.lat,
                    "lon": probe.location.lon,
                    "rtt_ms": float(rtt_ms),
                    "radius_km": delta * float(rtt_ms) * 300 / 2,
                    "source": extra.get("source", "existing_trace"),
                    "evidence": extra.get("evidence", {}),
                }
            )
        return rows

    def _constraints(self, target: Target) -> list[tuple[Any, float]]:
        self._constraint_evidence_by_probe = {}
        grouped: dict[str, list] = {}
        for hop in self.repo.traces_for(target.ip):
            if hop.rtt_ms is not None:
                grouped.setdefault(hop.probe_id, []).append(hop)

        constraints = []
        for probe_id, hops in grouped.items():
            probe = self.repo.probe_for(probe_id)
            if not probe or not probe.location.has_coordinate:
                continue
            target_hits = [hop.rtt_ms for hop in hops if hop.hop_ip == target.ip and hop.rtt_ms is not None]
            if target_hits:
                rtt_ms = min(target_hits)
            else:
                # traceroute 未到达目标时，用该探针最后可见 hop 的 RTT 作为保守主动测距证据。
                rtt_ms = max(hops, key=lambda item: item.hop_index).rtt_ms
            if rtt_ms is not None and rtt_ms > 0:
                constraints.append((probe, float(rtt_ms)))
                self._constraint_evidence_by_probe[probe.probe_id] = {
                    "source": "existing_trace_target_hit" if target_hits else "existing_trace_last_visible_hop",
                    "evidence": {"target_ip": target.ip},
                }
        if len(constraints) < self.min_constraints:
            constraints.extend(self._collect_active_constraints(target, constraints))
        return constraints

    def _collect_active_constraints(self, target: Target, existing: list[tuple[Any, float]]) -> list[tuple[Any, float]]:
        if not self.active_probe_config:
            return []
        existing_probe_ids = {probe.probe_id for probe, _rtt in existing}
        provider_order = self.active_probe_config.get("provider_order", ["existing_trace", "scamper", "ripe_atlas"])
        collected: list[tuple[Any, float]] = []
        provider_config = {
            "active_probe": self.active_probe_config,
            "scamper": self.config.get("scamper", {}),
            "ripe_atlas": self.config.get("ripe_atlas", {}),
            "external_services": self.config.get("external_services", {}),
        }
        providers = {
            "scamper": ScamperTraceProvider(provider_config),
            "ripe_atlas": RipeAtlasProvider(provider_config),
        }
        for provider_name in provider_order:
            provider = providers.get(provider_name)
            if provider is None:
                continue
            result = provider.collect(target.ip, self.repo)
            self._constraint_evidence_by_probe[f"provider:{provider_name}"] = {
                "source": provider_name,
                "evidence": result.evidence if result.evidence else {"failure_reason": result.failure_reason},
            }
            if not result.is_ok():
                continue
            for item in result.constraints:
                if item.probe.probe_id in existing_probe_ids:
                    continue
                collected.append((item.probe, item.rtt_ms))
                existing_probe_ids.add(item.probe.probe_id)
                self._constraint_evidence_by_probe[item.probe.probe_id] = {
                    "source": item.source,
                    "evidence": item.evidence,
                }
                if len(existing) + len(collected) >= self.min_constraints:
                    return collected
        return collected

    def _load_cbg_helpers(self) -> dict[str, Any] | None:
        root = self.cbgtool_root.resolve()
        if not root.exists():
            return {"select_best_guess_centroid": self._select_best_guess_centroid_fallback, "source": "internal_cbg_fallback"}
        for path in (root, root / "scripts" / "utils"):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
        try:
            from scripts.utils.helpers import select_best_guess_centroid
        except Exception:
            return {"select_best_guess_centroid": self._select_best_guess_centroid_fallback, "source": "internal_cbg_fallback"}
        helpers = {"select_best_guess_centroid": select_best_guess_centroid, "source": "GraduatePaper/ipgeotools/cbgtool/scripts/utils/helpers.py"}
        try:
            from scripts.analysis.analysis import compute_by_NCRGeo
            ncr_import_error = None
        except Exception as exc:
            compute_by_NCRGeo = None
            ncr_import_error = exc
        helpers["compute_by_NCRGeo"] = compute_by_NCRGeo
        helpers["ncr_import_error"] = ncr_import_error
        return helpers

    @staticmethod
    def _select_best_guess_centroid_fallback(
        ip_address: str,
        vp_coordinates: dict[str, tuple[float, float]],
        rtts: dict[str, float],
        sort_circles: int = 0,
        ncr_delta: float = 0.398,
    ):
        # 当外部 cbgtool 不在仓库快照中时，使用 RTT 反比加权质心保持实验闭环可运行。
        _ = ip_address, sort_circles
        weighted = []
        circles = []
        for probe_id, (lon, lat) in vp_coordinates.items():
            rtt_ms = float(rtts.get(probe_id, 0.0))
            if rtt_ms <= 0:
                continue
            radius_km = ncr_delta * rtt_ms * 300 / 2
            weight = 1.0 / max(radius_km, 1.0)
            weighted.append((lon, lat, weight))
            circles.append({"probe_id": probe_id, "radius_km": radius_km})
        total = sum(item[2] for item in weighted)
        if total <= 0:
            return None
        lon = sum(item[0] * item[2] for item in weighted) / total
        lat = sum(item[1] * item[2] for item in weighted) / total
        return (lon, lat), circles
