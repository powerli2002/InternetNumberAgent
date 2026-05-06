from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agentic_ipv6_geo.data.repository import DataRepository
from agentic_ipv6_geo.fusion import FusionTool
from agentic_ipv6_geo.tools import ActiveTriangulationTool, ModuGeoTool, PassiveIpDbGeoTool, RDnsGeoTool, WhoisBgpContextTool


@dataclass(frozen=True)
class MethodSpec:
    id: str
    name: str
    category: str
    description: str
    config_key: str | None
    cost_level: str
    evidence_type: str
    default_enabled: bool
    factory: Callable[[DataRepository, dict[str, Any]], Any]


METHOD_SPECS: tuple[MethodSpec, ...] = (
    MethodSpec(
        id="modugeo",
        name="ModuGeo",
        category="核心定位器",
        description="复用 TrustGeo/ModuGeo 核心预测，缺失时回退到多尺度前缀与语义基线。",
        config_key="modugeo",
        cost_level="低",
        evidence_type="前缀先验 + last-hop 条件证据",
        default_enabled=True,
        factory=lambda repo, cfg: ModuGeoTool(repo, cfg),
    ),
    MethodSpec(
        id="active_triangulation",
        name="主动三角定位",
        category="主动测距",
        description="复用 GraduatePaper/cbgtool 的 CBG 约束圆交集方法；NCR/NCR-CBG 仅保留为备选。",
        config_key="active_triangulation",
        cost_level="高",
        evidence_type="探针 RTT 约束圆",
        default_enabled=True,
        factory=lambda repo, cfg: ActiveTriangulationTool(repo, cfg),
    ),
    MethodSpec(
        id="rdns",
        name="rDNS",
        category="语义证据",
        description="从 hostname 中解析城市缩写、拼音、机场码等地理语义。",
        config_key="rdns",
        cost_level="低",
        evidence_type="hostname 地理词",
        default_enabled=True,
        factory=lambda repo, cfg: RDnsGeoTool(repo, cfg),
    ),
    MethodSpec(
        id="whois",
        name="WHOIS/BGP",
        category="上下文",
        description="提供 ASN、组织、BGP 前缀与注册地上下文，不作为强定位器。",
        config_key=None,
        cost_level="低",
        evidence_type="注册与路由上下文",
        default_enabled=True,
        factory=lambda repo, cfg: WhoisBgpContextTool(repo, cfg),
    ),
    MethodSpec(
        id="passive_ipdb",
        name="被动 IPDB",
        category="被动定位",
        description="使用本地 IP 地理位置数据库输出低成本候选位置。",
        config_key="passive_ipdb",
        cost_level="低",
        evidence_type="本地 IP 数据库",
        default_enabled=True,
        factory=lambda repo, cfg: PassiveIpDbGeoTool(repo, cfg),
    ),
)


def build_methods(repo: DataRepository, config: dict[str, Any], train_targets: list | None = None) -> dict[str, Any]:
    methods = {}
    for spec in METHOD_SPECS:
        tool_config = config.get(spec.config_key, {}) if spec.config_key else {}
        if spec.id == "active_triangulation":
            tool_config = {
                **tool_config,
                "active_probe": config.get("active_probe", {}),
                "scamper": config.get("scamper", {}),
                "ripe_atlas": config.get("ripe_atlas", {}),
                "external_services": config.get("external_services", {}),
            }
        tool = spec.factory(repo, tool_config)
        if train_targets is not None and hasattr(tool, "fit"):
            tool.fit(train_targets)
        methods[spec.id] = tool
    methods["fusion"] = FusionTool(config.get("fusion"))
    return methods


def method_spec_by_id(method_id: str) -> MethodSpec | None:
    return next((spec for spec in METHOD_SPECS if spec.id == method_id), None)
