from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import random
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agentic_ipv6_geo.common.geo import Point, haversine_km
from agentic_ipv6_geo.common.models import Target
from agentic_ipv6_geo.data.repository import DataRepository, write_jsonl
from agentic_ipv6_geo.environment import GeoAgentEnv
from agentic_ipv6_geo.environment.leakage import scan_for_private_truth
from agentic_ipv6_geo.environment.schemas import AgentAction, PrivateTruth, ToolObservation
from agentic_ipv6_geo.tools.registry import build_methods


TOOL_IDS = ("modugeo", "rdns", "active_triangulation", "passive_ipdb", "whois")


class P0Builder:
    """构建 P0 阶段所需的无泄漏、可回放 Agent 环境数据。"""

    def __init__(self, repo: DataRepository, config: dict[str, Any], output_dir: str | Path):
        self.repo = repo
        self.config = deepcopy(config)
        self.output_dir = Path(output_dir)
        self.dataset_dir = self.output_dir / "dataset"
        self.audit_dir = self.output_dir / "audit"
        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> dict[str, Any]:
        p0_cfg = self.config.get("p0", {})
        seed = int(p0_cfg.get("seed", 42))
        prefix_length = int(p0_cfg.get("split_prefix_length", 48))
        splits = prefix_isolated_split(self.repo.targets, seed=seed, prefix_length=prefix_length)
        train_targets = [target for target in self.repo.targets if splits[target.ip] == "train"]

        offline_config = self._offline_config()
        methods = build_methods(self.repo, offline_config, train_targets)
        tasks, private_truth, replay, replay_rows = self._build_replay(methods, splits, prefix_length)
        oracle = oracle_audit(replay, private_truth, splits)
        sft_rows = self._build_sft_seed(tasks, replay, private_truth, splits)
        grpo_rows = self._build_grpo_prompts(tasks, replay, splits)

        write_jsonl(self.dataset_dir / "tasks.jsonl", tasks.values())
        write_jsonl(self.dataset_dir / "private_truth.jsonl", (truth.to_dict() for truth in private_truth.values()))
        write_jsonl(self.dataset_dir / "tool_replay.jsonl", replay_rows)
        write_jsonl(self.dataset_dir / "sft_seed.jsonl", sft_rows)
        write_jsonl(self.dataset_dir / "grpo_prompts.jsonl", grpo_rows)
        self._write_json(self.dataset_dir / "splits.json", {"prefix_length": prefix_length, "seed": seed, "assignments": splits})
        self._write_json(self.audit_dir / "oracle_audit.json", oracle)

        leakage = self._leakage_audit(tasks, replay_rows, sft_rows, grpo_rows)
        replay_audit = self._replay_audit(tasks, replay, private_truth)
        summary = self._summary(splits, replay, oracle, leakage, replay_audit)
        manifest = self._manifest(summary)
        self._write_json(self.audit_dir / "leakage_audit.json", leakage)
        self._write_json(self.audit_dir / "replay_audit.json", replay_audit)
        self._write_json(self.output_dir / "build_manifest.json", manifest)
        self._write_json(self.output_dir / "p0_summary.json", summary)
        return summary

    def _offline_config(self) -> dict[str, Any]:
        config = deepcopy(self.config)
        config.setdefault("active_probe", {})["allow_live_measurements"] = False
        config["active_probe"]["provider_order"] = ["existing_trace"]
        config.setdefault("rdns", {})["enable_active_collection"] = False
        return config

    def _build_replay(
        self,
        methods: dict[str, Any],
        splits: dict[str, str],
        prefix_length: int,
    ) -> tuple[dict[str, dict], dict[str, PrivateTruth], dict[str, dict[str, ToolObservation]], list[dict]]:
        tasks: dict[str, dict] = {}
        private_truth: dict[str, PrivateTruth] = {}
        replay: dict[str, dict[str, ToolObservation]] = {}
        replay_rows: list[dict] = []
        for target in self.repo.targets:
            task_id = task_id_for(target.ip)
            tasks[task_id] = visible_task(target, task_id, prefix_length)
            private_truth[task_id] = PrivateTruth(task_id=task_id, location=target.location)
            replay[task_id] = {}
            for tool_id in TOOL_IDS:
                result = methods[tool_id].run(target)
                observation = ToolObservation.from_geo_result(task_id, tool_id, result)
                replay[task_id][tool_id] = observation
                replay_rows.append({"task_id": task_id, "split": splits[target.ip], **observation.to_dict()})
        return tasks, private_truth, replay, replay_rows

    def _build_sft_seed(
        self,
        tasks: dict[str, dict],
        replay: dict[str, dict[str, ToolObservation]],
        private_truth: dict[str, PrivateTruth],
        splits: dict[str, str],
    ) -> list[dict]:
        rows = []
        ip_to_split = {task_id_for(ip): split for ip, split in splits.items()}
        for task_id, task in tasks.items():
            if ip_to_split[task_id] != "train":
                continue
            prompt_state = initial_prompt_state(task, replay[task_id], int(self.config.get("p0", {}).get("max_steps", 4)))
            best = best_candidate(replay[task_id], private_truth[task_id])
            if best is None:
                assistant_messages = [{"role": "assistant", "content": json.dumps({"action": "abstain", "arguments": {"granularity": "coordinate"}}, ensure_ascii=False)}]
                teacher = "oracle_abstain"
            elif best.source_tool == "modugeo":
                assistant_messages = [
                    {
                        "role": "assistant",
                        "content": json.dumps({"action": "finalize", "arguments": {"candidate_id": best.candidate_id}}, ensure_ascii=False),
                    }
                ]
                teacher = "oracle_stop"
            else:
                tool_observation = replay[task_id][best.source_tool]
                assistant_messages = [
                    {
                        "role": "assistant",
                        "content": json.dumps({"action": "query_tool", "arguments": {"tool": best.source_tool}}, ensure_ascii=False),
                    },
                    {"role": "tool", "name": best.source_tool, "content": json.dumps(tool_observation.to_dict(), ensure_ascii=False)},
                    {
                        "role": "assistant",
                        "content": json.dumps({"action": "finalize", "arguments": {"candidate_id": best.candidate_id}}, ensure_ascii=False),
                    },
                ]
                teacher = "oracle_single_tool"
            messages = [
                {
                    "role": "system",
                    "content": "你是 IPv6 地理位置推断 Agent。只能调用允许的工具或从可见候选中选择最终位置。",
                },
                {"role": "user", "content": json.dumps(prompt_state, ensure_ascii=False)},
                *assistant_messages,
            ]
            rows.append({"id": f"sft:{task_id}", "split": "train", "messages": messages, "metadata": {"teacher": teacher}})
        return rows

    def _build_grpo_prompts(
        self,
        tasks: dict[str, dict],
        replay: dict[str, dict[str, ToolObservation]],
        splits: dict[str, str],
    ) -> list[dict]:
        ip_to_split = {task_id_for(ip): split for ip, split in splits.items()}
        rows = []
        for task_id, task in tasks.items():
            if ip_to_split[task_id] != "train":
                continue
            prompt_state = initial_prompt_state(task, replay[task_id], int(self.config.get("p0", {}).get("max_steps", 4)))
            rows.append(
                {
                    "task_id": task_id,
                    "split": "train",
                    "prompt": [
                        {
                            "role": "system",
                            "content": "你是 IPv6 地理位置推断 Agent。通过工具调用完成定位，不得访问隐藏真值。",
                        },
                        {"role": "user", "content": json.dumps(prompt_state, ensure_ascii=False)},
                    ],
                    "environment_ref": "geoagent-p0-replay:v1",
                    "max_steps": int(self.config.get("p0", {}).get("max_steps", 4)),
                    "reward_profile": "geoagent_reward_v1",
                }
            )
        return rows

    def _leakage_audit(self, tasks: dict, replay_rows: list[dict], sft_rows: list[dict], grpo_rows: list[dict]) -> dict:
        datasets = {
            "tasks": list(tasks.values()),
            "tool_replay": replay_rows,
            "sft_messages": [row["messages"] for row in sft_rows],
            "grpo_prompts": grpo_rows,
        }
        results = {}
        total_findings = 0
        for name, payload in datasets.items():
            findings = scan_for_private_truth(payload)
            results[name] = {"finding_count": len(findings), "examples": [asdict(item) for item in findings[:10]]}
            total_findings += len(findings)
        return {"passed": total_findings == 0, "total_findings": total_findings, "datasets": results}

    def _replay_audit(
        self,
        tasks: dict[str, dict],
        replay: dict[str, dict[str, ToolObservation]],
        private_truth: dict[str, PrivateTruth],
    ) -> dict:
        task_id = next(
            task_id
            for task_id in sorted(tasks)
            if replay[task_id].get("modugeo") is not None and replay[task_id]["modugeo"].candidate is not None
        )
        env = GeoAgentEnv(tasks, replay, private_truth, max_steps=4)
        first = env.reset(task_id)
        candidate_id = replay[task_id]["modugeo"].candidate.candidate_id  # type: ignore[union-attr]
        final_first = env.step(AgentAction("finalize", {"candidate_id": candidate_id}))
        second = env.reset(task_id)
        final_second = env.step(AgentAction("finalize", {"candidate_id": candidate_id}))
        passed = first == second and final_first == final_second
        return {"passed": passed, "task_id": task_id, "deterministic": passed}

    def _summary(self, splits: dict, replay: dict, oracle: dict, leakage: dict, replay_audit: dict) -> dict:
        status_counts: dict[str, Counter] = {tool: Counter() for tool in TOOL_IDS}
        for observations in replay.values():
            for tool_id, observation in observations.items():
                status_counts[tool_id][observation.status] += 1
        oracle_all = oracle["overall"]
        gate = (
            leakage["passed"]
            and replay_audit["passed"]
            and oracle_all["non_modugeo_improved_count"] > 0
            and oracle_all["non_modugeo_improvement_rate"] >= float(self.config.get("p0", {}).get("oracle_min_improvement_rate", 0.1))
        )
        if gate:
            conclusion = "P0 环境建设通过，当前工具动作空间达到进入定位纠错型 SFT/GRPO 的最低门禁。"
        else:
            conclusion = (
                "P0 基础环境已建成并通过泄漏与回放检查，但当前非 ModuGeo 工具的互补收益不足，"
                "不应直接进入以定位精度提升为目标的 GRPO；可先开展 SFT 与工具适用性/风险控制训练。"
            )
        return {
            "p0_build_complete": leakage["passed"] and replay_audit["passed"],
            "precision_grpo_gate_passed": gate,
            "conclusion": conclusion,
            "target_count": len(self.repo.targets),
            "split_counts": dict(Counter(splits.values())),
            "tool_status_counts": {tool: dict(counts) for tool, counts in status_counts.items()},
            "leakage_audit": leakage,
            "replay_audit": replay_audit,
            "oracle_overall": oracle_all,
            "outputs": {
                "tasks": str(self.dataset_dir / "tasks.jsonl"),
                "private_truth": str(self.dataset_dir / "private_truth.jsonl"),
                "tool_replay": str(self.dataset_dir / "tool_replay.jsonl"),
                "sft_seed": str(self.dataset_dir / "sft_seed.jsonl"),
                "grpo_prompts": str(self.dataset_dir / "grpo_prompts.jsonl"),
                "oracle_audit": str(self.audit_dir / "oracle_audit.json"),
                "build_manifest": str(self.output_dir / "build_manifest.json"),
            },
        }

    def _manifest(self, summary: dict[str, Any]) -> dict[str, Any]:
        files = {}
        for filename in (
            "targets.csv",
            "traces.csv",
            "probes.csv",
            "landmarks.csv",
            "metadata.csv",
            "rdns.csv",
            "modugeo_predictions.csv",
        ):
            path = self.repo.data_dir / filename
            if path.exists():
                files[filename] = {"sha256": _sha256(path), "bytes": path.stat().st_size}
        config_json = json.dumps(self.config, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        return {
            "builder": "P0Builder",
            "schema_version": "p0-v1",
            "input_files": files,
            "config_sha256": hashlib.sha256(config_json).hexdigest(),
            "split_counts": summary["split_counts"],
            "target_count": summary["target_count"],
            "p0_build_complete": summary["p0_build_complete"],
            "precision_grpo_gate_passed": summary["precision_grpo_gate_passed"],
        }

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)


