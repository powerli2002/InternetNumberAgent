from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

from agentic_ipv6_geo.common.config import load_runtime_config, runtime_warnings
from agentic_ipv6_geo.common.logger import JsonlLogger
from agentic_ipv6_geo.common.models import GeoResult, Location, Target
from agentic_ipv6_geo.data.repository import DataRepository
from agentic_ipv6_geo.providers.scamper import ScamperTraceProvider
from agentic_ipv6_geo.scheduler import RuleAgentScheduler
from agentic_ipv6_geo.tools.registry import METHOD_SPECS, build_methods


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


class IPv6GeoMcpRuntime:
    """MCP 工具运行时。

    运行时负责加载配置、构造数据仓库和工具实例。所有相对路径都按
    `GraduatePaper/` 根目录解析，保证 MCP 从任意工作目录启动时行为一致。
    """

    def __init__(self, config_path: str | Path = "configs/default.json"):
        self.project_root = _project_root()
        self.config_path = self._resolve_path(config_path)
        self.config = self._normalized_config(load_runtime_config(self.config_path))
        self.repo = DataRepository(self.config.get("data_dir", str(self.project_root / "data" / "processed")))
        self.methods = build_methods(self.repo, self.config, self.repo.targets)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "project_root": str(self.project_root),
            "config_path": str(self.config_path),
            "target_count": len(self.repo.targets),
            "warnings": runtime_warnings(self.config),
        }

    def list_geo_tools(self) -> dict[str, Any]:
        return {
            "tools": [
                {
                    "id": spec.id,
                    "name": spec.name,
                    "category": spec.category,
                    "description": spec.description,
                    "cost_level": spec.cost_level,
                    "evidence_type": spec.evidence_type,
                    "default_enabled": spec.default_enabled,
                }
                for spec in METHOD_SPECS
            ],
            "composite_tools": ["fusion", "scheduler_rule", "scamper_constraints"],
        }

    def run_geo_tool(self, ip: str, tool_id: str) -> dict[str, Any]:
        target = self._target_for(ip)
        if tool_id == "scheduler_rule":
            return self.geolocate_ip(ip, include_candidates=True)
        if tool_id == "fusion":
            results = [self.methods[name].run(target) for name in ["modugeo", "rdns", "active_triangulation", "passive_ipdb", "whois"]]
            return self._result_payload(self.methods["fusion"].run(results), target, {"input_results": [item.to_dict() for item in results]})
        tool = self.methods.get(tool_id)
        if tool is None:
            return {
                "status": "unavailable",
                "failure_reason": f"未知工具：{tool_id}",
                "available_tools": sorted([spec.id for spec in METHOD_SPECS] + ["fusion", "scheduler_rule"]),
            }
        return self._result_payload(tool.run(target), target)

    def geolocate_ip(self, ip: str, include_candidates: bool = False) -> dict[str, Any]:
        target = self._target_for(ip)
        scheduler = RuleAgentScheduler(
            self.methods["modugeo"],
            self.methods["rdns"],
            self.methods["active_triangulation"],
            self.methods["whois"],
            self.methods.get("passive_ipdb"),
            self.methods["fusion"],
            self.config.get("scheduler"),
            JsonlLogger(self.config.get("log_path")),
        )
        result = scheduler.run(target)
        extra: dict[str, Any] = {}
        if include_candidates:
            extra["candidate_results"] = result.evidence.get("scheduler", {}).get("candidate_results", [])
        return self._result_payload(result, target, extra)

    def debug_geo_tools(self, ip: str) -> dict[str, Any]:
        target = self._target_for(ip)
        tool_results = {}
        raw_results: list[GeoResult] = []
        for tool_id in ["modugeo", "rdns", "active_triangulation", "passive_ipdb", "whois"]:
            result = self.methods[tool_id].run(target)
            raw_results.append(result)
            tool_results[tool_id] = result.to_dict()
        fusion = self.methods["fusion"].run(raw_results)
        scheduler = self.geolocate_ip(ip, include_candidates=True)
        return {
            "target": self._target_payload(target),
            "tools": tool_results,
            "fusion": fusion.to_dict(),
            "scheduler_rule": scheduler,
        }

    def collect_scamper_constraints(self, ip: str, allow_live: bool = False) -> dict[str, Any]:
        config = copy.deepcopy(self.config)
        config.setdefault("active_probe", {})["allow_live_measurements"] = bool(allow_live)
        provider_config = {
            "active_probe": config.get("active_probe", {}),
            "scamper": config.get("scamper", {}),
            "ripe_atlas": config.get("ripe_atlas", {}),
            "external_services": config.get("external_services", {}),
        }
        result = ScamperTraceProvider(provider_config).collect(ip, self.repo)
        return {
            "status": result.status,
            "failure_reason": result.failure_reason,
            "constraint_count": len(result.constraints),
            "constraints": [
                {
                    "probe_id": item.probe.probe_id,
                    "lat": item.probe.location.lat,
                    "lon": item.probe.location.lon,
                    "rtt_ms": item.rtt_ms,
                    "source": item.source,
                    "evidence": item.evidence,
                }
                for item in result.constraints
            ],
            "evidence": result.evidence,
        }

    def _target_for(self, ip: str) -> Target:
        normalized = ip.strip()
        for target in self.repo.targets:
            if target.ip == normalized:
                return target
        metadata = self.repo.metadata_for(normalized)
        return Target(
            ip=normalized,
            location=Location(),
            asn=metadata.asn if metadata else None,
            operator=metadata.operator if metadata else None,
        )

    def _result_payload(self, result: GeoResult, target: Target, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "target": self._target_payload(target),
            "result": result.to_dict(),
        }
        if extra:
            payload.update(extra)
        return payload

    @staticmethod
    def _target_payload(target: Target) -> dict[str, Any]:
        return {
            "ip": target.ip,
            "asn": target.asn,
            "operator": target.operator,
            "truth_location": {
                "lat": target.location.lat,
                "lon": target.location.lon,
                "region": target.location.region,
                "city": target.location.city,
            },
        }

    def _resolve_path(self, path: str | Path) -> Path:
        value = Path(path)
        return value if value.is_absolute() else self.project_root / value

    def _normalized_config(self, config: dict[str, Any]) -> dict[str, Any]:
        normalized = copy.deepcopy(config)
        self._normalize_key(normalized, "data_dir")
        self._normalize_key(normalized, "log_path")
        self._normalize_nested_key(normalized, ("active_probe", "cache_dir"))
        self._normalize_nested_key(normalized, ("scamper", "scampertrace_root"))
        self._normalize_nested_key(normalized, ("scamper", "output_dir"))
        self._normalize_nested_key(normalized, ("rdns", "cache_path"))
        passive = normalized.get("passive_ipdb", {})
        for source in passive.get("sources", []):
            for key in ("path", "root", "ipv4_path", "ipv6_path"):
                if source.get(key):
                    source[key] = str(self._resolve_path(source[key]))
        if passive.get("path"):
            passive["path"] = str(self._resolve_path(passive["path"]))
        return normalized

    def _normalize_key(self, config: dict[str, Any], key: str) -> None:
        if config.get(key):
            config[key] = str(self._resolve_path(config[key]))

    def _normalize_nested_key(self, config: dict[str, Any], keys: tuple[str, str]) -> None:
        parent, child = keys
        node = config.get(parent)
        if isinstance(node, dict) and node.get(child):
            node[child] = str(self._resolve_path(node[child]))


