from __future__ import annotations

import time
from typing import Any

from agentic_ipv6_geo.common.models import Cost, GeoResult, Target
from agentic_ipv6_geo.data.repository import DataRepository


class BaseGeoTool:
    name = "Base"

    def __init__(self, repo: DataRepository, config: dict[str, Any] | None = None):
        self.repo = repo
        self.config = config or {}

    def run(self, target: Target) -> GeoResult:
        start = time.perf_counter()
        result = self._run(target)
        elapsed = (time.perf_counter() - start) * 1000
        result.cost = Cost(
            time_ms=elapsed,
            probe_count=result.cost.probe_count,
            tool_calls=result.cost.tool_calls,
        )
        return result

    def _run(self, target: Target) -> GeoResult:
        raise NotImplementedError