def task_id_for(ip: str) -> str:
    return "geo-" + hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]


def visible_task(target: Target, task_id: str, prefix_length: int) -> dict[str, Any]:
    prefix = str(ipaddress.ip_network(f"{target.ip}/{prefix_length}", strict=False))
    return {
        "task_id": task_id,
        "target": {"ip": target.ip, f"prefix_{prefix_length}": prefix, "asn": target.asn, "operator": target.operator},
        "available_tools": list(TOOL_IDS),
    }


def initial_prompt_state(task: dict[str, Any], observations: dict[str, ToolObservation], max_steps: int) -> dict[str, Any]:
    base = observations.get("modugeo")
    candidates = [base.candidate.to_dict()] if base and base.candidate else []
    return {
        **task,
        "history": [],
        "visible_candidates": candidates,
        "remaining_budget": {"steps": max_steps, "probe_count": 12},
        "done": False,
    }


def prefix_isolated_split(
    targets: list[Target],
    seed: int = 42,
    prefix_length: int = 48,
    ratios: tuple[tuple[str, float], ...] = (("train", 0.7), ("validation", 0.1), ("test", 0.1), ("test_prefix_ood", 0.1)),
) -> dict[str, str]:
    groups: dict[str, list[Target]] = defaultdict(list)
    for target in targets:
        prefix = str(ipaddress.ip_network(f"{target.ip}/{prefix_length}", strict=False))
        groups[prefix].append(target)
    items = list(groups.items())
    random.Random(seed).shuffle(items)
    targets_by_split = {name: len(targets) * ratio for name, ratio in ratios}
    counts = Counter()
    assignments: dict[str, str] = {}
    for _prefix, members in sorted(items, key=lambda item: len(item[1]), reverse=True):
        split = min((name for name, _ratio in ratios), key=lambda name: counts[name] / max(targets_by_split[name], 1))
        for target in members:
            assignments[target.ip] = split
        counts[split] += len(members)
    return assignments


