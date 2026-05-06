from __future__ import annotations

EXPERIMENT_DISPLAY_NAMES = {
    "single_modugeo": "ModuGeo",
    "single_rdns": "rDNS",
    "single_active_triangulation": "主动三角定位",
    "single_passive_ipdb": "被动 IPDB",
    "fusion_modugeo_rdns": "ModuGeo + rDNS",
    "fusion_modugeo_active": "ModuGeo + 主动定位",
    "fusion_modugeo_passive": "ModuGeo + 被动 IPDB",
    "fusion_all": "全部融合",
    "scheduler_rule": "规则调度",
    "scheduler_bandit": "Bandit 调度",
    "scheduler_qwen_baseline": "Qwen3.5 Baseline",
    "scheduler_rl_policy": "RL Policy",
}

TOOL_DISPLAY_NAMES = {
    "ModuGeo": "ModuGeo",
    "rDNS": "rDNS",
    "ActiveTriangulation": "主动三角定位",
    "CBG": "传统 CBG",
    "WhoisBGP": "WHOIS/BGP 上下文",
    "PassiveIPDB": "被动 IPDB",
    "Fusion": "融合器",
    "RuleAgentScheduler": "规则调度器",
}


def display_experiment_name(experiment_id: str | None) -> str:
    if not experiment_id:
        return "未知实验"
    return EXPERIMENT_DISPLAY_NAMES.get(experiment_id, experiment_id)


def display_tool_name(tool_name: str | None) -> str:
    if not tool_name:
        return "未知工具"
    return TOOL_DISPLAY_NAMES.get(tool_name, tool_name)
