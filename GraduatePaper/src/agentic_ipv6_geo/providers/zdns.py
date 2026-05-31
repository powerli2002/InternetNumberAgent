from __future__ import annotations

import csv
import ipaddress
import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class ZDnsPtrRow:
    ip: str
    status: str
    raw_status: str
    hostnames: list[str]
    duration_sec: float | None
    resolver: str
    protocol: str
    failure_reason: str
    raw: dict[str, Any]


class ZDnsBulkRDnsCollector:
    """使用 zdns 批量采集 PTR/rDNS 结果。

    采集器只负责网络查询、状态标准化和落盘，不把失败结果伪造成 hostname。
    成功记录会写入兼容 DataRepository 的 rdns.csv；失败记录保留在 full JSONL 中用于复盘。
    """

    def __init__(
        self,
        zdns_bin: str = "zdns",
        resolver: str | None = "1.1.1.1",
        mode: str = "recursive",
        network_timeout: int = 2,
        iteration_timeout: int = 4,
    ):
        self.zdns_bin = zdns_bin
        self.resolver = resolver
        self.mode = mode
        self.network_timeout = network_timeout
        self.iteration_timeout = iteration_timeout

    def collect(
        self,
        ips: list[str],
        output_jsonl: str | Path,
        output_rdns_csv: str | Path,
        summary_path: str | Path,
        *,
        show_progress: bool = True,
        append: bool = False,
        resume: bool = False,
    ) -> dict[str, Any]:
        output_jsonl = Path(output_jsonl)
        output_rdns_csv = Path(output_rdns_csv)
        summary_path = Path(summary_path)
        output_jsonl.parent.mkdir(parents=True, exist_ok=True)
        output_rdns_csv.parent.mkdir(parents=True, exist_ok=True)
        summary_path.parent.mkdir(parents=True, exist_ok=True)

        seen = self._load_seen_ips(output_jsonl) if resume else set()
        query_ips = [ip for ip in ips if ip not in seen]
        total_requested = len(ips)
        total_to_query = len(query_ips)
        if not append and not resume:
            output_jsonl.write_text("", encoding="utf-8")
            self._write_rdns_csv(output_rdns_csv, [], append=False)

        started = time.perf_counter()
        rows: list[ZDnsPtrRow] = []
        if query_ips:
            for row in self._run_zdns(query_ips, show_progress=show_progress):
                rows.append(row)
                self._append_jsonl(output_jsonl, row)
                if row.status == "ok":
                    self._write_rdns_csv(output_rdns_csv, [row], append=True)
                if show_progress:
                    self._render_progress(len(rows), total_to_query, started, row)
            if show_progress:
                print(file=sys.stderr)

        summary = self._summary(rows, total_requested, total_to_query, time.perf_counter() - started, skipped=len(seen))
        with summary_path.open("w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)
        return summary

    def _run_zdns(self, ips: list[str], *, show_progress: bool) -> Iterable[ZDnsPtrRow]:
        zdns_bin = self._resolve_zdns_bin()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as fh:
            for ip in ips:
                fh.write(ip + "\n")
            input_path = Path(fh.name)

        cmd = [
            zdns_bin,
            "PTR",
            f"--network-timeout={self.network_timeout}",
            "--input-file",
            str(input_path),
        ]
        if self.mode == "iterative":
            cmd.extend(["--iterative", f"--iteration-timeout={self.iteration_timeout}"])
        elif self.resolver:
            cmd.append(f"--name-servers={self.resolver}")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                yield self.parse_json_line(line)
            proc.stdout.close()
            code = proc.wait()
            if code != 0:
                raise RuntimeError(f"zdns 进程异常退出，exit_code={code}")
        finally:
            input_path.unlink(missing_ok=True)

    def parse_json_line(self, line: str) -> ZDnsPtrRow:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            return ZDnsPtrRow(
                ip="",
                status="parse_error",
                raw_status="PARSE_ERROR",
                hostnames=[],
                duration_sec=None,
                resolver="",
                protocol="",
                failure_reason=f"zdns 输出不是合法 JSON: {exc}",
                raw={"line": line},
            )

        ip = str(payload.get("name") or "")
        result = payload.get("results", {}).get("PTR", {})
        data = result.get("data") or {}
        answers = data.get("answers") or []
        hostnames = [str(item.get("answer")).rstrip(".") for item in answers if item.get("type") == "PTR" and item.get("answer")]
        raw_status = str(result.get("status") or "UNKNOWN").upper()
        status = self._normalize_status(raw_status, hostnames)
        failure_reason = "" if status == "ok" else str(result.get("error") or self._default_failure_reason(status, raw_status))
        return ZDnsPtrRow(
            ip=ip,
            status=status,
            raw_status=raw_status,
            hostnames=hostnames,
            duration_sec=result.get("duration") if isinstance(result.get("duration"), (int, float)) else None,
            resolver=str(data.get("resolver") or ""),
            protocol=str(data.get("protocol") or ""),
            failure_reason=failure_reason,
            raw=payload,
        )

    @staticmethod
    def extract_ips_from_file(path: str | Path, *, ip_version: int = 6, limit: int | None = None) -> list[str]:
        path = Path(path)
        seen: set[str] = set()
        ips: list[str] = []
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            has_comma = "," in sample
            rows = csv.reader(fh) if has_comma else ((line.strip(),) for line in fh)
            for row in rows:
                for cell in row:
                    value = str(cell).strip()
                    if not value:
                        continue
                    try:
                        address = ipaddress.ip_address(value)
                    except ValueError:
                        continue
                    if address.version != ip_version or not address.is_global:
                        continue
                    normalized = str(address)
                    if normalized in seen:
                        continue
                    seen.add(normalized)
                    ips.append(normalized)
                    break
                if limit is not None and len(ips) >= limit:
                    break
        return ips

    def _resolve_zdns_bin(self) -> str:
        candidate = Path(self.zdns_bin)
        if candidate.exists():
            return str(candidate)
        found = shutil.which(self.zdns_bin)
        if found:
            return found
        raise FileNotFoundError(f"找不到 zdns 可执行文件: {self.zdns_bin}")

    @staticmethod
    def _normalize_status(raw_status: str, hostnames: list[str]) -> str:
        if raw_status == "NOERROR" and hostnames:
            return "ok"
        if raw_status == "NOERROR":
            return "no_answer"
        mapping = {
            "NXDOMAIN": "nxdomain",
            "SERVFAIL": "servfail",
            "TIMEOUT": "timeout",
        }
        return mapping.get(raw_status, "error")

    @staticmethod
    def _default_failure_reason(status: str, raw_status: str) -> str:
        reasons = {
            "no_answer": "查询成功但没有 PTR answer",
            "nxdomain": "反向解析域名不存在",
            "servfail": "上游权威链路返回 SERVFAIL",
            "timeout": "查询超时",
        }
        return reasons.get(status, f"zdns 返回状态 {raw_status}")

    @staticmethod
    def _load_seen_ips(path: Path) -> set[str]:
        if not path.exists():
            return set()
        seen = set()
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                ip = row.get("ip") or row.get("name")
                if ip:
                    seen.add(str(ip))
        return seen

    @staticmethod
    def _append_jsonl(path: Path, row: ZDnsPtrRow) -> None:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "ip": row.ip,
                        "status": row.status,
                        "raw_status": row.raw_status,
                        "hostnames": row.hostnames,
                        "duration_sec": row.duration_sec,
                        "resolver": row.resolver,
                        "protocol": row.protocol,
                        "failure_reason": row.failure_reason,
                        "raw": row.raw,
                    },
                    ensure_ascii=False,
                    default=str,
                )
                + "\n"
            )

    @staticmethod
    def _write_rdns_csv(path: Path, rows: list[ZDnsPtrRow], *, append: bool) -> None:
        exists = path.exists()
        mode = "a" if append else "w"
        with path.open(mode, encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["ip", "hostname", "resolved_at", "source", "status", "failure_reason"],
            )
            if not append or not exists:
                writer.writeheader()
            now = datetime.now(timezone.utc).isoformat()
            for row in rows:
                for hostname in row.hostnames:
                    writer.writerow(
                        {
                            "ip": row.ip,
                            "hostname": hostname,
                            "resolved_at": now,
                            "source": "zdns",
                            "status": row.status,
                            "failure_reason": row.failure_reason,
                        }
                    )

    @staticmethod
    def _summary(rows: list[ZDnsPtrRow], total_requested: int, total_queried: int, elapsed_sec: float, *, skipped: int) -> dict[str, Any]:
        status_counts: dict[str, int] = {}
        for row in rows:
            status_counts[row.status] = status_counts.get(row.status, 0) + 1
        ok_count = status_counts.get("ok", 0)
        return {
            "total_requested": total_requested,
            "skipped_by_resume": skipped,
            "total_queried": total_queried,
            "elapsed_sec": elapsed_sec,
            "throughput_qps": total_queried / elapsed_sec if elapsed_sec > 0 else None,
            "ok_count": ok_count,
            "ptr_result_rate": ok_count / total_queried if total_queried else 0,
            "status_counts": status_counts,
        }

    @staticmethod
    def _render_progress(done: int, total: int, started: float, row: ZDnsPtrRow) -> None:
        width = 28
        ratio = done / total if total else 1.0
        filled = min(width, int(width * ratio))
        elapsed = time.perf_counter() - started
        qps = done / elapsed if elapsed > 0 else 0
        bar = "#" * filled + "-" * (width - filled)
        print(
            f"\r[{bar}] {done}/{total} {ratio:6.2%} {qps:6.2f} qps last={row.status}:{row.ip}",
            end="",
            file=sys.stderr,
            flush=True,
        )
