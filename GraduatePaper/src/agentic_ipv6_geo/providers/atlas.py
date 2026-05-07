from __future__ import annotations

import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
from typing import Any

from agentic_ipv6_geo.common.models import Location, Probe
from agentic_ipv6_geo.data.repository import DataRepository
from agentic_ipv6_geo.providers.common import ProbeCollectionResult, ProbeConstraint


class RipeAtlasProvider:
    """RIPE Atlas 主动 traceroute provider。

    该类只负责创建/读取测量和解析 RTT 约束，不直接做地理定位。
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.service_cfg = self.config.get("external_services", {}).get("ripe_atlas", {})
        self.atlas_cfg = self.config.get("ripe_atlas", {})
        self.active_cfg = self.config.get("active_probe", {})
        self.base_url = str(self.service_cfg.get("base_url", "https://atlas.ripe.net/api/v2")).rstrip("/")
        self.timeout = int(self.service_cfg.get("timeout_seconds", 30))
        self.allow_live = bool(self.active_cfg.get("allow_live_measurements", False))
        self.max_targets_per_run = int(self.active_cfg.get("max_targets_per_run", 20))
        self.max_probes_per_target = int(self.active_cfg.get("max_probes_per_target", 3))
        self.max_retries = int(self.atlas_cfg.get("max_retries", 2))
        self.cache_dir = Path(self.active_cfg.get("cache_dir", "outputs/active_probe/cache"))
        self.budget_path = self.cache_dir / "ripe_atlas_budget.json"
        self._probe_cache: dict[str, Probe | None] = {}

    def collect(self, target_ip: str, repo: DataRepository) -> ProbeCollectionResult:
        if not self.allow_live:
            return ProbeCollectionResult(
                status="unavailable",
                failure_reason="未启用 RIPE Atlas 真实 measurement 创建",
                evidence={"allow_live_measurements": False},
            )
        auth = self._auth_header()
        if not auth:
            return ProbeCollectionResult(
                status="unavailable",
                failure_reason="缺少 RIPE Atlas 认证环境变量",
                evidence={"api_key_env": self.service_cfg.get("api_key_env"), "auth_header_env": self.service_cfg.get("auth_header_env")},
            )
        budget = self._reserve_budget(target_ip)
        if budget["status"] != "ok":
            return ProbeCollectionResult(status="unavailable", failure_reason=budget["failure_reason"], evidence=budget["evidence"])

        payload = self._traceroute_payload(target_ip)
        created = self._request_json("POST", "/measurements/", payload=payload, auth=auth)
        if created["status"] != "ok":
            return ProbeCollectionResult(status="unavailable", failure_reason=created["failure_reason"], evidence=created["evidence"])
        measurement_ids = created["data"].get("measurements") or []
        if not measurement_ids:
            return ProbeCollectionResult(status="unavailable", failure_reason="Atlas 未返回 measurement id", evidence=created["data"])

        measurement_id = measurement_ids[0]
        latest = self._poll_latest(measurement_id, auth)
        if latest["status"] != "ok":
            return ProbeCollectionResult(status="unavailable", failure_reason=latest["failure_reason"], evidence=latest["evidence"])
        constraints = self._constraints_from_results(target_ip, latest["data"], repo, auth)
        if not constraints:
            return ProbeCollectionResult(
                status="unavailable",
                failure_reason="Atlas 结果中未解析出有效 RTT 约束",
                evidence={"measurement_id": measurement_id},
            )
        return ProbeCollectionResult(status="ok", constraints=constraints, evidence={"measurement_id": measurement_id, "source": "ripe_atlas"})

    def _traceroute_payload(self, target_ip: str) -> dict[str, Any]:
        probe_selection = self._china_probe_selection()
        tags_include = self.atlas_cfg.get("tags_include") or ["system-ipv6-works"]
        probes = []
        for item in probe_selection:
            row = dict(item)
            if tags_include and "tags_include" not in row:
                row["tags_include"] = tags_include
            probes.append(row)
        return {
            "definitions": [
                {
                    "target": target_ip,
                    "description": self.atlas_cfg.get("measurement_description", "agentic-ipv6-geo traceroute"),
                    "type": "traceroute",
                    "af": 6,
                    "protocol": self.atlas_cfg.get("protocol", "ICMP"),
                    "is_oneoff": True,
                    "resolve_on_probe": True,
                }
            ],
            "probes": probes,
        }

    def _china_probe_selection(self) -> list[dict[str, Any]]:
        requested = max(1, min(3, self.max_probes_per_target))
        return [{"requested": requested, "type": "countries", "value": "CN"}]

    def _poll_latest(self, measurement_id: int, auth: str) -> dict[str, Any]:
        attempts = int(self.atlas_cfg.get("max_poll_attempts", 20))
        interval = int(self.atlas_cfg.get("poll_interval_seconds", 15))
        last_error: dict[str, Any] | None = None
        for _ in range(attempts):
            result = self._request_json("GET", f"/measurements/{measurement_id}/latest/", auth=auth)
            if result["status"] == "ok" and result["data"]:
                return result
            last_error = result
            time.sleep(interval)
        return {
            "status": "unavailable",
            "failure_reason": "等待 RIPE Atlas measurement 结果超时",
            "evidence": {"measurement_id": measurement_id, "last_error": last_error},
        }

    def _constraints_from_results(self, target_ip: str, data: Any, repo: DataRepository, auth: str | None = None) -> list[ProbeConstraint]:
        raw_results = self._flatten_latest(data)
        constraints = []
        for result in raw_results:
            probe_id = str(result.get("prb_id") or result.get("probe_id") or "")
            if not probe_id:
                continue
            probe = repo.probe_for(probe_id) or self._probe_from_result(probe_id, result) or self._probe_from_api(probe_id, auth)
            if not probe or not probe.location.has_coordinate:
                continue
            rtt_ms, hop_evidence = self._best_rtt(result, target_ip)
            if rtt_ms is None or rtt_ms <= 0:
                continue
            constraints.append(
                ProbeConstraint(
                    probe=probe,
                    rtt_ms=rtt_ms,
                    source="ripe_atlas",
                    evidence={"probe_id": probe_id, "target_ip": target_ip, **hop_evidence},
                )
            )
        return constraints

    def _flatten_latest(self, data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            rows = []
            for value in data.values():
                if isinstance(value, list):
                    rows.extend(item for item in value if isinstance(item, dict))
                elif isinstance(value, dict):
                    rows.append(value)
            return rows
        return []

    def _probe_from_result(self, probe_id: str, result: dict[str, Any]) -> Probe | None:
        lat = result.get("probe_lat") or result.get("lat")
        lon = result.get("probe_lon") or result.get("lon")
        if lat is None or lon is None:
            return None
        try:
            return Probe(probe_id=probe_id, location=Location(lat=float(lat), lon=float(lon)), network_type="ripe_atlas")
        except Exception:
            return None

    def _probe_from_api(self, probe_id: str, auth: str | None = None) -> Probe | None:
        if probe_id in self._probe_cache:
            return self._probe_cache[probe_id]
        result = self._request_json("GET", f"/probes/{probe_id}/", auth=auth)
        if result["status"] != "ok":
            self._probe_cache[probe_id] = None
            return None
        data = result["data"]
        geometry = data.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        if len(coordinates) < 2:
            self._probe_cache[probe_id] = None
            return None
        try:
            probe = Probe(
                probe_id=probe_id,
                location=Location(lat=float(coordinates[1]), lon=float(coordinates[0])),
                operator=str(data.get("country_code") or "CN"),
                network_type="ripe_atlas",
            )
        except Exception:
            probe = None
        self._probe_cache[probe_id] = probe
        return probe

    def _best_rtt(self, result: dict[str, Any], target_ip: str) -> tuple[float | None, dict[str, Any]]:
        best_target: float | None = None
        last_visible: tuple[int, str | None, float] | None = None
        for hop in result.get("result") or []:
            hop_index = int(hop.get("hop") or 0) if isinstance(hop, dict) else 0
            for attempt in hop.get("result") or []:
                if not isinstance(attempt, dict) or "rtt" not in attempt:
                    continue
                try:
                    rtt = float(attempt["rtt"])
                except Exception:
                    continue
                hop_ip = attempt.get("from")
                if hop_ip:
                    last_visible = (hop_index, hop_ip, rtt)
                if hop_ip == target_ip:
                    best_target = rtt if best_target is None else min(best_target, rtt)
        if best_target is not None:
            return best_target, {"rtt_source": "target_hit"}
        if last_visible is not None:
            hop_index, hop_ip, rtt = last_visible
            return rtt, {"rtt_source": "last_visible_hop", "hop_index": hop_index, "hop_ip": hop_ip}
        return None, {"rtt_source": "none"}

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None, auth: str | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        last_error: dict[str, Any] | None = None
        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(
                self.base_url + path,
                data=body,
                method=method,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
            if auth:
                request.add_header("Authorization", auth)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return {"status": "ok", "data": json.loads(response.read().decode("utf-8"))}
            except urllib.error.HTTPError as exc:
                last_error = {"reason": exc.reason, "attempt": attempt, "code": exc.code}
                if exc.code in {400, 401, 403, 404}:
                    break
            except Exception as exc:
                last_error = {"reason": str(exc), "attempt": attempt}
            if attempt < self.max_retries:
                time.sleep(min(2 ** attempt, 5))
        if last_error and "code" in last_error:
            return {"status": "unavailable", "failure_reason": f"Atlas HTTP {last_error['code']}", "evidence": last_error}
        return {"status": "unavailable", "failure_reason": "Atlas 请求失败", "evidence": last_error or {}}

    def _reserve_budget(self, target_ip: str) -> dict[str, Any]:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        budget = self._load_budget()
        targets = set(budget.get("targets", []))
        if target_ip not in targets and len(targets) >= self.max_targets_per_run:
            return {
                "status": "unavailable",
                "failure_reason": f"RIPE Atlas 本批目标数已达到上限 {self.max_targets_per_run}",
                "evidence": {"target_count": len(targets), "max_targets_per_run": self.max_targets_per_run},
            }
        targets.add(target_ip)
        budget["targets"] = sorted(targets)
        budget["max_targets_per_run"] = self.max_targets_per_run
        budget["max_probes_per_target"] = min(3, self.max_probes_per_target)
        with self.budget_path.open("w", encoding="utf-8") as fh:
            json.dump(budget, fh, ensure_ascii=False, indent=2)
        return {"status": "ok", "evidence": {"target_count": len(targets), "budget_path": str(self.budget_path)}}

    def _load_budget(self) -> dict[str, Any]:
        if not self.budget_path.exists():
            return {"targets": []}
        try:
            with self.budget_path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {"targets": []}

    def _auth_header(self) -> str | None:
        if self.service_cfg.get("auth_header"):
            return str(self.service_cfg["auth_header"])
        if self.service_cfg.get("api_key"):
            return f"Key {self.service_cfg['api_key']}"
        auth_header_env = self.service_cfg.get("auth_header_env", "RIPE_ATLAS_AUTH_HEADER")
        api_key_env = self.service_cfg.get("api_key_env", "RIPE_ATLAS_API_KEY")
        if auth_header_env and os.environ.get(str(auth_header_env)):
            return os.environ[str(auth_header_env)]
        if api_key_env and os.environ.get(str(api_key_env)):
            return f"Key {os.environ[str(api_key_env)]}"
        return None
