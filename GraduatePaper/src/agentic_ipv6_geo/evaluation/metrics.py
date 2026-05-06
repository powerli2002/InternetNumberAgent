from __future__ import annotations

import statistics


def summarize_errors(errors: list[float], covered: int, total: int, tool_calls: list[int], probe_counts: list[int]) -> dict:
    if not errors:
        return {
            "Median": None,
            "Mean": None,
            "P90": None,
            "Coverage": 0.0,
            "AvgToolCalls": 0.0,
            "AvgProbeCost": 0.0,
        }
    ordered = sorted(errors)
    p90_index = min(len(ordered) - 1, int(0.9 * (len(ordered) - 1)))
    return {
        "Median": statistics.median(ordered),
        "Mean": statistics.mean(ordered),
        "P90": ordered[p90_index],
        "Coverage": covered / total if total else 0.0,
        "AvgToolCalls": statistics.mean(tool_calls) if tool_calls else 0.0,
        "AvgProbeCost": statistics.mean(probe_counts) if probe_counts else 0.0,
    }