def best_candidate(observations: dict[str, ToolObservation], truth: PrivateTruth):
    truth_point = Point(float(truth.location.lat), float(truth.location.lon))  # type: ignore[arg-type]
    rows = []
    for observation in observations.values():
        candidate = observation.candidate
        if not candidate or not candidate.has_coordinate:
            continue
        point = Point(float(candidate.location.lat), float(candidate.location.lon))  # type: ignore[arg-type]
        rows.append((haversine_km(truth_point, point), candidate))
    return min(rows, key=lambda row: row[0])[1] if rows else None


def oracle_audit(
    replay: dict[str, dict[str, ToolObservation]],
    private_truth: dict[str, PrivateTruth],
    splits: dict[str, str],
) -> dict[str, Any]:
    split_by_task = {task_id_for(ip): split for ip, split in splits.items()}
    rows = []
    for task_id, observations in replay.items():
        truth = private_truth[task_id]
        truth_point = Point(float(truth.location.lat), float(truth.location.lon))  # type: ignore[arg-type]
        errors = {}
        for tool_id, observation in observations.items():
            candidate = observation.candidate
            if candidate and candidate.has_coordinate:
                point = Point(float(candidate.location.lat), float(candidate.location.lon))  # type: ignore[arg-type]
                errors[tool_id] = haversine_km(truth_point, point)
        base_error = errors.get("modugeo")
        if base_error is None:
            continue
        oracle_tool, oracle_error = min(errors.items(), key=lambda item: item[1])
        rows.append(
            {
                "task_id": task_id,
                "split": split_by_task[task_id],
                "modugeo_error_km": base_error,
                "oracle_tool": oracle_tool,
                "oracle_error_km": oracle_error,
                "improvement_km": base_error - oracle_error,
                "tool_errors_km": errors,
            }
        )
    result = {"overall": summarize_oracle(rows), "by_split": {}, "rows": rows}
    for split in sorted({row["split"] for row in rows}):
        result["by_split"][split] = summarize_oracle([row for row in rows if row["split"] == split])
    return result


def summarize_oracle(rows: list[dict]) -> dict[str, Any]:
    if not rows:
        return {"count": 0}
    base = [row["modugeo_error_km"] for row in rows]
    oracle = [row["oracle_error_km"] for row in rows]
    improved = [row for row in rows if row["oracle_tool"] != "modugeo" and row["improvement_km"] > 1e-9]
    return {
        "count": len(rows),
        "modugeo_median_km": _percentile(base, 0.5),
        "modugeo_mean_km": sum(base) / len(base),
        "modugeo_p90_km": _percentile(base, 0.9),
        "oracle_median_km": _percentile(oracle, 0.5),
        "oracle_mean_km": sum(oracle) / len(oracle),
        "oracle_p90_km": _percentile(oracle, 0.9),
        "non_modugeo_improved_count": len(improved),
        "non_modugeo_improvement_rate": len(improved) / len(rows),
        "mean_improvement_km": sum(row["improvement_km"] for row in rows) / len(rows),
        "best_tool_counts": dict(Counter(row["oracle_tool"] for row in rows)),
    }


def _percentile(values: list[float], q: float) -> float:
    rows = sorted(values)
    index = max(0, min(len(rows) - 1, math.ceil(q * len(rows)) - 1))
    return rows[index]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