def create_mcp_server(config_path: str | Path = "configs/default.json"):
    try:
        from fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover - 依赖缺失时只给启动提示
        raise RuntimeError("缺少 fastmcp 依赖，请运行：uv sync --extra mcp") from exc

    runtime = IPv6GeoMcpRuntime(config_path)
    mcp = FastMCP(
        name="agentic-ipv6-geo",
        instructions="Agentic IPv6 地理位置推断工具服务，只调度可复现实验工具，不让 LLM 直接预测经纬度。",
    )

    @mcp.tool
    def health() -> dict[str, Any]:
        """检查 Agentic IPv6 Geo MCP 服务状态。"""
        return runtime.health()

    @mcp.tool
    def list_geo_tools() -> dict[str, Any]:
        """列出可调用的 IPv6 定位工具。"""
        return runtime.list_geo_tools()

    @mcp.tool
    def run_geo_tool(ip: str, tool_id: str) -> dict[str, Any]:
        """对单个 IPv6 地址运行指定工具。tool_id 可取 modugeo、rdns、active_triangulation、passive_ipdb、whois、fusion、scheduler_rule。"""
        return runtime.run_geo_tool(ip, tool_id)

    @mcp.tool
    def geolocate_ip(ip: str, include_candidates: bool = False) -> dict[str, Any]:
        """使用规则 Agent 调度器定位单个 IPv6 地址。"""
        return runtime.geolocate_ip(ip, include_candidates=include_candidates)

    @mcp.tool
    def debug_geo_tools(ip: str) -> dict[str, Any]:
        """运行所有定位工具并返回调试信息。"""
        return runtime.debug_geo_tools(ip)

    @mcp.tool
    def collect_scamper_constraints(ip: str, allow_live: bool = False) -> dict[str, Any]:
        """读取或触发 scampertrace，返回可用于 CBG 的 RTT 约束。"""
        return runtime.collect_scamper_constraints(ip, allow_live=allow_live)

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 Agentic IPv6 Geo MCP server")
    parser.add_argument("--config", default="configs/default.json")
    args = parser.parse_args()
    create_mcp_server(args.config).run()


if __name__ == "__main__":
    main()
