from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PRIVATE_KEYS = {
    "truth",
    "truth_lat",
    "truth_lon",
    "truth_region",
    "truth_city",
    "error_km",
    "candidate_rewards",
    "chosen_reward",
    "reward",
}


@dataclass(frozen=True)
class LeakageFinding:
    path: str
    key: str


def scan_for_private_truth(payload: Any, path: str = "$") -> list[LeakageFinding]:
    """扫描模型可见载荷中的真值或奖励字段。"""

    findings: list[LeakageFinding] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            child_path = f"{path}.{key}"
            if str(key).lower() in PRIVATE_KEYS:
                findings.append(LeakageFinding(path=child_path, key=str(key)))
            findings.extend(scan_for_private_truth(value, child_path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            findings.extend(scan_for_private_truth(value, f"{path}[{index}]"))
    return findings


def assert_no_private_truth(payload: Any) -> None:
    findings = scan_for_private_truth(payload)
    if findings:
        paths = ", ".join(item.path for item in findings[:10])
        raise ValueError(f"模型可见载荷包含私有真值或奖励字段：{paths}")
