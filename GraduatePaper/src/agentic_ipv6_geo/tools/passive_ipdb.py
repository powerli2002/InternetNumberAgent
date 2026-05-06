from __future__ import annotations

import csv
import ipaddress
from pathlib import Path
from typing import Any

from agentic_ipv6_geo.common.models import GeoResult, Location, Target
from agentic_ipv6_geo.tools.base import BaseGeoTool


class PassiveIpDbGeoTool(BaseGeoTool):
    """基于本地 IP 数据库的低成本被动定位工具。"""

    name = "PassiveIPDB"

    def __init__(self, repo, config: dict[str, Any] | None = None):
        super().__init__(repo, config)
        self.enabled = bool(self.config.get("enabled", False))
        self.backend = str(self.config.get("backend", "csv"))
        self.path = Path(self.config.get("path", "")) if self.config.get("path") else None
        self.default_confidence = float(self.config.get("default_confidence", 0.35))
        self._rows: list[dict[str, Any]] | None = None

    def _run(self, target: Target) -> GeoResult:
        if not self.enabled:
            return GeoResult(tool=self.name, status="unavailable", failure_reason="未启用被动 IP 数据库定位")
        if self.backend != "csv":
            return GeoResult(tool=self.name, status="unavailable", failure_reason=f"暂不支持的被动 IPDB backend: {self.backend}")
        if not self.path or not self.path.exists():
            return GeoResult(tool=self.name, status="unavailable", failure_reason="被动 IPDB 文件不存在")

        row = self._lookup_csv(target.ip)
        if not row:
            return GeoResult(tool=self.name, status="unavailable", failure_reason="被动 IPDB 未命中目标")
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except Exception:
            return GeoResult(tool=self.name, status="unavailable", failure_reason="被动 IPDB 命中记录缺少有效经纬度", evidence=row)

        granularity = row.get("granularity") or ("city" if row.get("city") else "region")
        confidence = float(row.get("confidence") or self.default_confidence)
        return GeoResult(
            tool=self.name,
            status="ok",
            location=Location(lat=lat, lon=lon, region=row.get("region") or None, city=row.get("city") or None),
            granularity=granularity,
            confidence=max(0.0, min(1.0, confidence)),
            evidence={
                "backend": self.backend,
                "path": str(self.path),
                "matched": row.get("ip") or row.get("prefix"),
                "database": row.get("database") or self.path.name,
                "version": row.get("version"),
                "note": "被动 IPDB 只作为低成本候选证据，不作为真值",
            },
        )

    def _lookup_csv(self, ip: str) -> dict[str, Any] | None:
        address = ipaddress.ip_address(ip)
        best_prefix: tuple[int, dict[str, Any]] | None = None
        for row in self._load_rows():
            if row.get("ip") == ip:
                return row
            prefix = row.get("prefix")
            if not prefix:
                continue
            try:
                network = ipaddress.ip_network(prefix, strict=False)
            except ValueError:
                continue
            if address in network and (best_prefix is None or network.prefixlen > best_prefix[0]):
                best_prefix = (network.prefixlen, row)
        return best_prefix[1] if best_prefix else None

    def _load_rows(self) -> list[dict[str, Any]]:
        if self._rows is not None:
            return self._rows
        assert self.path is not None
        with self.path.open("r", encoding="utf-8-sig", newline="") as fh:
            self._rows = list(csv.DictReader(fh))
        return self._rows
