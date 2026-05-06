from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_RUNTIME_CONFIG: dict[str, Any] = {
    "secrets_config_path": "configs/local.secrets.json",
    "external_services": {
        "ripe_atlas": {
            "base_url": "https://atlas.ripe.net/api/v2",
            "api_key_env": "RIPE_ATLAS_API_KEY",
            "auth_header_env": "RIPE_ATLAS_AUTH_HEADER",
            "timeout_seconds": 30,
        },
        "qwen": {
            "api_key_env": "QWEN_API_KEY",
            "base_url_env": "QWEN_BASE_URL",
            "model": "qwen3.5",
            "timeout_seconds": 60,
        },
    },
    "scamper": {
        "scampertrace_root": "scampertrace",
        "scamper_path": "scamper",
        "sc_warts2csv_path": "sc_warts2csv",
        "use_sudo": False,
        "pps": 10,
        "timeout_seconds": 180,
        "output_dir": "outputs/active_probe/scamper",
    },
    "active_probe": {
        "allow_live_measurements": False,
        "provider_order": ["existing_trace", "scamper", "ripe_atlas"],
        "cache_dir": "outputs/active_probe/cache",
        "max_targets_per_run": 10,
        "max_probes_per_target": 5,
        "min_probe_constraints": 3,
    },
    "ripe_atlas": {
        "probe_selection": [{"requested": 3, "type": "countries", "value": "CN"}],
        "tags_include": ["system-ipv6-works"],
        "measurement_description": "agentic-ipv6-geo traceroute",
        "protocol": "ICMP",
        "poll_interval_seconds": 15,
        "max_poll_attempts": 20,
    },
    "passive_ipdb": {
        "enabled": False,
        "backend": "csv",
        "path": "",
        "default_confidence": 0.35,
    },
    "llm_baseline": {
        "enabled": False,
        "provider": "qwen",
        "model": "qwen3.5",
        "max_steps": 4,
        "trajectory_path": "outputs/rl/trajectories/qwen_baseline.jsonl",
    },
    "rl": {
        "trajectory_dir": "outputs/rl/trajectories",
        "reward_summary_path": "outputs/rl/reward_summary.json",
        "policy_path": "outputs/rl/policy.json",
        "max_steps": 4,
        "reward": {
            "tool_cost_weight": 10.0,
            "probe_cost_weight": 2.0,
            "conflict_weight": 0.05,
            "coverage_reward": 50.0,
            "invalid_action_penalty": 1000.0,
        },
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_runtime_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as fh:
        user_config = json.load(fh)
    config = deep_merge(DEFAULT_RUNTIME_CONFIG, user_config)
    secrets_path = _resolve_secrets_path(config, config_path)
    if secrets_path and secrets_path.exists():
        with secrets_path.open("r", encoding="utf-8") as fh:
            config = deep_merge(config, json.load(fh))
    return config


def _resolve_secrets_path(config: dict[str, Any], config_path: Path) -> Path | None:
    override = os.environ.get("AGENTIC_IPV6_GEO_SECRETS")
    raw_path = override or config.get("secrets_config_path")
    if not raw_path:
        return None
    secrets_path = Path(str(raw_path))
    if secrets_path.is_absolute():
        return secrets_path
    # 优先按当前工作目录解析；不存在时再按主配置所在目录解析，便于脚本和测试共用。
    cwd_path = Path.cwd() / secrets_path
    if cwd_path.exists():
        return cwd_path
    return config_path.parent.parent / secrets_path


def env_value(config: dict[str, Any], *keys: str) -> str | None:
    node: Any = config
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    if not node:
        return None
    return os.environ.get(str(node))


def runtime_warnings(config: dict[str, Any]) -> list[str]:
    warnings = []
    if config.get("active_probe", {}).get("allow_live_measurements"):
        atlas_cfg = config.get("external_services", {}).get("ripe_atlas", {})
        has_key = bool(os.environ.get(str(atlas_cfg.get("api_key_env", ""))))
        has_header = bool(os.environ.get(str(atlas_cfg.get("auth_header_env", ""))))
        has_inline = bool(atlas_cfg.get("api_key") or atlas_cfg.get("auth_header"))
        if not has_key and not has_header and not has_inline:
            warnings.append("已允许真实主动探测，但缺少 RIPE Atlas 认证环境变量")
    if config.get("llm_baseline", {}).get("enabled"):
        qwen_cfg = config.get("external_services", {}).get("qwen", {})
        if not os.environ.get(str(qwen_cfg.get("api_key_env", ""))):
            warnings.append("已启用 Qwen baseline，但缺少 Qwen API key 环境变量")
    if config.get("passive_ipdb", {}).get("enabled") and not config.get("passive_ipdb", {}).get("path"):
        warnings.append("已启用被动 IPDB，但未配置数据库路径")
    return warnings
