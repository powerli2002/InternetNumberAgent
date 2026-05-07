from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Callable

from agentic_ipv6_geo.common.catalog import display_experiment_name
from agentic_ipv6_geo.common.geo import Point, haversine_km
from agentic_ipv6_geo.common.logger import JsonlLogger
from agentic_ipv6_geo.common.models import GeoResult, Target
from agentic_ipv6_geo.data.repository import DataRepository, write_jsonl
from agentic_ipv6_geo.evaluation.metrics import summarize_errors
from agentic_ipv6_geo.scheduler import ContextualBanditScheduler, OfflineRewardPolicyScheduler, QwenToolUseScheduler, RuleAgentScheduler
from agentic_ipv6_geo.tools.registry import build_methods


class Evaluator:
    def __init__(self, repo: DataRepository, config: dict, output_dir: str | Path = "outputs"):
        self.repo = repo
        self.config = config
        self.output_dir = Path(output_dir)
        self.metrics_dir = self.output_dir / "metrics"
        self.pred_dir = self.output_dir / "predictions"
        self.metrics_dir.mkdir(parents=True, exist_ok=True)
        self.pred_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> dict[str, dict]:
        split_cfg = self.config.get("split", {})
        train_targets, test_targets = self.repo.split_targets(
            test_ratio=float(split_cfg.get("test_ratio", 0.3)),
            seed=int(split_cfg.get("seed", 42)),
        )
        tools = self._build_tools(train_targets)
        experiments = self._experiments(tools)
        all_metrics = {}
        all_rows = {}
        for name, runner in experiments.items():
            rows, metrics = self._evaluate_runner(name, test_targets, runner)
            all_metrics[name] = metrics
            all_rows[name] = rows
            write_jsonl(self.pred_dir / f"{name}.jsonl", rows)
        self._write_metrics(all_metrics, all_rows)
        return all_metrics

    def _build_tools(self, train_targets: list[Target]) -> dict:
        tools = build_methods(self.repo, self.config, train_targets)
        tools["train_targets"] = train_targets
        return tools

    def _experiments(self, tools: dict) -> dict[str, Callable[[Target], GeoResult]]:
        def fuse_subset(target: Target, names: list[str]) -> GeoResult:
            results = [tools[name].run(target) for name in names]
            return tools["fusion"].run(results)

        scheduler = RuleAgentScheduler(
            tools["modugeo"],
            tools["rdns"],
            tools["active_triangulation"],
            tools["whois"],
            tools.get("passive_ipdb"),
            tools["fusion"],
            self.config.get("scheduler"),
            JsonlLogger(self.config.get("log_path")),
        )
        bandit = ContextualBanditScheduler(
            tools["modugeo"],
            tools["rdns"],
            tools["active_triangulation"],
            tools["whois"],
            tools["fusion"],
            self.config.get("bandit"),
            JsonlLogger(self.config.get("log_path")),
        )
        bandit.fit(tools["train_targets"])
        qwen = QwenToolUseScheduler(
            tools["modugeo"],
            tools["rdns"],
            tools["active_triangulation"],
            tools["whois"],
            tools["passive_ipdb"],
            tools["fusion"],
            self.config.get("llm_baseline"),
            self.config.get("external_services", {}).get("qwen"),
            JsonlLogger(self.config.get("log_path")),
        )
        rl_policy = OfflineRewardPolicyScheduler(
            tools["modugeo"],
            tools["rdns"],
            tools["active_triangulation"],
            tools["whois"],
            tools["passive_ipdb"],
            tools["fusion"],
            self.config.get("rl"),
            JsonlLogger(self.config.get("log_path")),
        )
        rl_policy.fit(tools["train_targets"])

        return {
            "single_modugeo": tools["modugeo"].run,
            "single_rdns": tools["rdns"].run,
            "single_active_triangulation": tools["active_triangulation"].run,
            "single_passive_ipdb": tools["passive_ipdb"].run,
            "fusion_modugeo_rdns": lambda target: fuse_subset(target, ["modugeo", "rdns", "whois"]),
            "fusion_modugeo_active": lambda target: fuse_subset(target, ["modugeo", "active_triangulation", "whois"]),
            "fusion_modugeo_passive": lambda target: fuse_subset(target, ["modugeo", "passive_ipdb", "whois"]),
            "fusion_all": lambda target: fuse_subset(target, ["modugeo", "rdns", "active_triangulation", "passive_ipdb", "whois"]),
            "scheduler_rule": scheduler.run,
            "scheduler_bandit": bandit.run,
            "scheduler_qwen_baseline": qwen.run,
            "scheduler_rl_policy": rl_policy.run,
        }

    def _evaluate_runner(self, name: str, targets: list[Target], runner: Callable[[Target], GeoResult]) -> tuple[list[dict], dict]:
        rows = []
        errors = []
        tool_calls = []
        probe_counts = []
        covered = 0
        for target in targets:
            result = runner(target)
            error = None
            if result.is_ok() and result.location and result.location.has_coordinate:
                truth = Point(target.location.lat, target.location.lon)  # type: ignore[arg-type]
                pred = Point(result.location.lat, result.location.lon)  # type: ignore[arg-type]
                error = haversine_km(truth, pred)
                errors.append(error)
                covered += 1
            tool_calls.append(result.cost.tool_calls)
            probe_counts.append(result.cost.probe_count)
            rows.append(
                {
                    "experiment": name,
                    "target_ip": target.ip,
                    "truth": target.location,
                    "result": result.to_dict(),
                    "error_km": error,
                }
            )
        metrics = summarize_errors(errors, covered, len(targets), tool_calls, probe_counts)
        metrics["Calibration"] = self._calibration(rows)
        return rows, metrics

    def _calibration(self, rows: list[dict]) -> dict:
        valid = [row for row in rows if row["error_km"] is not None]
        if len(valid) < 2:
            return {"high_conf_mean_error": None, "low_conf_mean_error": None}
        valid.sort(key=lambda row: row["result"]["confidence"])
        mid = len(valid) // 2
        low = valid[:mid]
        high = valid[mid:]
        return {
            "high_conf_mean_error": sum(row["error_km"] for row in high) / len(high),
            "low_conf_mean_error": sum(row["error_km"] for row in low) / len(low),
        }

    def _write_metrics(self, metrics: dict[str, dict], rows_by_experiment: dict[str, list[dict]]) -> None:
        json_path = self.metrics_dir / "summary.json"
        with json_path.open("w", encoding="utf-8") as fh:
            json.dump(metrics, fh, ensure_ascii=False, indent=2)

        csv_path = self.metrics_dir / "summary.csv"
        fieldnames = ["experiment", "experiment_name", "Median", "Mean", "P90", "Coverage", "AvgToolCalls", "AvgProbeCost"]
        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for experiment, row in metrics.items():
                writer.writerow(
                    {
                        "experiment": experiment,
                        "experiment_name": display_experiment_name(experiment),
                        **{key: row.get(key) for key in fieldnames[2:]},
                    }
                )

        self._write_analysis_artifacts(metrics, rows_by_experiment)

    def _write_analysis_artifacts(self, metrics: dict[str, dict], rows_by_experiment: dict[str, list[dict]]) -> None:
        figures_dir = self.output_dir / "figures"
        figures_dir.mkdir(parents=True, exist_ok=True)
        frontier_path = figures_dir / "cost_accuracy_frontier.csv"
        with frontier_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "experiment",
                    "experiment_name",
                    "mean_error_km",
                    "median_error_km",
                    "avg_tool_calls",
                    "avg_probe_cost",
                    "coverage",
                ],
            )
            writer.writeheader()
            for experiment, row in metrics.items():
                writer.writerow(
                    {
                        "experiment": experiment,
                        "experiment_name": display_experiment_name(experiment),
                        "mean_error_km": row.get("Mean"),
                        "median_error_km": row.get("Median"),
                        "avg_tool_calls": row.get("AvgToolCalls"),
                        "avg_probe_cost": row.get("AvgProbeCost"),
                        "coverage": row.get("Coverage"),
                    }
                )

        for experiment, rows in rows_by_experiment.items():
            errors = sorted(row["error_km"] for row in rows if row["error_km"] is not None)
            cdf_path = figures_dir / f"{experiment}_error_cdf.csv"
            with cdf_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=["error_km", "cdf"])
                writer.writeheader()
                total = len(errors)
                for index, error in enumerate(errors, start=1):
                    writer.writerow({"error_km": error, "cdf": index / total if total else 0})

        group_metrics = self._group_metrics(rows_by_experiment)
        with (self.metrics_dir / "group_metrics.json").open("w", encoding="utf-8") as fh:
            json.dump(group_metrics, fh, ensure_ascii=False, indent=2)

        self._write_rl_artifacts(rows_by_experiment)
        self._write_tool_selection_sft(rows_by_experiment)

        report_path = self.output_dir / "实验报告.md"
        with report_path.open("w", encoding="utf-8") as fh:
            fh.write("# Agentic IPv6 Geolocation 实验报告\n\n")
            fh.write("## 总体指标\n\n")
            fh.write("| 实验 | Median km | Mean km | P90 km | Coverage | AvgToolCalls | AvgProbeCost |\n")
            fh.write("| --- | ---: | ---: | ---: | ---: | ---: | ---: |\n")
            for experiment, row in metrics.items():
                fh.write(
                    f"| {display_experiment_name(experiment)} | {self._fmt(row.get('Median'))} | {self._fmt(row.get('Mean'))} | "
                    f"{self._fmt(row.get('P90'))} | {self._fmt(row.get('Coverage'))} | "
                    f"{self._fmt(row.get('AvgToolCalls'))} | {self._fmt(row.get('AvgProbeCost'))} |\n"
                )
            fh.write("\n## 输出文件\n\n")
            fh.write(f"- 成本-精度前沿：`{frontier_path}`\n")
            fh.write(f"- 分组指标：`{self.metrics_dir / 'group_metrics.json'}`\n")
            fh.write(f"- 各实验预测：`{self.pred_dir}`\n")
            fh.write(f"- RL 轨迹：`{Path(self.config.get('rl', {}).get('trajectory_dir', 'outputs/rl/trajectories'))}`\n")

    def _group_metrics(self, rows_by_experiment: dict[str, list[dict]]) -> dict:
        from agentic_ipv6_geo.evaluation.metrics import summarize_errors

        grouped = {}
        for experiment, rows in rows_by_experiment.items():
            buckets: dict[str, list[dict]] = {}
            for row in rows:
                truth = row["truth"]
                key = truth.region or truth.city or "unknown"
                buckets.setdefault(key, []).append(row)
            grouped[experiment] = {}
            for key, items in buckets.items():
                errors = [row["error_km"] for row in items if row["error_km"] is not None]
                tool_calls = [row["result"]["cost"]["tool_calls"] for row in items]
                probe_counts = [row["result"]["cost"]["probe_count"] for row in items]
                grouped[experiment][key] = summarize_errors(errors, len(errors), len(items), tool_calls, probe_counts)
        return grouped

    def _write_rl_artifacts(self, rows_by_experiment: dict[str, list[dict]]) -> None:
        rl_cfg = self.config.get("rl", {})
        trajectory_dir = Path(rl_cfg.get("trajectory_dir", self.output_dir / "rl" / "trajectories"))
        trajectory_dir.mkdir(parents=True, exist_ok=True)
        reward_summary = {}
        for experiment, rows in rows_by_experiment.items():
            path = trajectory_dir / f"{experiment}.jsonl"
            rewards = []
            with path.open("w", encoding="utf-8") as fh:
                for row in rows:
                    reward = self._trajectory_reward(row)
                    rewards.append(reward)
                    fh.write(json.dumps(self._trajectory_row(row, reward), ensure_ascii=False, default=str) + "\n")
            reward_summary[experiment] = {
                "count": len(rewards),
                "mean_reward": sum(rewards) / len(rewards) if rewards else None,
                "max_reward": max(rewards) if rewards else None,
                "min_reward": min(rewards) if rewards else None,
            }
        summary_path = Path(rl_cfg.get("reward_summary_path", self.output_dir / "rl" / "reward_summary.json"))
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with summary_path.open("w", encoding="utf-8") as fh:
            json.dump(reward_summary, fh, ensure_ascii=False, indent=2)
        comparison_path = Path(rl_cfg.get("offline_reward_comparison_path", self.output_dir / "rl" / "offline_reward_comparison.json"))
        comparison_path.parent.mkdir(parents=True, exist_ok=True)
        with comparison_path.open("w", encoding="utf-8") as fh:
            json.dump(reward_summary, fh, ensure_ascii=False, indent=2)

    def _write_tool_selection_sft(self, rows_by_experiment: dict[str, list[dict]]) -> None:
        action_by_experiment = {
            "single_modugeo": "stop",
            "single_rdns": "rdns",
            "single_active_triangulation": "active",
            "single_passive_ipdb": "passive",
            "fusion_all": "all",
        }
        grouped: dict[str, list[tuple[str, dict, float]]] = {}
        for experiment, rows in rows_by_experiment.items():
            action = action_by_experiment.get(experiment)
            if not action:
                continue
            for row in rows:
                grouped.setdefault(row["target_ip"], []).append((action, row, self._trajectory_reward(row)))

        rl_cfg = self.config.get("rl", {})
        sft_path = Path(rl_cfg.get("sft_dataset_path", self.output_dir / "rl" / "sft" / "tool_selection_sft.jsonl"))
        sft_path.parent.mkdir(parents=True, exist_ok=True)
        with sft_path.open("w", encoding="utf-8") as fh:
            for target_ip, candidates in sorted(grouped.items()):
                action, row, reward = max(candidates, key=lambda item: item[2])
                sample = {
                    "messages": [
                        {"role": "system", "content": "你只能从 stop, rdns, active, passive, all 中选择一个 IPv6 定位工具动作，并返回 JSON。"},
                        {"role": "user", "content": json.dumps(self._sft_state(row, candidates), ensure_ascii=False)},
                        {"role": "assistant", "content": json.dumps({"action": action}, ensure_ascii=False)},
                    ],
                    "target_ip": target_ip,
                    "chosen_action": action,
                    "chosen_reward": reward,
                    "candidate_rewards": {candidate_action: candidate_reward for candidate_action, _candidate_row, candidate_reward in candidates},
                }
                fh.write(json.dumps(sample, ensure_ascii=False, default=str) + "\n")

    def _sft_state(self, row: dict, candidates: list[tuple[str, dict, float]]) -> dict:
        result = row["result"]
        return {
            "target_ip": row["target_ip"],
            "truth_region": row["truth"].region,
            "truth_city": row["truth"].city,
            "available_actions": ["stop", "rdns", "active", "passive", "all"],
            "candidate_status": {action: candidate_row["result"]["status"] for action, candidate_row, _reward in candidates},
            "candidate_cost": {action: candidate_row["result"].get("cost", {}) for action, candidate_row, _reward in candidates},
            "current_result_confidence": result.get("confidence"),
        }

    def _trajectory_row(self, row: dict, reward: float) -> dict:
        result = row["result"]
        scheduler = result.get("evidence", {}).get("scheduler", {})
        return {
            "state": {
                "target_ip": row["target_ip"],
                "truth_region": row["truth"].region,
                "truth_city": row["truth"].city,
                "experiment": row["experiment"],
            },
            "available_tools": ["modugeo", "rdns", "active_triangulation", "passive_ipdb", "whois", "fusion", "stop"],
            "action": scheduler.get("selected_action") or scheduler.get("type") or row["experiment"],
            "observation": result,
            "cost": result.get("cost", {}),
            "final_result": result,
            "error_km": row["error_km"],
            "reward": reward,
            "done": True,
        }

    def _trajectory_reward(self, row: dict) -> float:
        reward_cfg = self.config.get("rl", {}).get("reward", {})
        result = row["result"]
        if row["error_km"] is None:
            return -float(reward_cfg.get("invalid_action_penalty", 1000.0))
        conflict = max((item.get("distance_km", 0.0) for item in result.get("evidence", {}).get("conflicts", [])), default=0.0)
        cost = result.get("cost", {})
        return (
            -float(row["error_km"])
            - float(reward_cfg.get("tool_cost_weight", 10.0)) * float(cost.get("tool_calls", 0.0))
            - float(reward_cfg.get("probe_cost_weight", 2.0)) * float(cost.get("probe_count", 0.0))
            - float(reward_cfg.get("conflict_weight", 0.05)) * conflict
            + float(reward_cfg.get("coverage_reward", 50.0))
        )

    @staticmethod
    def _fmt(value) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:.4f}"
        return str(value)
