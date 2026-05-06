from __future__ import annotations

import argparse
import ast
import csv
import ipaddress
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROBE_PREFIX_MAP = {
    "2408": "unicom",
    "2409": "mobile",
    "240e": "telecom",
}


def safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        out = float(value)
        if out != out:
            return None
        return out
    except Exception:
        return None


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def infer_probe_name(src_ip: str, worker_node: str = "") -> str:
    node = str(worker_node).lower()
    if "unicom" in node:
        return "unicom"
    if "mobile" in node:
        return "mobile"
    if "telecom" in node:
        return "telecom"
    if "bupt" in node or "cernet" in node:
        return "bupt"
    for prefix, name in PROBE_PREFIX_MAP.items():
        if str(src_ip).startswith(prefix):
            return name
    return "unknown"


def parse_tracelog(log_text: str) -> list[dict[str, Any]]:
    try:
        raw_hops = ast.literal_eval(log_text)
    except Exception:
        return []
    if not isinstance(raw_hops, (list, tuple)):
        return []

    hops = []
    for index, raw in enumerate(raw_hops, start=1):
        text = str(raw).strip()
        if not text or text.startswith("*"):
            continue
        parts = text.split()
        ip = parts[0]
        rtt_ms = None
        for token in parts[1:]:
            token = token.replace("ms", "").replace("msec", "")
            rtt_ms = safe_float(token)
            if rtt_ms is not None:
                break
        hops.append({"hop_index": index, "hop_ip": ip, "rtt_ms": rtt_ms})
    return hops


class PrefixAsnLookup:
    def __init__(self, path: Path):
        self.by_first_hextet: dict[str, list[tuple[ipaddress._BaseNetwork, str]]] = defaultdict(list)
        for row in read_csv(path):
            prefix = row.get("prefix")
            asn = row.get("asn")
            if not prefix or not asn:
                continue
            try:
                network = ipaddress.ip_network(prefix, strict=False)
            except ValueError:
                continue
            first = network.network_address.exploded.split(":")[0]
            self.by_first_hextet[first].append((network, str(asn).strip()))
        for networks in self.by_first_hextet.values():
            networks.sort(key=lambda item: item[0].prefixlen, reverse=True)

    def lookup(self, ip: str) -> tuple[str | None, str | None]:
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return None, None
        first = address.exploded.split(":")[0]
        for network, asn in self.by_first_hextet.get(first, []):
            if address in network:
                return asn, str(network)
        return None, None


