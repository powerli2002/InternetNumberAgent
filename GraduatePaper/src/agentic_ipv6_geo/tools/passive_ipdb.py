from __future__ import annotations

import csv
import ipaddress
import json
import subprocess
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
        self.sources = list(self.config.get("sources", []))
        self._rows: list[dict[str, Any]] | None = None

    def _run(self, target: Target) -> GeoResult:
        if not self.enabled:
            return GeoResult(tool=self.name, status="unavailable", failure_reason="未启用被动 IP 数据库定位")
        if self.sources:
            failures = []
            for source in self.sources:
                if source.get("enabled", True) is False:
                    continue
                result = self._run_source(target, source)
                if result.status == "ok":
                    return result
                failures.append({"source": source.get("name"), "reason": result.failure_reason, "evidence": result.evidence})
            return GeoResult(tool=self.name, status="unavailable", failure_reason="所有被动 IPDB 数据源均不可用或未命中", evidence={"failures": failures})
        if self.backend != "csv":
            return GeoResult(tool=self.name, status="unavailable", failure_reason=f"暂不支持的被动 IPDB backend: {self.backend}")
        if not self.path or not self.path.exists():
            return GeoResult(tool=self.name, status="unavailable", failure_reason="被动 IPDB 文件不存在")

        row = self._lookup_csv(target.ip)
        if not row:
            return GeoResult(tool=self.name, status="unavailable", failure_reason="被动 IPDB 未命中目标")
        return self._result_from_row(row, {"name": self.path.name, "backend": self.backend})

    def _run_source(self, target: Target, source: dict[str, Any]) -> GeoResult:
        backend = str(source.get("backend", "csv"))
        if backend == "csv":
            original_path, original_confidence = self.path, self.default_confidence
            self.path = Path(source.get("path", "")) if source.get("path") else None
            self.default_confidence = float(source.get("default_confidence", original_confidence))
            self._rows = None
            result = self._run_csv_source(target, source)
            self.path, self.default_confidence = original_path, original_confidence
            self._rows = None
            return result
        if backend == "aiwen_tsv":
            return self._run_aiwen_tsv(target, source)
        if backend == "ip_database_php":
            return self._run_ip_database_php(target, source)
        if backend == "geocn_mmdb":
            return self._run_geocn_mmdb(target, source)
        return GeoResult(tool=self.name, status="unavailable", failure_reason=f"暂不支持的被动 IPDB backend: {backend}", evidence={"source": source.get("name")})

    def _run_csv_source(self, target: Target, source: dict[str, Any]) -> GeoResult:
        if not self.path or not self.path.exists():
            return GeoResult(tool=self.name, status="unavailable", failure_reason="CSV 被动 IPDB 文件不存在", evidence={"source": source.get("name"), "path": str(self.path)})
        row = self._lookup_csv(target.ip)
        if not row:
            return GeoResult(tool=self.name, status="unavailable", failure_reason="CSV 被动 IPDB 未命中目标", evidence={"source": source.get("name")})
        return self._result_from_row(row, source)

    def _run_aiwen_tsv(self, target: Target, source: dict[str, Any]) -> GeoResult:
        address = ipaddress.ip_address(target.ip)
        if address.version != 4:
            return GeoResult(
                tool=self.name,
                status="unavailable",
                failure_reason="Aiwen database/scripts 口径使用 IPv4 整数区间，未确认可支持 IPv6",
                evidence={"source": source.get("name"), "ip_version": address.version},
            )
        path = Path(source.get("path", ""))
        if not path.exists():
            return GeoResult(tool=self.name, status="unavailable", failure_reason="Aiwen 数据文件不存在", evidence={"path": str(path)})
        ip_int = int(address)
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as fh:
            reader = csv.DictReader(
                fh,
                delimiter="\t",
                fieldnames=[
                    "id",
                    "minip",
                    "maxip",
                    "continent",
                    "areacode",
                    "adcode",
                    "country",
                    "region",
                    "city",
                    "district",
                    "lon",
                    "lat",
                    "radius",
                    "granularity",
                    "owner",
                    "isp",
                    "asnumber",
                    "source",
                    "zipcode",
                    "timezone",
                ],
            )
            next(reader, None)
            for row in reader:
                try:
                    if int(row["minip"].strip('"')) <= ip_int <= int(row["maxip"].strip('"')):
                        cleaned = {key: (value or "").strip('"') for key, value in row.items()}
                        cleaned["database"] = source.get("name", "aiwen")
                        cleaned["confidence"] = source.get("default_confidence", self.default_confidence)
                        return self._result_from_row(cleaned, source)
                except Exception:
                    continue
        return GeoResult(tool=self.name, status="unavailable", failure_reason="Aiwen 被动 IPDB 未命中目标", evidence={"source": source.get("name")})

    def _run_ip_database_php(self, target: Target, source: dict[str, Any]) -> GeoResult:
        root = Path(source.get("root", ""))
        ipv4_path = source.get("ipv4_path", "")
        ipv6_path = source.get("ipv6_path", "")
        if not root.exists():
            return GeoResult(tool=self.name, status="unavailable", failure_reason="ip-database 项目目录不存在", evidence={"root": str(root)})
        if ipaddress.ip_address(target.ip).version == 6 and ipv6_path and not Path(ipv6_path).exists():
            return GeoResult(tool=self.name, status="unavailable", failure_reason="ip-database IPv6 数据文件不存在", evidence={"ipv6_path": ipv6_path})
        php = source.get("php_bin", "php")
        code = (
            "require 'src/IpLocation.php';"
            "require 'src/StringParser.php';"
            "require 'src/IpParser/IpParserInterface.php';"
            "require 'src/IpParser/QQwry.php';"
            "require 'src/IpParser/IpV6wry.php';"
            f"echo json_encode(\\itbdw\\Ip\\IpLocation::getLocation('{target.ip}', '{ipv4_path}', '{ipv6_path}'), JSON_UNESCAPED_UNICODE);"
        )
        try:
            proc = subprocess.run([php, "-r", code], cwd=root, text=True, capture_output=True, timeout=int(source.get("timeout_seconds", 10)), check=False)
        except Exception as exc:
            return GeoResult(tool=self.name, status="unavailable", failure_reason=f"ip-database PHP 调用失败: {exc}", evidence={"source": source.get("name")})
        if proc.returncode != 0:
            return GeoResult(tool=self.name, status="unavailable", failure_reason="ip-database PHP 返回非零退出码", evidence={"stderr": proc.stderr[-500:]})
        try:
            data = json.loads(proc.stdout)
        except Exception:
            return GeoResult(tool=self.name, status="unavailable", failure_reason="ip-database PHP 输出不是 JSON", evidence={"stdout": proc.stdout[-500:]})
        if data.get("error"):
            return GeoResult(tool=self.name, status="unavailable", failure_reason=data["error"], evidence={"source": source.get("name")})
        row = {
            "country": data.get("country"),
            "region": data.get("province"),
            "city": data.get("city"),
            "database": source.get("name", "ip-database"),
            "granularity": "city" if data.get("city") else "region",
            "confidence": source.get("default_confidence", self.default_confidence),
        }
        return self._result_from_row(row, source)

    def _run_geocn_mmdb(self, target: Target, source: dict[str, Any]) -> GeoResult:
        path = Path(source.get("path", ""))
        if not path.exists():
            return GeoResult(tool=self.name, status="unavailable", failure_reason="GeoCN.mmdb 数据文件不存在", evidence={"path": str(path)})
        try:
            import maxminddb  # type: ignore[import-not-found]
        except Exception as exc:
            return GeoResult(tool=self.name, status="unavailable", failure_reason=f"缺少 maxminddb Python 依赖: {exc}", evidence={"source": source.get("name")})
        try:
            with maxminddb.open_database(str(path)) as reader:
                data = reader.get(target.ip)
        except Exception as exc:
            return GeoResult(tool=self.name, status="unavailable", failure_reason=f"GeoCN.mmdb 查询失败: {exc}", evidence={"source": source.get("name")})
        if not data:
            return GeoResult(tool=self.name, status="unavailable", failure_reason="GeoCN.mmdb 未命中目标", evidence={"source": source.get("name")})
        geo_cn = data.get("geo_cn") if isinstance(data, dict) else None
        row = {
            "country": "中国",
            "region": _first_name(geo_cn, 0),
            "city": _first_name(geo_cn, 1),
            "database": source.get("name", "GeoCN"),
            "granularity": "city" if _first_name(geo_cn, 1) else "region",
            "confidence": source.get("default_confidence", self.default_confidence),
        }
        return self._result_from_row(row, source)

    def _result_from_row(self, row: dict[str, Any], source: dict[str, Any]) -> GeoResult:
        try:
            lat = _maybe_float(row.get("lat") or row.get("latitude") or row.get("latwgs"))
            lon = _maybe_float(row.get("lon") or row.get("longitude") or row.get("lngwgs"))
        except Exception:
            lat = lon = None
        region = _clean_region(row.get("region") or row.get("province"))
        city = _clean_region(row.get("city"))
        confidence = max(0.0, min(1.0, float(row.get("confidence") or source.get("default_confidence", self.default_confidence))))
        if lat is None or lon is None:
            if region or city:
                return GeoResult(
                    tool=self.name,
                    status="ok",
                    location=Location(region=region, city=city),
                    granularity=row.get("granularity") or ("city" if city else "region"),
                    confidence=confidence,
                    evidence={"source": source.get("name"), "database": row.get("database"), "note": "被动 IPDB 命中区域但缺少经纬度"},
                )
            return GeoResult(tool=self.name, status="unavailable", failure_reason="被动 IPDB 命中记录缺少有效地理字段", evidence={"source": source.get("name")})
        return GeoResult(
            tool=self.name,
            status="ok",
            location=Location(lat=lat, lon=lon, region=region, city=city),
            granularity=row.get("granularity") or ("city" if city else "region"),
            confidence=confidence,
            evidence={
                "source": source.get("name"),
                "backend": source.get("backend"),
                "database": row.get("database") or source.get("path") or source.get("root"),
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


def _maybe_float(value: Any) -> float | None:
    if value is None or str(value).strip() in {"", "NULL"}:
        return None
    return float(value)


def _clean_region(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "NULL":
        return None
    return text


def _first_name(geo_cn: Any, index: int) -> str | None:
    if not isinstance(geo_cn, dict):
        return None
    names = geo_cn.get("full") or geo_cn.get("short") or []
    if isinstance(names, list) and len(names) > index:
        return str(names[index])
    return None
