from __future__ import annotations

import csv
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentic_ipv6_geo.common.models import RDnsRecord


class RDnsCollector:
    """按需采集 rDNS hostname，并保持可复现缓存。"""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.enabled = bool(self.config.get("enable_active_collection", False))
        self.use_system_resolver = bool(self.config.get("use_system_resolver", True))
        self.cache_path = Path(self.config.get("cache_path", "outputs/active_probe/rdns.csv"))

    def lookup(self, ip: str) -> tuple[RDnsRecord | None, dict[str, Any]]:
        cached = self._lookup_cache(ip)
        if cached:
            return cached, {"source": "rdns_cache", "cache_path": str(self.cache_path)}
        if not self.enabled:
            return None, {"status": "unavailable", "failure_reason": "未启用 rDNS 主动采集"}
        if not self.use_system_resolver:
            return None, {"status": "unavailable", "failure_reason": "未配置可用 rDNS resolver"}
        try:
            hostname, _aliases, _addresses = socket.gethostbyaddr(ip)
        except Exception as exc:
            return None, {"status": "unavailable", "failure_reason": f"rDNS 查询失败: {exc}"}
        record = RDnsRecord(ip=ip, hostname=hostname, resolved_at=datetime.now(timezone.utc).isoformat())
        self._append_cache(record, source="system_resolver", status="ok", failure_reason="")
        return record, {"source": "system_resolver", "cache_path": str(self.cache_path)}

    def _lookup_cache(self, ip: str) -> RDnsRecord | None:
        if not self.cache_path.exists():
            return None
        with self.cache_path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("ip") == ip and row.get("hostname"):
                    return RDnsRecord(ip=ip, hostname=row["hostname"], resolved_at=row.get("resolved_at") or None)
        return None

    def _append_cache(self, record: RDnsRecord, source: str, status: str, failure_reason: str) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        exists = self.cache_path.exists()
        with self.cache_path.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["ip", "hostname", "resolved_at", "source", "status", "failure_reason"],
            )
            if not exists:
                writer.writeheader()
            writer.writerow(
                {
                    "ip": record.ip,
                    "hostname": record.hostname,
                    "resolved_at": record.resolved_at or "",
                    "source": source,
                    "status": status,
                    "failure_reason": failure_reason,
                }
            )