class TrustGeoAdapter:
    """将 TrustGeo 数据转成当前系统的统一 CSV。

    适配器只做字段对齐、最长前缀匹配、traceroute 展开和已有预测复用，不改写 TrustGeo
    原始文件。所有生成物写入 GraduatePaper 的 data/trustgeo_processed/。
    """

    def __init__(self, trustgeo_root: str | Path, output_dir: str | Path, max_targets: int | None = None):
        self.root = Path(trustgeo_root)
        self.output_dir = Path(output_dir)
        self.max_targets = max_targets
        self.pred_path = self.root / "output/pfxgeo_v11/predictions.csv"
        self.cbg_pred_path = self.root / "output/ipv6_cbg/predictions.csv"
        self.trace_path = self.root / "data/traceroute/probe_results_0122.csv"
        self.pfx2as_path = self.root / "data/pfx2as_v6_processed.csv"
        self.as_whois_path = self.root / "data/as_whois_cn_parsed_qwen_with_org_with_gps.csv"
        self.city_geo_path = self.root / "data/city_geo.json"
        self.lookup = PrefixAsnLookup(self.pfx2as_path)
        self.asn_geo = self._load_asn_geo()
        self.city_geo = self._load_city_geo()

    def run(self) -> dict[str, Any]:
        predictions = self._load_predictions()
        if self.max_targets:
            predictions = predictions[: self.max_targets]
        target_ips = {row["ip"] for row in predictions}

        targets, metadata = self._build_targets_and_metadata(predictions)
        traces, probe_counter, hop_ips = self._build_traces(target_ips)
        probes = self._build_probes(probe_counter)
        landmarks = self._build_landmarks(hop_ips)
        modugeo_predictions = self._build_modugeo_predictions(predictions)
        rdns: list[dict[str, Any]] = []

        write_csv(self.output_dir / "targets.csv", ["ip", "lat", "lon", "region", "city", "asn", "operator", "observed_at"], targets)
        write_csv(self.output_dir / "metadata.csv", ["prefix", "bgp_prefix", "asn", "org", "operator", "registered_region", "registered_city"], metadata)
        write_csv(self.output_dir / "traces.csv", ["target_ip", "probe_id", "hop_ip", "hop_index", "rtt_ms", "measured_at"], traces)
        write_csv(self.output_dir / "probes.csv", ["probe_id", "lat", "lon", "region", "city", "operator", "network_type"], probes)
        write_csv(self.output_dir / "landmarks.csv", ["ip", "lat", "lon", "region", "city", "rtt_ms"], landmarks)
        write_csv(self.output_dir / "rdns.csv", ["ip", "hostname", "resolved_at"], rdns)
        write_csv(self.output_dir / "modugeo_predictions.csv", ["ip", "pred_lat", "pred_lon", "pred_city", "confidence", "method", "pred_available"], modugeo_predictions)

        summary = {
            "trustgeo_root": str(self.root),
            "output_dir": str(self.output_dir),
            "targets": len(targets),
            "metadata": len(metadata),
            "traces": len(traces),
            "probes": len(probes),
            "landmarks": len(landmarks),
            "rdns": len(rdns),
            "modugeo_predictions": len(modugeo_predictions),
            "note": "TrustGeo 未发现独立 rDNS 数据，rdns.csv 仅写入表头，RDnsGeoTool 会按 unavailable 计入覆盖率。",
        }
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with (self.output_dir / "adapter_summary.json").open("w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)
        return summary

    def _load_predictions(self) -> list[dict[str, str]]:
        rows = []
        for row in read_csv(self.pred_path):
            ip = row.get("ip", "").strip()
            lat = safe_float(row.get("true_lat"))
            lon = safe_float(row.get("true_lon"))
            pred_lat = safe_float(row.get("pred_lat"))
            pred_lon = safe_float(row.get("pred_lon"))
            if not ip or lat is None or lon is None or pred_lat is None or pred_lon is None:
                continue
            rows.append(row)
        return rows

    def _build_targets_and_metadata(self, predictions: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        targets = []
        metadata_by_prefix: dict[str, dict[str, Any]] = {}
        for row in predictions:
            ip = row["ip"].strip()
            asn, prefix = self.lookup.lookup(ip)
            as_info = self.asn_geo.get(asn or "", {})
            region = row.get("true_province") or as_info.get("province") or ""
            city = row.get("true_city") or as_info.get("city") or ""
            targets.append(
                {
                    "ip": ip,
                    "lat": row.get("true_lat"),
                    "lon": row.get("true_lon"),
                    "region": region,
                    "city": city,
                    "asn": f"AS{asn}" if asn else "",
                    "operator": as_info.get("org") or as_info.get("as_name") or "",
                    "observed_at": "",
                }
            )
            if prefix and prefix not in metadata_by_prefix:
                metadata_by_prefix[prefix] = {
                    "prefix": prefix,
                    "bgp_prefix": prefix,
                    "asn": f"AS{asn}" if asn else "",
                    "org": as_info.get("org") or as_info.get("as_name") or "",
                    "operator": as_info.get("org") or as_info.get("as_name") or "",
                    "registered_region": as_info.get("province") or "",
                    "registered_city": as_info.get("city") or "",
                }
        return targets, list(metadata_by_prefix.values())

    def _build_traces(self, target_ips: set[str]) -> tuple[list[dict[str, Any]], dict[str, Counter], set[str]]:
        traces = []
        probe_counter: dict[str, Counter] = defaultdict(Counter)
        hop_ips: set[str] = set()
        for row in read_csv(self.trace_path):
            target_ip = row.get("target_ip", "").strip()
            if target_ip not in target_ips:
                continue
            probe = infer_probe_name(row.get("src_ip", ""), row.get("worker_node", ""))
            if probe == "unknown":
                continue
            src_ip = row.get("src_ip", "").strip()
            if src_ip:
                probe_counter[probe][src_ip] += 1
            for hop in parse_tracelog(row.get("tracelog", "")):
                hop_ips.add(hop["hop_ip"])
                traces.append(
                    {
                        "target_ip": target_ip,
                        "probe_id": probe,
                        "hop_ip": hop["hop_ip"],
                        "hop_index": hop["hop_index"],
                        "rtt_ms": hop["rtt_ms"],
                        "measured_at": row.get("created_at") or row.get("trace_timestamp") or "",
                    }
                )
        return traces, probe_counter, hop_ips

    def _build_probes(self, probe_counter: dict[str, Counter]) -> list[dict[str, Any]]:
        probes = []
        for probe, counter in sorted(probe_counter.items()):
            if not counter:
                continue
            src_ip, _count = counter.most_common(1)[0]
            asn, _prefix = self.lookup.lookup(src_ip)
            info = self.asn_geo.get(asn or "", {})
            lat = safe_float(info.get("lat"))
            lon = safe_float(info.get("lon"))
            if (lat is None or lon is None) and info.get("city") in self.city_geo:
                lat, lon = self.city_geo[info["city"]]
            if lat is None or lon is None:
                continue
            probes.append(
                {
                    "probe_id": probe,
                    "lat": lat,
                    "lon": lon,
                    "region": info.get("province") or "",
                    "city": info.get("city") or "",
                    "operator": info.get("org") or "",
                    "network_type": "trustgeo_probe",
                }
            )
        return probes

    def _build_landmarks(self, hop_ips: set[str]) -> list[dict[str, Any]]:
        rows = []
        seen = set()
        for ip in sorted(hop_ips):
            asn, _prefix = self.lookup.lookup(ip)
            info = self.asn_geo.get(asn or "", {})
            lat = safe_float(info.get("lat"))
            lon = safe_float(info.get("lon"))
            if lat is None or lon is None:
                continue
            key = (ip, lat, lon)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "ip": ip,
                    "lat": lat,
                    "lon": lon,
                    "region": info.get("province") or "",
                    "city": info.get("city") or "",
                    "rtt_ms": "",
                }
            )
        return rows

    def _build_modugeo_predictions(self, predictions: list[dict[str, str]]) -> list[dict[str, Any]]:
        rows = []
        for row in predictions:
            rows.append(
                {
                    "ip": row["ip"],
                    "pred_lat": row.get("pred_lat"),
                    "pred_lon": row.get("pred_lon"),
                    "pred_city": row.get("pred_city") or "",
                    "confidence": row.get("confidence") or "",
                    "method": row.get("method") or "pfxgeo_v11",
                    "pred_available": row.get("pred_available") or "1",
                }
            )
        return rows

    def _load_asn_geo(self) -> dict[str, dict[str, Any]]:
        out = {}
        for row in read_csv(self.as_whois_path):
            asn = str(row.get("ASN", "")).strip()
            if not asn:
                continue
            out[asn] = {
                "as_name": row.get("as-name") or "",
                "org": row.get("org_llm") or row.get("org") or row.get("descr") or "",
                "province": row.get("province") or "",
                "city": row.get("city") or "",
                "lat": row.get("gps_lat") or "",
                "lon": row.get("gps_lon") or "",
            }
        return out

    def _load_city_geo(self) -> dict[str, tuple[float, float]]:
        if not self.city_geo_path.exists():
            return {}
        with self.city_geo_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        out = {}
        for city, info in raw.items():
            lat = safe_float(info.get("lat"))
            lon = safe_float(info.get("lng"))
            if lat is not None and lon is not None:
                out[str(city)] = (lat, lon)
        return out


def main() -> None:
    parser = argparse.ArgumentParser(description="将 TrustGeo 数据适配为 Agentic IPv6 Geo 统一输入")
    parser.add_argument("--trustgeo-root", default="/home/lzj/TrustGeo")
    parser.add_argument("--output-dir", default="data/trustgeo_processed")
    parser.add_argument("--max-targets", type=int, default=None)
    args = parser.parse_args()
    summary = TrustGeoAdapter(args.trustgeo_root, args.output_dir, args.max_targets).run()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
