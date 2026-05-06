from __future__ import annotations

import csv
import ipaddress
import random
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from agentic_ipv6_geo.common.models import (
    ExternalPrediction,
    Landmark,
    Location,
    Metadata,
    Probe,
    RDnsRecord,
    Target,
    TraceHop,
)


def _none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def _float(value: str | None) -> float | None:
    value = _none(value)
    return float(value) if value is not None else None


def _int(value: str | None, default: int = 0) -> int:
    value = _none(value)
    return int(value) if value is not None else default


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


class DataRepository:
    """统一管理实验数据。

    数据加载层只做类型转换和索引构建，不补造缺失事实。定位工具发现依赖字段为空时，
    必须显式返回 unavailable，便于后续评测覆盖率和失败原因可追踪。
    """

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.targets = self._load_targets()
        self.traces = self._load_traces()
        self.probes = self._load_probes()
        self.metadata = self._load_metadata()
        self.rdns = self._load_rdns()
        self.landmarks = self._load_landmarks()
        self.modugeo_predictions = self._load_external_predictions("modugeo_predictions.csv")
        self._traces_by_target = self._index_traces()
        self._rdns_by_ip = {row.ip: row for row in self.rdns}
        self._probe_by_id = {row.probe_id: row for row in self.probes}
        self._landmark_by_ip = {row.ip: row for row in self.landmarks}
        self._modugeo_prediction_by_ip = {row.ip: row for row in self.modugeo_predictions if row.pred_available}

    def _load_targets(self) -> list[Target]:
        rows = []
        for row in _read_csv(self.data_dir / "targets.csv"):
            lat = _float(row.get("lat"))
            lon = _float(row.get("lon"))
            if lat is None or lon is None:
                continue
            rows.append(
                Target(
                    ip=row["ip"].strip(),
                    location=Location(lat=lat, lon=lon, region=_none(row.get("region")), city=_none(row.get("city"))),
                    asn=_none(row.get("asn")),
                    operator=_none(row.get("operator")),
                    observed_at=_none(row.get("observed_at")),
                )
            )
        return rows

    def _load_traces(self) -> list[TraceHop]:
        rows = []
        for row in _read_csv(self.data_dir / "traces.csv"):
            hop_ip = _none(row.get("hop_ip"))
            if not hop_ip or hop_ip == "*":
                continue
            rows.append(
                TraceHop(
                    target_ip=row["target_ip"].strip(),
                    probe_id=row["probe_id"].strip(),
                    hop_ip=hop_ip,
                    hop_index=_int(row.get("hop_index")),
                    rtt_ms=_float(row.get("rtt_ms")),
                    measured_at=_none(row.get("measured_at")),
                )
            )
        return rows

    def _load_probes(self) -> list[Probe]:
        rows = []
        for row in _read_csv(self.data_dir / "probes.csv"):
            lat = _float(row.get("lat"))
            lon = _float(row.get("lon"))
            if lat is None or lon is None:
                continue
            rows.append(
                Probe(
                    probe_id=row["probe_id"].strip(),
                    location=Location(lat=lat, lon=lon, region=_none(row.get("region")), city=_none(row.get("city"))),
                    operator=_none(row.get("operator")),
                    network_type=_none(row.get("network_type")),
                )
            )
        return rows

    def _load_metadata(self) -> list[Metadata]:
        return [
            Metadata(
                prefix=row["prefix"].strip(),
                bgp_prefix=_none(row.get("bgp_prefix")),
                asn=_none(row.get("asn")),
                org=_none(row.get("org")),
                operator=_none(row.get("operator")),
                registered_region=_none(row.get("registered_region")),
                registered_city=_none(row.get("registered_city")),
            )
            for row in _read_csv(self.data_dir / "metadata.csv")
            if _none(row.get("prefix"))
        ]

    def _load_rdns(self) -> list[RDnsRecord]:
        return [
            RDnsRecord(ip=row["ip"].strip(), hostname=row["hostname"].strip(), resolved_at=_none(row.get("resolved_at")))
            for row in _read_csv(self.data_dir / "rdns.csv")
            if _none(row.get("ip")) and _none(row.get("hostname"))
        ]

    def _load_landmarks(self) -> list[Landmark]:
        rows = []
        for row in _read_csv(self.data_dir / "landmarks.csv"):
            lat = _float(row.get("lat"))
            lon = _float(row.get("lon"))
            if lat is None or lon is None:
                continue
            rows.append(
                Landmark(
                    ip=row["ip"].strip(),
                    location=Location(lat=lat, lon=lon, region=_none(row.get("region")), city=_none(row.get("city"))),
                    rtt_ms=_float(row.get("rtt_ms")),
                )
            )
        return rows

    def _load_external_predictions(self, filename: str) -> list[ExternalPrediction]:
        rows = []
        for row in _read_csv(self.data_dir / filename):
            pred_available = str(row.get("pred_available", "1")).strip().lower() not in {"0", "false", "no", ""}
            lat = _float(row.get("pred_lat") or row.get("lat"))
            lon = _float(row.get("pred_lon") or row.get("lon"))
            if lat is None or lon is None:
                continue
            rows.append(
                ExternalPrediction(
                    ip=row["ip"].strip(),
                    location=Location(lat=lat, lon=lon, city=_none(row.get("pred_city"))),
                    confidence=_float(row.get("confidence")),
                    method=_none(row.get("method")),
                    pred_available=pred_available,
                )
            )
        return rows

    def _index_traces(self) -> dict[str, list[TraceHop]]:
        groups: dict[str, list[TraceHop]] = defaultdict(list)
        for hop in self.traces:
            groups[hop.target_ip].append(hop)
        for hops in groups.values():
            hops.sort(key=lambda item: (item.probe_id, item.hop_index))
        return dict(groups)

    def traces_for(self, ip: str) -> list[TraceHop]:
        return self._traces_by_target.get(ip, [])

    def rdns_for(self, ip: str) -> RDnsRecord | None:
        return self._rdns_by_ip.get(ip)

    def probe_for(self, probe_id: str) -> Probe | None:
        return self._probe_by_id.get(probe_id)

    def landmark_for(self, ip: str) -> Landmark | None:
        return self._landmark_by_ip.get(ip)

    def modugeo_prediction_for(self, ip: str) -> ExternalPrediction | None:
        return self._modugeo_prediction_by_ip.get(ip)

    def metadata_for(self, ip: str) -> Metadata | None:
        address = ipaddress.ip_address(ip)
        best: tuple[int, Metadata] | None = None
        for item in self.metadata:
            try:
                network = ipaddress.ip_network(item.prefix, strict=False)
            except ValueError:
                continue
            if address in network and (best is None or network.prefixlen > best[0]):
                best = (network.prefixlen, item)
        return best[1] if best else None

    def split_targets(self, test_ratio: float, seed: int) -> tuple[list[Target], list[Target]]:
        targets = list(self.targets)
        random.Random(seed).shuffle(targets)
        test_count = max(1, int(round(len(targets) * test_ratio))) if targets else 0
        return targets[test_count:], targets[:test_count]


def write_jsonl(path: str | Path, rows: Iterable[dict]) -> None:
    import json

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
