from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentic_ipv6_geo.environment.env import GeoAgentEnv
from agentic_ipv6_geo.environment.schemas import PrivateTruth, ToolObservation


def load_p0_environment(root: str | Path, max_steps: int = 4, max_probe_count: int = 12) -> GeoAgentEnv:
    """从 P0 构建产物加载可确定性重放的多轮环境。"""

    dataset_dir = Path(root) / "dataset"
    tasks = {row["task_id"]: row for row in _read_jsonl(dataset_dir / "tasks.jsonl")}
    private_truth = {row["task_id"]: PrivateTruth.from_dict(row) for row in _read_jsonl(dataset_dir / "private_truth.jsonl")}
    replay: dict[str, dict[str, ToolObservation]] = {}
    for row in _read_jsonl(dataset_dir / "tool_replay.jsonl"):
        task_id = str(row.pop("task_id"))
        row.pop("split", None)
        observation = ToolObservation.from_dict(row)
        replay.setdefault(task_id, {})[observation.tool_id] = observation
    return GeoAgentEnv(tasks, replay, private_truth, max_steps=max_steps, max_probe_count=max_probe_count)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
