from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from agentic_ipv6_geo.common.geo import Point, haversine_km
from agentic_ipv6_geo.common.logger import JsonlLogger
from agentic_ipv6_geo.common.models import GeoResult, Target
from agentic_ipv6_geo.fusion import FusionTool
from agentic_ipv6_geo.tools import ActiveTriangulationTool, ModuGeoTool, PassiveIpDbGeoTool, RDnsGeoTool, WhoisBgpContextTool


class OfflineRewardPolicyScheduler:
    """离线奖励优化策略。

    该策略先枚举工具动作并用训练集真值计算奖励，再在测试时按上下文选择平均奖励最高的动作。
    它不是在线 RL，但提供了后续接入 SFT/GRPO/PPO 前可复现的 policy 数据闭环。
    """

    ACTIONS = ("stop", "rdns", "active", "passive", "all")

    def __init__(
        self,
        modugeo: ModuGeoTool,
        rdns: RDnsGeoTool,
        active_triangulation: ActiveTriangulationTool,
        whois_bgp: WhoisBgpContextTool,
        passive_ipdb: PassiveIpDbGeoTool,
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
        self.reward_cfg = self.config.get("reward", {})
        self.logger = logger or JsonlLogger(None)
        self.policy: dict[tuple, str] = {}
        self.global_action = "stop"

    def fit(self, targets: list[Target]) -> None:
        by_context: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        global_rewards: dict[str, list[float]] = defaultdict(list)
        for target in targets:
            base = self.modugeo.run(target)
            context = self._context(target, base)
            for action in self.ACTIONS:
                result = self._run_action(target, base, action)
                reward = self.reward(target, result)
                by_context[context][action].append(reward)
                global_rewards[action].append(reward)
        for context, values_by_action in by_context.items():
            averages = {action: sum(values) / len(values) for action, values in values_by_action.items() if values}
            if averages:
                self.policy[context] = max(averages, key=averages.get)
        global_averages = {action: sum(values) / len(values) for action, values in global_rewards.items() if values}
        if global_averages:
            self.global_action = max(global_averages, key=global_averages.get)
        self._write_policy()

    def run(self, target: Target) -> GeoResult:
        base = self.modugeo.run(target)
        context = self._context(target, base)
        action = self.policy.get(context, self.global_action)
        result = self._run_action(target, base, action)
        result.evidence["scheduler"] = {
            "type": "offline_reward_policy",
            "context": list(context),
            "selected_action": action,
            "global_action": self.global_action,
            "known_context_count": len(self.policy),
        }
        self.logger.log("rl_policy_action", target_ip=target.ip, action=action, context=list(context))
        return result

    def reward(self, target: Target, result: GeoResult) -> float:
        if not result.is_ok() or not result.location or not result.location.has_coordinate:
            return -float(self.reward_cfg.get("invalid_action_penalty", 1000.0))
        truth = Point(target.location.lat, target.location.lon)  # type: ignore[arg-type]
        pred = Point(result.location.lat, result.location.lon)  # type: ignore[arg-type]
        error = haversine_km(truth, pred)
        conflict = max((item.get("distance_km", 0.0) for item in result.evidence.get("conflicts", [])), default=0.0)
        return (
            -error
            - float(self.reward_cfg.get("tool_cost_weight", 10.0)) * result.cost.tool_calls
            - float(self.reward_cfg.get("probe_cost_weight", 2.0)) * result.cost.probe_count
            - float(self.reward_cfg.get("conflict_weight", 0.05)) * conflict
            + float(self.reward_cfg.get("coverage_reward", 50.0))
        )

    def _run_action(self, target: Target, base: GeoResult, action: str) -> GeoResult:
        results = [base, self.whois_bgp.run(target)]
        if action in {"rdns", "all"}:
            results.append(self.rdns.run(target))
        if action in {"active", "all"}:
            results.append(self.active_triangulation.run(target))
        if action in {"passive", "all"}:
            results.append(self.passive_ipdb.run(target))
        fused = self.fusion.run(results)
        return fused if fused.status == "ok" else base

    def _context(self, target: Target, base: GeoResult) -> tuple:
        confidence_bucket = "high" if base.confidence >= 0.7 else ("mid" if base.confidence >= 0.45 else "low")
        active_constraints = len(self.active_triangulation._constraints(target))
        active_bucket = "active3" if active_constraints >= self.active_triangulation.min_constraints else "active_lt3"
        return (
            confidence_bucket,
            bool(self.rdns.repo.rdns_for(target.ip)),
            active_bucket,
            bool(self.passive_ipdb.enabled),
            (target.operator or "unknown")[:24],
        )

    def _write_policy(self) -> None:
        path = self.config.get("policy_path")
        if not path:
            return
        policy_path = Path(path)
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "global_action": self.global_action,
            "policy": [{"context": list(context), "action": action} for context, action in self.policy.items()],
        }
        with policy_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
