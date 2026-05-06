from __future__ import annotations

from typing import Any

from agentic_ipv6_geo.common.logger import JsonlLogger
from agentic_ipv6_geo.common.models import GeoResult, Target
from agentic_ipv6_geo.fusion import FusionTool
from agentic_ipv6_geo.tools import ActiveTriangulationTool, ModuGeoTool, PassiveIpDbGeoTool, RDnsGeoTool, WhoisBgpContextTool


class RuleAgentScheduler:
    """按成本从低到高调度工具。

    固定先调用 ModuGeo，再根据 rDNS 可用性和 ModuGeo 置信度决定是否调用额外工具。
    调度器只决定调用顺序和停机条件，定位证据仍来自可复现工具本身。
    """

    def __init__(
        self,
        modugeo: ModuGeoTool,
        rdns: RDnsGeoTool,
        active_triangulation: ActiveTriangulationTool,
        whois_bgp: WhoisBgpContextTool,
        passive_ipdb: PassiveIpDbGeoTool | None,
        fusion: FusionTool,
        config: dict[str, Any] | None = None,
        logger: JsonlLogger | None = None,
    ):
        self.modugeo = modugeo
        self.rdns = rdns
        self.active_triangulation = active_triangulation
        self.whois_bgp = whois_bgp
        self.passive_ipdb = passive_ipdb
        self.fusion = fusion
        self.config = config or {}
        self.logger = logger or JsonlLogger(None)
        self.modugeo_low_confidence = float(self.config.get("modugeo_low_confidence", 0.62))
        self.final_confidence_threshold = float(self.config.get("final_confidence_threshold", 0.55))

    def run(self, target: Target) -> GeoResult:
        results: list[GeoResult] = []
        decisions: list[dict[str, Any]] = []
        self.logger.log("scheduler_start", target_ip=target.ip)

        modugeo_result = self.modugeo.run(target)
        results.append(modugeo_result)
        decisions.append({"step": "ModuGeoTool", "action": "call", "reason": "核心定位器固定先调用", "status": modugeo_result.status})
        self.logger.log("tool_result", target_ip=target.ip, result=modugeo_result.to_dict())

        whois_result = self.whois_bgp.run(target)
        results.append(whois_result)
        decisions.append({"step": "WhoisBgpContextTool", "action": "call", "reason": "提供 ASN/组织/前缀上下文", "status": whois_result.status})
        self.logger.log("tool_result", target_ip=target.ip, result=whois_result.to_dict())

        rdns_record = self.rdns.repo.rdns_for(target.ip)
        if rdns_record:
            rdns_result = self.rdns.run(target)
            results.append(rdns_result)
            decisions.append({"step": "RDnsGeoTool", "action": "call", "reason": "目标存在 rDNS hostname", "status": rdns_result.status})
            self.logger.log("tool_result", target_ip=target.ip, result=rdns_result.to_dict())
        else:
            decisions.append({"step": "RDnsGeoTool", "action": "skip", "reason": "缺少目标 rDNS hostname", "status": "unavailable"})

        if self.passive_ipdb and self.passive_ipdb.enabled:
            passive_result = self.passive_ipdb.run(target)
            results.append(passive_result)
            decisions.append({"step": "PassiveIpDbGeoTool", "action": "call", "reason": "被动 IP 数据库已启用", "status": passive_result.status})
            self.logger.log("tool_result", target_ip=target.ip, result=passive_result.to_dict())
        else:
            decisions.append({"step": "PassiveIpDbGeoTool", "action": "skip", "reason": "被动 IP 数据库未启用", "status": "skipped"})

        should_call_active = modugeo_result.confidence < self.modugeo_low_confidence
        if should_call_active:
            active_result = self.active_triangulation.run(target)
            results.append(active_result)
            decisions.append(
                {
                    "step": "主动三角定位",
                    "action": "call",
                    "reason": f"ModuGeo 置信度 {modugeo_result.confidence:.3f} 低于阈值 {self.modugeo_low_confidence:.3f}",
                    "status": active_result.status,
                }
            )
            self.logger.log("tool_result", target_ip=target.ip, result=active_result.to_dict())
        else:
            decisions.append(
                {
                    "step": "主动三角定位",
                    "action": "skip",
                    "reason": f"ModuGeo 置信度 {modugeo_result.confidence:.3f} 已达到阈值 {self.modugeo_low_confidence:.3f}",
                    "status": "skipped",
                }
            )

        fused = self.fusion.run(results)
        fused.evidence["scheduler"] = {
            "type": "rule",
            "decisions": decisions,
            "candidate_results": [item.to_dict() for item in results],
        }
        self.logger.log("fusion_result", target_ip=target.ip, result=fused.to_dict())
        if fused.status == "ok" and fused.confidence >= self.final_confidence_threshold:
            self.logger.log("scheduler_stop", target_ip=target.ip, reason="confidence_threshold_reached")
            return fused

        if fused.status == "ok":
            fused.failure_reason = "融合置信度低于停机阈值"
            self.logger.log("scheduler_stop", target_ip=target.ip, reason="low_confidence")
            return fused

        best = self._best_available(results)
        best.evidence["scheduler"] = {
            "type": "rule",
            "decisions": decisions,
            "candidate_results": [item.to_dict() for item in results],
            "fallback_reason": "FusionTool 不可用，返回最高置信可用工具",
        }
        self.logger.log("scheduler_stop", target_ip=target.ip, reason="fusion_unavailable", fallback=best.to_dict())
        return best

    @staticmethod
    def _best_available(results: list[GeoResult]) -> GeoResult:
        ok = [item for item in results if item.is_ok()]
        if not ok:
            return GeoResult(tool="RuleAgentScheduler", status="unavailable", failure_reason="所有定位工具均不可用")
        return max(ok, key=lambda item: item.confidence)
