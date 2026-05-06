from __future__ import annotations

import re
import csv
from pathlib import Path
from typing import Any

from agentic_ipv6_geo.common.geo import Point, clamp
from agentic_ipv6_geo.common.models import GeoResult, Location, Target
from agentic_ipv6_geo.providers import RDnsCollector
from agentic_ipv6_geo.tools.base import BaseGeoTool


CITY_ALIASES: dict[str, tuple[str, str, Point]] = {
    "bj": ("北京市", "北京", Point(39.9042, 116.4074)),
    "beijing": ("北京市", "北京", Point(39.9042, 116.4074)),
    "pek": ("北京市", "北京", Point(39.9042, 116.4074)),
    "sh": ("上海市", "上海", Point(31.2304, 121.4737)),
    "sha": ("上海市", "上海", Point(31.2304, 121.4737)),
    "shanghai": ("上海市", "上海", Point(31.2304, 121.4737)),
    "gz": ("广东省", "广州", Point(23.1291, 113.2644)),
    "can": ("广东省", "广州", Point(23.1291, 113.2644)),
    "guangzhou": ("广东省", "广州", Point(23.1291, 113.2644)),
    "sz": ("广东省", "深圳", Point(22.5431, 114.0579)),
    "sZX".lower(): ("广东省", "深圳", Point(22.5431, 114.0579)),
    "shenzhen": ("广东省", "深圳", Point(22.5431, 114.0579)),
    "hz": ("浙江省", "杭州", Point(30.2741, 120.1551)),
    "hangzhou": ("浙江省", "杭州", Point(30.2741, 120.1551)),
    "cd": ("四川省", "成都", Point(30.5728, 104.0668)),
    "ctu": ("四川省", "成都", Point(30.5728, 104.0668)),
    "chengdu": ("四川省", "成都", Point(30.5728, 104.0668)),
    "wh": ("湖北省", "武汉", Point(30.5928, 114.3055)),
    "wuhan": ("湖北省", "武汉", Point(30.5928, 114.3055)),
    "xa": ("陕西省", "西安", Point(34.3416, 108.9398)),
    "xian": ("陕西省", "西安", Point(34.3416, 108.9398)),
}


class RDnsGeoTool(BaseGeoTool):
    name = "rDNS"

    def __init__(self, repo, config: dict[str, Any] | None = None):
        super().__init__(repo, config)
        self.min_confidence = float(self.config.get("min_confidence", 0.35))
        self.city_aliases = dict(CITY_ALIASES)
        lexicon_path = self.config.get("lexicon_path")
        if lexicon_path:
            self.city_aliases.update(self._load_lexicon(Path(lexicon_path)))
        self.collector = RDnsCollector(self.config)

    def _run(self, target: Target) -> GeoResult:
        record = self.repo.rdns_for(target.ip)
        if not record:
            record, collect_evidence = self.collector.lookup(target.ip)
        else:
            collect_evidence = {"source": "repository"}
        if not record:
            return GeoResult(
                tool=self.name,
                status="unavailable",
                failure_reason=collect_evidence.get("failure_reason", "缺少目标 IP 的 rDNS hostname"),
                evidence=collect_evidence,
            )

        tokens = self._hostname_tokens(record.hostname)
        hits = []
        for token in tokens:
            if token in self.city_aliases:
                hits.append((token, self.city_aliases[token]))

        if not hits:
            return GeoResult(
                tool=self.name,
                status="unavailable",
                evidence={"hostname": record.hostname, "tokens": tokens, "collection": collect_evidence},
                failure_reason="hostname 未命中地理词典",
            )

        token, (region, city, point) = hits[0]
        confidence = clamp(self.min_confidence + 0.15 * min(len(hits), 2))
        return GeoResult(
            tool=self.name,
            status="ok",
            location=Location(lat=point.lat, lon=point.lon, region=region, city=city),
            granularity="city",
            confidence=confidence,
            evidence={"hostname": record.hostname, "matched_token": token, "tokens": tokens, "collection": collect_evidence},
        )

    @staticmethod
    def _hostname_tokens(hostname: str) -> list[str]:
        normalized = hostname.lower()
        return [token for token in re.split(r"[^a-z0-9]+", normalized) if token]

    @staticmethod
    def _load_lexicon(path: Path) -> dict[str, tuple[str, str, Point]]:
        aliases = {}
        if not path.exists():
            return aliases
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    alias = row["alias"].strip().lower()
                    region = row.get("region", "").strip() or None
                    city = row["city"].strip()
                    lat = float(row["lat"])
                    lon = float(row["lon"])
                except Exception:
                    continue
                aliases[alias] = (region, city, Point(lat, lon))
        return aliases
