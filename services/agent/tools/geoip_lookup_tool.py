"""GeoIP 离线定位工具。

整合三个免费数据源，按优先级链式查询：
  1. GeoLite2-City.mmdb      — MaxMind，城市级，精度最高
  2. dbip-city-lite.mmdb     — DB-IP，城市级，月更，互补
  3. ipapi.is CSV (IPv6/IPv4) — 带 accuracy 字段和 source 字段，可溯源

数据目录默认 data/geoip/（相对于仓库根目录），可通过环境变量 GEOIP_DATA_DIR 覆盖。
"""

from __future__ import annotations

import bisect
import csv
import ipaddress
import os
import struct
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.tools.base import BaseTool, ToolResult
from fusiondata.src.utils.logging_manager import logger

__all__ = ["GeoIPLookupTool", "lookup_ipv6"]

# 仓库根目录
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data" / "geoip"


def _data_dir() -> Path:
    d = Path(os.environ.get("GEOIP_DATA_DIR", str(_DEFAULT_DATA_DIR)))
    if not d.exists():
        raise RuntimeError(f"GeoIP 数据目录不存在: {d}，请先运行下载脚本。")
    return d


# ---------------------------------------------------------------------------
# MMDB 读取（需要 geoip2 库）
# ---------------------------------------------------------------------------

def _mmdb_reader(path: Path):
    """惰性加载 MMDB reader，避免导入时崩溃。"""
    try:
        import geoip2.database  # type: ignore
    except ImportError as exc:
        raise RuntimeError("未安装 geoip2，请执行 pip install geoip2。") from exc
    return geoip2.database.Reader(str(path))


@lru_cache(maxsize=4)
def _get_reader(path_str: str):
    """按路径缓存 MMDB reader，进程内只开一次文件。"""
    return _mmdb_reader(Path(path_str))


def _query_mmdb_city(mmdb_path: Path, ip: str) -> Optional[Dict[str, Any]]:
    """查询 City MMDB，返回标准化结果字典，查不到返回 None。"""
    try:
        reader = _get_reader(str(mmdb_path))
        r = reader.city(ip)
        return {
            "ip": ip,
            "country_code": r.country.iso_code or "",
            "country": r.country.name or "",
            "region": r.subdivisions.most_specific.name or "",
            "city": r.city.name or "",
            "latitude": r.location.latitude,
            "longitude": r.location.longitude,
            "timezone": r.location.time_zone or "",
            "accuracy_radius": r.location.accuracy_radius,
            "source": mmdb_path.name,
        }
    except Exception:
        return None


