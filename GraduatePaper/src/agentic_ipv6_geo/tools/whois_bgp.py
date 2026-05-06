from __future__ import annotations

from agentic_ipv6_geo.common.models import GeoResult, Location, Target
from agentic_ipv6_geo.tools.base import BaseGeoTool


class WhoisBgpContextTool(BaseGeoTool):
    name = "WhoisBGP"

    def _run(self, target: Target) -> GeoResult:
        metadata = self.repo.metadata_for(target.ip)
        if not metadata:
            return GeoResult(tool=self.name, status="unavailable", failure_reason="未找到匹配的 WHOIS/BGP 元数据")

        location = None
        granularity = "context"
        confidence = 0.15
        if metadata.registered_region or metadata.registered_city:
            location = Location(region=metadata.registered_region, city=metadata.registered_city)
            granularity = "registered_region"
            confidence = 0.2

        return GeoResult(
            tool=self.name,
            status="ok",
            location=location,
            granularity=granularity,
            confidence=confidence,
            evidence={
                "prefix": metadata.prefix,
                "bgp_prefix": metadata.bgp_prefix,
                "asn": metadata.asn,
                "org": metadata.org,
                "operator": metadata.operator,
                "registered_region": metadata.registered_region,
                "registered_city": metadata.registered_city,
                "note": "WHOIS/BGP 仅作为上下文证据，不作为强定位器",
            },
        )
