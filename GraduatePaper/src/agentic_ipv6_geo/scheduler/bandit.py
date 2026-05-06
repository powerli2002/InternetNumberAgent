from __future__ import annotations

from collections import defaultdict
from typing import Any

from agentic_ipv6_geo.common.geo import Point, haversine_km
from agentic_ipv6_geo.common.logger import JsonlLogger
from agentic_ipv6_geo.common.models import GeoResult, Target
from agentic_ipv6_geo.fusion import FusionTool
from agentic_ipv6_geo.tools import ActiveTriangulationTool, ModuGeoTool, RDnsGeoTool, WhoisBgpContextTool


class ContextualBanditScheduler:
    """离线上下文 bandit 调度器。

    训练阶段在训练集上模拟 stop、rdns、active、all 四类动作，按误差和调用成本计算奖励；
    推断阶段只根据当前样本可观测上下文选动作，不读取真实位置。
    """

    ACTIONS = ("stop", "rdns", "active", "all")

    def __init__(
        self,
        modugeo: ModuGeoTool,
        rdns: RDnsGeoTool,
        active_triangulation: ActiveTriangulationTool,
        whois_bgp: WhoisBgpContextTool,
        fusion: FusionTool,
        config: dict[str, Any] | None = None,
        logger: JsonlLogger | None = None,
    ):
        self.modugeo = modugeo
        self.rdns = rdns
        self.active_triangulation = active_triangulation
        self.whois_bgp = whois_bgp
        self.fusion = fusion
        self.config = config or {}
        self.logger = logger or JsonlLogger(None)
        self.tool_cost_weight = float(self.config.get("tool_cost_weight", 10.0))
        self.probe_cost_weight = float(self.config.get("probe_cost_weight", 2.0))
        self.min_samples_per_context = int(self.config.get("min_samples_per_context", 2))
        self.policy: dict[tuple, str] = {}
        self.global_action = "stop"

    def fit(self, targets: list[Target]) -> None:
        rewards: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        global_rewards: dict[str, list[float]] = defaultdict(list)
        for target in targets:
            base = self.modugeo.run(target)
            context = self._context(target, base)
            for action in self.ACTIONS:
                result = self._run_action(target, base, action)
                reward = self._reward(target, result)
                rewards[context][action].append(reward)
                global_rewards[action].append(reward)

        for context, action_rewards in rewards.items():
            candidates = {
                action: sum(values) / len(values)
                for action, values in action_rewards.items()
                if len(values) >= self.min_samples_per_context
            }
            if candidates:
                self.policy[context] = max(candidates, key=candidates.get)

        global_avg = {action: sum(values) / len(values) for action, values in global_rewards.items() if values}
        if global_avg:
            self.global_action = max(global_avg, key=global_avg.get)

    def run(self, target: Target) -> GeoResult:
        base = self.modugeo.run(target)
        context = self._context(target, base)
        action = self.policy.get(context, self.global_action)
        self.logger.log("bandit_action", target_ip=target.ip, context=list(context), action=action)
        result = self._run_action(target, base, action)
        result.evidence["scheduler"] = {
            "type": "contextual_bandit",
            "context": list(context),
            "selected_action": action,
            "global_action": self.global_action,
            "known_context_count": len(self.policy),
        }
        return result

    def _run_action(self, target: Target, base: GeoResult, action: str) -> GeoResult:
        results = [base, self.whois_bgp.run(target)]
        if action in {"rdns", "all"}:
            results.append(self.rdns.run(target))
        if action in {"active", "all"}:
            results.append(self.active_triangulation.run(target))
        if action == "stop":
            fused = self.fusion.run(results)
            return fused if fused.status == "ok" else base
        return self.fusion.run(results)

    def _context(self, target: Target, base: GeoResult) -> tuple:
        confidence_bucket = "high" if base.confidence >= 0.7 else ("mid" if base.confidence >= 0.45 else "low")
        rdns_available = self.rdns.repo.rdns_for(target.ip) is not None
        active_constraints = len(self.active_triangulation._constraints(target))
        cbg_bucket = "active3" if active_constraints >= self.active_triangulation.min_constraints else "active_lt3"
        operator = (target.operator or "unknown")[:24]
        return confidence_bucket, bool(rdns_available), cbg_bucket, operator

    def _reward(self, target: Target, result: GeoResult) -> float:
        if not result.is_ok() or not result.location or not result.location.has_coordinate:
            return -100000.0
        truth = Point(target.location.lat, target.location.lon)  # type: ignore[arg-type]
        pred = Point(result.location.lat, result.location.lon)  # type: ignore[arg-type]
        error = haversine_km(truth, pred)
        return -error - self.tool_cost_weight * result.cost.tool_calls - self.probe_cost_weight * result.cost.probe_count