def _query_mmdb_asn(mmdb_path: Path, ip: str) -> Optional[Dict[str, Any]]:
    """查询 ASN MMDB，返回 asn / org 字段。"""
    try:
        reader = _get_reader(str(mmdb_path))
        r = reader.asn(ip)
        return {
            "asn": r.autonomous_system_number,
            "org": r.autonomous_system_organization or "",
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# ipapi.is CSV 查询（区间二分搜索）
# ---------------------------------------------------------------------------

def _ip_to_int(ip_str: str) -> int:
    """统一转为 128 位整数（IPv4 映射为 IPv4-mapped IPv6）。"""
    addr = ipaddress.ip_address(ip_str)
    if isinstance(addr, ipaddress.IPv4Address):
        # 映射成 ::ffff:0:0/96 形式，统一比较
        return int(ipaddress.IPv6Address(f"::ffff:{ip_str}"))
    return int(addr)


class IpapiCSVDB:
    """ipapi.is CSV 数据库，启动时全量加载到内存，支持二分搜索。"""

    def __init__(self, csv_path: Path) -> None:
        self._ranges: List[Tuple[int, int, Dict[str, Any]]] = []
        self._load(csv_path)

    def _load(self, path: Path) -> None:
        logger.info("加载 ipapi.is CSV: %s", path)
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    start = _ip_to_int(row["start_ip"])
                    end = _ip_to_int(row["end_ip"])
                    self._ranges.append((start, end, dict(row)))
                except Exception:
                    continue
        # 按起始 IP 排序，供二分搜索
        self._ranges.sort(key=lambda x: x[0])
        self._starts = [r[0] for r in self._ranges]
        logger.info("ipapi.is CSV 加载完成，共 %d 条区间", len(self._ranges))

    def lookup(self, ip: str) -> Optional[Dict[str, Any]]:
        try:
            target = _ip_to_int(ip)
        except Exception:
            return None
        idx = bisect.bisect_right(self._starts, target) - 1
        if idx < 0:
            return None
        start, end, row = self._ranges[idx]
        if target > end:
            return None
        return {
            "ip": ip,
            "country_code": row.get("country_code", ""),
            "country": row.get("country", ""),
            "region": row.get("state", ""),
            "city": row.get("city", ""),
            "latitude": _safe_float(row.get("latitude")),
            "longitude": _safe_float(row.get("longitude")),
            "timezone": row.get("timezone", ""),
            "accuracy": row.get("accuracy", ""),
            "data_source": row.get("source", ""),
            "source": "ipapi.is",
        }


def _safe_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 单例缓存（避免每次调用重复加载 CSV）
# ---------------------------------------------------------------------------

_ipapi_v4_db: Optional[IpapiCSVDB] = None
_ipapi_v6_db: Optional[IpapiCSVDB] = None


def _get_ipapi_db(version: int) -> Optional[IpapiCSVDB]:
    global _ipapi_v4_db, _ipapi_v6_db
    d = _data_dir()
    if version == 6:
        if _ipapi_v6_db is None:
            p = d / "geolocationDatabaseIPv6.csv"
            if p.exists():
                _ipapi_v6_db = IpapiCSVDB(p)
        return _ipapi_v6_db
    else:
        if _ipapi_v4_db is None:
            p = d / "geolocationDatabaseIPv4.csv"
            if p.exists():
                _ipapi_v4_db = IpapiCSVDB(p)
        return _ipapi_v4_db


# ---------------------------------------------------------------------------
# 主查询函数
# ---------------------------------------------------------------------------

def lookup_ipv6(ip: str) -> Dict[str, Any]:
    """查询单个 IPv6 地址，返回聚合结果（含多源对比）。"""
    d = _data_dir()
    result: Dict[str, Any] = {"ip": ip, "sources": {}}

    # 1. GeoLite2 City
    mmdb_city = d / "GeoLite2-City.mmdb"
    if mmdb_city.exists():
        r = _query_mmdb_city(mmdb_city, ip)
        if r:
            result["sources"]["geolite2_city"] = r
            result.setdefault("country_code", r["country_code"])
            result.setdefault("country", r["country"])
            result.setdefault("city", r["city"])
            result.setdefault("latitude", r["latitude"])
            result.setdefault("longitude", r["longitude"])

    # 2. GeoLite2 ASN
    mmdb_asn = d / "GeoLite2-ASN.mmdb"
    if mmdb_asn.exists():
        r = _query_mmdb_asn(mmdb_asn, ip)
        if r:
            result["sources"]["geolite2_asn"] = r
            result.setdefault("asn", r["asn"])
            result.setdefault("org", r["org"])

    # 3. DB-IP City
    dbip_files = sorted(d.glob("dbip-city-lite-*.mmdb"))
    if dbip_files:
        r = _query_mmdb_city(dbip_files[-1], ip)
        if r:
            result["sources"]["dbip_city"] = r
            result.setdefault("country_code", r["country_code"])
            result.setdefault("city", r["city"])

    # 4. ipapi.is CSV
    db = _get_ipapi_db(6)
    if db:
        r = db.lookup(ip)
        if r:
            result["sources"]["ipapi_is"] = r
            result.setdefault("country_code", r["country_code"])
            result.setdefault("city", r["city"])
            result.setdefault("latitude", r["latitude"])
            result.setdefault("longitude", r["longitude"])

    return result


# ---------------------------------------------------------------------------
# BaseTool 封装
# ---------------------------------------------------------------------------

class GeoIPLookupTool(BaseTool):
    """IPv6/IPv4 离线 GeoIP 定位工具，整合 GeoLite2 + DB-IP + ipapi.is 三源。

    查询结果包含多源对比（sources 字段），顶层字段取首个命中源的值，
    metadata 中记录各源命中情况。
    """

    schema: Dict[str, Any] = {
        "name": "geoip_lookup",
        "description": (
            "离线查询 IPv6 或 IPv4 地址的地理位置（国家/城市/经纬度/ASN）。"
            "整合 GeoLite2、DB-IP、ipapi.is 三个免费数据库，结果带多源对比。"
            "适用于「这个 IP 在哪里」「归属运营商」等实时定位问题。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ips": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要查询的 IP 地址列表，支持 IPv4 和 IPv6 混合。",
                },
            },
            "required": ["ips"],
        },
    }

    async def aexecute(self, ips: List[str], **_) -> ToolResult:
        if not ips:
            return ToolResult(success=False, error="ips 不能为空")

        results = []
        errors = []
        for ip in ips:
            ip = ip.strip()
            if not ip:
                continue
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                errors.append(f"无效 IP: {ip}")
                continue
            try:
                results.append(lookup_ipv6(ip))
            except Exception as exc:
                errors.append(f"{ip}: {exc}")
                logger.warning("GeoIP 查询异常 ip=%s err=%s", ip, exc)

        return ToolResult(
            success=len(errors) == 0,
            output=results,
            error="; ".join(errors) if errors else None,
            metadata={
                "total": len(ips),
                "succeeded": len(results),
                "failed": len(errors),
            },
        )
