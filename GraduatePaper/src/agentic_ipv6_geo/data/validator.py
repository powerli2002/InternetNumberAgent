from __future__ import annotations

import json
from pathlib import Path

from agentic_ipv6_geo.data.repository import DataRepository


class DataValidator:
    def __init__(self, repo: DataRepository):
        self.repo = repo

    def validate(self) -> dict:
        duplicate_targets = len(self.repo.targets) - len({target.ip for target in self.repo.targets})
        invalid_targets = [
            target.ip
            for target in self.repo.targets
            if not target.location.has_coordinate
            or target.location.lat is None
            or target.location.lon is None
            or not (-90 <= target.location.lat <= 90)
            or not (-180 <= target.location.lon <= 180)
        ]
        trace_targets = {hop.target_ip for hop in self.repo.traces}
        targets = {target.ip for target in self.repo.targets}
        orphan_trace_targets = sorted(trace_targets - targets)[:20]
        missing_trace_count = sum(1 for target in self.repo.targets if target.ip not in trace_targets)
        missing_modugeo_count = sum(1 for target in self.repo.targets if self.repo.modugeo_prediction_for(target.ip) is None)
        missing_rdns_count = sum(1 for target in self.repo.targets if self.repo.rdns_for(target.ip) is None)

        return {
            "target_count": len(self.repo.targets),
            "trace_hop_count": len(self.repo.traces),
            "probe_count": len(self.repo.probes),
            "metadata_count": len(self.repo.metadata),
            "rdns_count": len(self.repo.rdns),
            "landmark_count": len(self.repo.landmarks),
            "modugeo_prediction_count": len(self.repo.modugeo_predictions),
            "duplicate_target_count": duplicate_targets,
            "invalid_target_count": len(invalid_targets),
            "invalid_target_examples": invalid_targets[:20],
            "missing_trace_target_count": missing_trace_count,
            "missing_modugeo_prediction_count": missing_modugeo_count,
            "missing_rdns_target_count": missing_rdns_count,
            "orphan_trace_target_examples": orphan_trace_targets,
            "is_valid_for_evaluation": len(self.repo.targets) > 0 and len(invalid_targets) == 0,
        }


def write_validation_report(path: str | Path, report: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
