from __future__ import annotations

import csv
import ipaddress
import subprocess
import sys
from pathlib import Path
from typing import Any

from agentic_ipv6_geo.common.models import Location, Probe
from agentic_ipv6_geo.data.repository import DataRepository
from agentic_ipv6_geo.providers.common import ProbeCollectionResult, ProbeConstraint


class ScamperTraceProvider:
    """把 scampertrace 的主动探测结果转换为统一 RTT 约束。"""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.scamper_cfg = self.config.get("scamper", {})
        self.active_cfg = self.config.get("active_probe", {})
        self.root = Path(self.scamper_cfg.get("scampertrace_root", "ipgeotools/scampertrace"))
        self.output_dir = Path(self.scamper_cfg.get("output_dir", "outputs/active_probe/scamper"))
        self.allow_live = bool(self.active_cfg.get("allow_live_measurements", False))
        self.timeout_seconds = int(self.scamper_cfg.get("timeout_seconds", 180))
        self.source_filename = str(self.scamper_cfg.get("source_filename", "agentic_ipv6_targets.csv"))

    def collect(self, target_ip: str, repo: DataRepository) -> ProbeCollectionResult:
        cached = self._constraints_from_cache(target_ip, repo)
        if cached:
            return ProbeCollectionResult(
                status="ok",
                constraints=cached,
                evidence={"source": "scamper_cache", "output_dir": str(self.output_dir)},
            )
        if not self.allow_live:
            return ProbeCollectionResult(
                status="unavailable",
                failure_reason="未启用真实 scamper 主动探测，且缓存中没有该目标结果",
                evidence={"allow_live_measurements": False, "output_dir": str(self.output_dir)},
            )
        if not self.root.exists():
            return ProbeCollectionResult(
                status="unavailable",
                failure_reason="scampertrace 根目录不存在",
                evidence={"scampertrace_root": str(self.root)},
            )

        run_result = self._run_scampertrace(target_ip)
        if run_result["status"] != "ok":
            return ProbeCollectionResult(
                status="unavailable",
                failure_reason=run_result["failure_reason"],
                evidence=run_result["evidence"],
            )
        constraints = self._constraints_from_cache(target_ip, repo)
        if not constraints:
            return ProbeCollectionResult(
                status="unavailable",
                failure_reason="scampertrace 已运行，但未解析出有效 RTT 约束",
                evidence=run_result["evidence"],
            )
        return ProbeCollectionResult(status="ok", constraints=constraints, evidence=run_result["evidence"])

    def _run_scampertrace(self, target_ip: str) -> dict[str, Any]:
        input_dir = self.root / "data" / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        target_file = input_dir / self.source_filename
        column = "ipv6" if ipaddress.ip_address(target_ip).version == 6 else "ipv4"
        with target_file.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=[column])
            writer.writeheader()
            writer.writerow({column: target_ip})

        cmd = [
            sys.executable,
            "main.py",
            "--config",
            "config.json",
            "--source-file",
            self.source_filename,
            "--nocontinues",
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.root,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except Exception as exc:
            return {
                "status": "unavailable",
                "failure_reason": f"scampertrace 执行失败: {exc}",
                "evidence": {"command": cmd, "target_file": str(target_file)},
            }
        if proc.returncode != 0:
            return {
                "status": "unavailable",
                "failure_reason": "scampertrace 返回非零退出码",
                "evidence": {
                    "command": cmd,
                    "returncode": proc.returncode,
                    "stderr_tail": proc.stderr[-1000:],
                },
            }
        return {
            "status": "ok",
            "evidence": {
                "command": cmd,
                "target_file": str(target_file),
                "returncode": proc.returncode,
                "stdout_tail": proc.stdout[-1000:],
                "stderr_tail": proc.stderr[-1000:],
                "output_dirs": [str(self.output_dir), str(self.root / "data" / "output")],
                "log_tail": self._latest_log_tail(),
            },
        }

    def _constraints_from_cache(self, target_ip: str, repo: DataRepository) -> list[ProbeConstraint]:
        trace_rows = self._read_trace_rows(target_ip)
        probe_by_id = self._read_probe_rows()
        by_probe: dict[str, list[dict[str, Any]]] = {}
        for row in trace_rows:
            by_probe.setdefault(row["probe_id"], []).append(row)

        constraints = []
        for probe_id, rows in by_probe.items():
            probe = repo.probe_for(probe_id) or probe_by_id.get(probe_id)
            if not probe or not probe.location.has_coordinate:
                continue
            target_hits = [row for row in rows if row.get("hop_ip") == target_ip and row.get("rtt_ms") is not None]
            if target_hits:
                best = min(target_hits, key=lambda item: float(item["rtt_ms"]))
                source = "scamper_target_hit"
            else:
                best = max(rows, key=lambda item: int(item.get("hop_index") or 0))
                source = "scamper_last_visible_hop"
            rtt_ms = best.get("rtt_ms")
            if rtt_ms is None or float(rtt_ms) <= 0:
                continue
            constraints.append(
                ProbeConstraint(
                    probe=probe,
                    rtt_ms=float(rtt_ms),
                    source=source,
                    evidence={
                        "target_ip": target_ip,
                        "probe_id": probe_id,
                        "hop_ip": best.get("hop_ip"),
                        "hop_index": best.get("hop_index"),
                        "measured_at": best.get("measured_at"),
                    },
                )
            )
        return constraints

    def _read_trace_rows(self, target_ip: str) -> list[dict[str, Any]]:
        rows = []
        for path in self._candidate_trace_files(target_ip):
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    normalized = self._normalize_trace_row(row, target_ip)
                    if not normalized:
                        continue
                    rows.append(normalized)
        return rows

    def _candidate_trace_files(self, target_ip: str) -> list[Path]:
        safe_target = target_ip.replace(":", "_")
        native_output_dir = self.root / "data" / "output"
        explicit = [
            self.output_dir / "traces.csv",
            self.output_dir / f"{target_ip}_traces.csv",
            self.output_dir / f"{safe_target}_traces.csv",
            native_output_dir / "traces.csv",
            native_output_dir / f"{target_ip}_traces.csv",
            native_output_dir / f"{safe_target}_traces.csv",
        ]
        generated = []
        for directory in (self.output_dir, native_output_dir):
            if not directory.exists():
                continue
            generated.extend(sorted(directory.glob(f"{Path(self.source_filename).stem}*.csv")))
            generated.extend(sorted(directory.glob("*result.csv")))
        return explicit + [path for path in generated if path not in explicit]

    def _normalize_trace_row(self, row: dict[str, Any], target_ip: str) -> dict[str, Any] | None:
        row_target = row.get("target_ip") or row.get("dst") or row.get("destination") or row.get("target")
        if row_target and str(row_target).strip() != target_ip:
            return None
        hop_ip = row.get("hop_ip") or row.get("addr") or row.get("from") or row.get("hop_addr") or row.get("reply_from")
        if not hop_ip or str(hop_ip).strip() == "*":
            return None
        probe_id = row.get("probe_id") or row.get("src") or row.get("source") or row.get("vp") or "local_scamper"
        hop_index = row.get("hop_index") or row.get("hop") or row.get("ttl") or row.get("hop_no") or 0
        rtt_ms = row.get("rtt_ms") or row.get("rtt") or row.get("rtt1") or row.get("min_rtt")
        try:
            parsed_rtt = float(str(rtt_ms).replace("ms", "").strip()) if rtt_ms not in {None, ""} else None
        except Exception:
            parsed_rtt = None
        try:
            parsed_hop_index = int(float(hop_index or 0))
        except Exception:
            parsed_hop_index = 0
        return {
            "target_ip": target_ip,
            "probe_id": str(probe_id),
            "hop_ip": str(hop_ip).strip(),
            "hop_index": parsed_hop_index,
            "rtt_ms": parsed_rtt,
            "measured_at": row.get("measured_at") or row.get("timestamp") or row.get("time"),
        }

    def _read_probe_rows(self) -> dict[str, Probe]:
        probes = {}
        for path in [self.output_dir / "probes.csv", self.root / "data" / "output" / "probes.csv"]:
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    try:
                        lat = float(row["lat"])
                        lon = float(row["lon"])
                    except Exception:
                        continue
                    probes[row["probe_id"]] = Probe(
                        probe_id=row["probe_id"],
                        location=Location(lat=lat, lon=lon, region=row.get("region") or None, city=row.get("city") or None),
                        operator=row.get("operator") or None,
                        network_type=row.get("network_type") or "scamper",
                    )
        return probes

    def _latest_log_tail(self) -> str:
        logs_dir = self.root / "logs"
        if not logs_dir.exists():
            return ""
        candidates = [path for path in logs_dir.rglob("*") if path.is_file()]
        if not candidates:
            return ""
        latest = max(candidates, key=lambda path: path.stat().st_mtime)
        try:
            return latest.read_text(encoding="utf-8", errors="ignore")[-2000:]
        except Exception:
            return ""
