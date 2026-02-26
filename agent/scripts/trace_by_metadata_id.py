#!/usr/bin/env python3
"""
按 metadata.trace_id 拼接 LangSmith 跨服务链路。

功能：
1. 从指定项目读取最近一段时间内的 runs。
2. 使用 metadata.trace_id 过滤关联 runs（跨 langgraph/mcp）。
3. 输出计划节点（graph_node:plan）、时间线、错误摘要。
4. 可选输出关键节点的输入输出预览，便于定位问题。
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from langsmith import Client


def _extract_metadata(run: Any) -> Dict[str, Any]:
    """兼容不同 SDK 字段结构，提取 metadata。"""
    extra = getattr(run, "extra", None)
    if isinstance(extra, dict):
        metadata = extra.get("metadata")
        if isinstance(metadata, dict):
            return metadata
    metadata = getattr(run, "metadata", None)
    if isinstance(metadata, dict):
        return metadata
    return {}


def _extract_start_time(run: Any) -> datetime:
    """提取 start_time，缺失时给最小值便于排序。"""
    start_time = getattr(run, "start_time", None)
    if isinstance(start_time, datetime):
        return start_time
    return datetime.min.replace(tzinfo=timezone.utc)


def _short_id(value: Any) -> str:
    raw = str(value) if value is not None else "-"
    if raw == "-" or len(raw) <= 8:
        return raw
    return raw[:8]


def _json_preview(value: Any, limit: int) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...<truncated {len(text)} chars>"


def _build_parent_map(runs: Iterable[Any]) -> Dict[str, Optional[str]]:
    parent_map: Dict[str, Optional[str]] = {}
    for run in runs:
        run_id = str(getattr(run, "id", ""))
        parent = getattr(run, "parent_run_id", None)
        parent_map[run_id] = str(parent) if parent else None
    return parent_map


def _resolve_root(run_id: str, parent_map: Dict[str, Optional[str]]) -> str:
    """在过滤后的 runs 集合中解析根节点。"""
    seen = set()
    current = run_id
    while current and current not in seen:
        seen.add(current)
        parent = parent_map.get(current)
        if not parent or parent not in parent_map:
            return current
        current = parent
    return run_id


def _extract_plan_payload(run: Any) -> Optional[Dict[str, Any]]:
    outputs = getattr(run, "outputs", None)
    if not isinstance(outputs, dict):
        return None
    # LangGraph 新版追踪：plan/reason 直接挂在 outputs 顶层
    if isinstance(outputs.get("plan"), list):
        return {
            "plan": outputs.get("plan", []),
            "reason": outputs.get("reason", ""),
        }
    payload = outputs.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("plan"), list):
        return payload
    return None


def _extract_error(run: Any) -> str:
    """提取 run 级错误和常见工具错误。"""
    run_error = getattr(run, "error", None)
    if run_error:
        return str(run_error)
    outputs = getattr(run, "outputs", None)
    if isinstance(outputs, dict):
        final_event = outputs.get("final_event")
        if isinstance(final_event, dict):
            data = final_event.get("data")
            if isinstance(data, dict) and data.get("error"):
                return str(data.get("error"))
    return ""


def _collect_runs(client: Client, project: str, limit: int, since_hours: float) -> List[Any]:
    """
    拉取 runs。

    说明：LangSmith /runs/query 对 limit 有上限（100），此处做硬限制。
    """
    safe_limit = max(1, min(100, int(limit)))
    kwargs: Dict[str, Any] = {"project_name": project, "limit": safe_limit}
    if since_hours > 0:
        kwargs["start_time"] = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    return list(client.list_runs(**kwargs))


def _print_plan_section(runs: List[Any]) -> None:
    plan_runs = [run for run in runs if str(getattr(run, "name", "")).startswith("graph_node:plan")]
    if not plan_runs:
        print("未发现 graph_node:plan 计划节点。")
        return
    for run in sorted(plan_runs, key=_extract_start_time):
        payload = _extract_plan_payload(run)
        print(f"- {run.name} run={_short_id(run.id)}")
        if not payload:
            print("  无 payload.plan。")
            continue
        reason = payload.get("reason", "")
        if reason:
            print(f"  reason: {reason}")
        plan = payload.get("plan", [])
        for idx, step in enumerate(plan, 1):
            if not isinstance(step, dict):
                continue
            tool = step.get("tool") or step.get("agent") or "unknown"
            objective = str(step.get("objective", "")).strip()
            print(f"  {idx}. {tool} -> {objective}")


def _print_timeline(runs: List[Any]) -> None:
    parent_map = _build_parent_map(runs)
    print("时间 | 名称 | 类型 | 状态 | run | parent | root")
    for run in sorted(runs, key=_extract_start_time):
        run_id = str(getattr(run, "id", ""))
        parent = parent_map.get(run_id)
        root = _resolve_root(run_id, parent_map)
        status = "error" if _extract_error(run) else "ok"
        start = _extract_start_time(run).isoformat()
        print(
            f"{start} | {run.name} | {run.run_type} | {status} | "
            f"{_short_id(run_id)} | {_short_id(parent)} | {_short_id(root)}"
        )


def _print_errors(runs: List[Any]) -> None:
    errors: List[Tuple[Any, str]] = []
    for run in runs:
        error = _extract_error(run)
        if error:
            errors.append((run, error))
    if not errors:
        print("未发现错误节点。")
        return
    for run, error in sorted(errors, key=lambda item: _extract_start_time(item[0])):
        print(f"- {run.name} run={_short_id(run.id)}: {error}")


def _print_io_preview(runs: List[Any], io_limit: int) -> None:
    important_prefixes = (
        "graph_node:",
        "langgraph_agent",
        "mcp_tool:",
        "mcp_server:",
    )
    for run in sorted(runs, key=_extract_start_time):
        name = str(getattr(run, "name", ""))
        if not name.startswith(important_prefixes):
            continue
        inputs = getattr(run, "inputs", None)
        outputs = getattr(run, "outputs", None)
        print(f"- {name} run={_short_id(run.id)}")
        print(f"  inputs: {_json_preview(inputs, io_limit)}")
        print(f"  outputs: {_json_preview(outputs, io_limit)}")


def _to_serializable_runs(runs: List[Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for run in sorted(runs, key=_extract_start_time):
        metadata = _extract_metadata(run)
        items.append(
            {
                "id": str(getattr(run, "id", "")),
                "parent_run_id": str(getattr(run, "parent_run_id", "")) if getattr(run, "parent_run_id", None) else None,
                "trace": str(getattr(run, "trace_id", "")),
                "name": str(getattr(run, "name", "")),
                "run_type": str(getattr(run, "run_type", "")),
                "start_time": _extract_start_time(run).isoformat(),
                "metadata": metadata,
                "inputs": getattr(run, "inputs", None),
                "outputs": getattr(run, "outputs", None),
                "error": _extract_error(run) or None,
            }
        )
    return items


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按 metadata.trace_id 聚合 LangSmith runs。")
    parser.add_argument("--trace-id", required=True, help="要拼接的 metadata.trace_id")
    parser.add_argument(
        "--project",
        default=os.getenv("LANGSMITH_PROJECT", "internet-number-qa"),
        help="LangSmith 项目名（默认读 LANGSMITH_PROJECT）",
    )
    parser.add_argument("--limit", type=int, default=100, help="查询 runs 数量上限（最大 100）")
    parser.add_argument("--since-hours", type=float, default=24.0, help="仅拉取最近 N 小时 runs（<=0 表示不限制）")
    parser.add_argument("--show-io", action="store_true", help="打印关键节点输入输出预览")
    parser.add_argument("--io-limit", type=int, default=800, help="输入输出预览最大字符数")
    parser.add_argument("--json-out", default="", help="将聚合结果写入 JSON 文件")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = Client()
    runs = _collect_runs(client, args.project, args.limit, args.since_hours)
    matched = [run for run in runs if _extract_metadata(run).get("trace_id") == args.trace_id]
    matched = sorted(matched, key=_extract_start_time)

    print("=== 查询参数 ===")
    print(f"project={args.project}")
    print(f"trace_id={args.trace_id}")
    print(f"total_runs={len(runs)} matched_runs={len(matched)}")

    if not matched:
        print("未匹配到任何 run。可尝试扩大 --since-hours 或检查 trace_id。")
        return 1

    parent_map = _build_parent_map(matched)
    roots = sorted({_resolve_root(str(getattr(run, "id", "")), parent_map) for run in matched})
    print(f"root_count={len(roots)}")
    for root in roots:
        print(f"  - root={root}")

    print("\n=== 计划节点 ===")
    _print_plan_section(matched)

    print("\n=== 时间线 ===")
    _print_timeline(matched)

    print("\n=== 错误摘要 ===")
    _print_errors(matched)

    if args.show_io:
        print("\n=== 关键输入输出预览 ===")
        _print_io_preview(matched, io_limit=max(200, args.io_limit))

    if args.json_out:
        payload = {
            "project": args.project,
            "metadata_trace_id": args.trace_id,
            "matched_count": len(matched),
            "runs": _to_serializable_runs(matched),
        }
        with open(args.json_out, "w", encoding="utf-8") as fw:
            json.dump(payload, fw, ensure_ascii=False, indent=2, default=str)
        print(f"\n已写入: {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
