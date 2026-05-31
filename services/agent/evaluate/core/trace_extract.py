"""LangSmith Trace 提取工具。"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from langsmith import Client


def _extract_request_trace_id(run: Any) -> str:
    """提取请求级 trace_id（优先读取 run.extra.metadata.trace_id）。"""
    extra = getattr(run, "extra", None)
    if isinstance(extra, dict):
        metadata = extra.get("metadata")
        if isinstance(metadata, dict):
            trace_id = metadata.get("trace_id")
            if trace_id:
                return str(trace_id)

    # 兼容少量 SDK 场景：metadata 可能直接暴露在 run.metadata
    metadata_attr = getattr(run, "metadata", None)
    if isinstance(metadata_attr, dict):
        trace_id = metadata_attr.get("trace_id")
        if trace_id:
            return str(trace_id)

    # 最后回退到 LangSmith 内部 trace_id 字段。
    fallback_trace_id = getattr(run, "trace_id", None)
    return str(fallback_trace_id) if fallback_trace_id is not None else ""


def _extract_start_time(run: Any) -> datetime:
    """提取 run.start_time，缺省时返回最小时间。"""
    value = getattr(run, "start_time", None)
    if isinstance(value, datetime):
        return value
    return datetime.min.replace(tzinfo=timezone.utc)


def _is_run_outputs_ready(run: Any) -> bool:
    """判断 root run 输出是否已就绪（兼容 LangSmith 最终一致性延迟）。"""
    outputs = getattr(run, "outputs", None)
    if not isinstance(outputs, dict):
        return False
    # 只要出现核心字段之一，即可认为已可用于评测提取。
    for key in (
        "node_records",
        "final_state_output",
        "main_flow_trace",
        "answer",
        "metadata",
    ):
        if key in outputs:
            return True
    return False


def _safe_json_loads(text: Any) -> Dict[str, Any]:
    """安全解析 JSON 字符串。"""
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return {}
    raw = text.strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def fetch_root_run_by_trace(
    trace_id: str,
    project: str,
    since_hours: float = 24.0,
    limit: int = 100,
    max_retries: int = 20,
    retry_interval_seconds: float = 1.5,
) -> Any:
    """按请求级 trace_id 拉取 root run（带短轮询，兼容 LangSmith 最终一致性）。"""
    if not trace_id.strip():
        raise ValueError("trace_id 不能为空")
    client = Client()
    # LangSmith /runs/query 对 limit 的服务端上限是 100。
    safe_limit = max(1, min(100, int(limit)))
    kwargs: Dict[str, Any] = {"limit": safe_limit, "is_root": True}
    if project.strip():
        kwargs["project_name"] = project
    if since_hours > 0:
        kwargs["start_time"] = datetime.now(timezone.utc) - timedelta(
            hours=float(since_hours)
        )
    attempts = max(1, int(max_retries))
    last_seen_runs = 0
    for _ in range(attempts):
        runs = list(client.list_runs(**kwargs))
        last_seen_runs = len(runs)
        matched = [run for run in runs if _extract_request_trace_id(run) == trace_id]
        if matched:
            matched = sorted(matched, key=_extract_start_time)
            langgraph_roots = [
                run
                for run in matched
                if str(getattr(run, "name", "")) == "langgraph_agent"
            ]
            candidate = langgraph_roots[0] if langgraph_roots else matched[0]
            if _is_run_outputs_ready(candidate):
                return candidate
        time.sleep(max(0.0, float(retry_interval_seconds)))

    # 兜底：跨项目再查一次，避免 project 过滤不一致导致漏检。
    fallback_kwargs = dict(kwargs)
    fallback_kwargs.pop("project_name", None)
    runs = list(client.list_runs(**fallback_kwargs))
    last_seen_runs = len(runs)
    matched = [run for run in runs if _extract_request_trace_id(run) == trace_id]
    if matched:
        matched = sorted(matched, key=_extract_start_time)
        langgraph_roots = [
            run for run in matched if str(getattr(run, "name", "")) == "langgraph_agent"
        ]
        candidate = langgraph_roots[0] if langgraph_roots else matched[0]
        if _is_run_outputs_ready(candidate):
            return candidate

    raise RuntimeError(
        f"未找到 trace_id 对应可用 root run: {trace_id} "
        f"(project={project or '-'}, looked_up_roots={last_seen_runs}, retries={attempts})"
    )


def _collect_tool_execution_records(
    node_records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """从 node_records 提取完整工具执行记录，保留实际调用顺序。"""
    input_records: List[Dict[str, Any]] = []
    output_records: Dict[str, Dict[str, Any]] = {}
    for record in node_records:
        prompt_records = (
            record.get("prompt_records") if isinstance(record, dict) else None
        )
        if not isinstance(prompt_records, list):
            continue
        for item in prompt_records:
            if not isinstance(item, dict):
                continue
            stage = str(item.get("stage") or "").strip()
            if stage == "tool_dispatch_inputs":
                tools_raw = item.get("tools")
                tools: List[Dict[str, Any]] = (
                    tools_raw if isinstance(tools_raw, list) else []
                )
                for tool in tools:
                    if not isinstance(tool, dict):
                        continue
                    name = str(tool.get("tool") or "").strip()
                    if not name:
                        continue
                    input_records.append(
                        {
                            "step_id": str(tool.get("step_id") or ""),
                            "name": name,
                            "arguments": tool.get("arguments")
                            if isinstance(tool.get("arguments"), dict)
                            else {},
                        }
                    )
                continue

            if stage != "tool_dispatch_outputs":
                continue
            output_items_raw = item.get("results")
            output_items: List[Dict[str, Any]] = (
                output_items_raw if isinstance(output_items_raw, list) else []
            )
            for out in output_items:
                if not isinstance(out, dict):
                    continue
                step_id = str(out.get("step_id") or "").strip()
                if not step_id:
                    continue
                output_records[step_id] = {
                    "status": str(out.get("status") or "unknown"),
                    "error": str(out.get("error") or ""),
                    "result_preview": str(out.get("result_preview") or ""),
                    "evidences_size": int(out.get("evidences_size") or 0),
                    "sources_size": int(out.get("sources_size") or 0),
                }

    merged_records: List[Dict[str, Any]] = []
    for item in input_records:
        step_id = str(item.get("step_id") or "")
        output = output_records.get(step_id, {})
        merged_records.append(
            {
                "step_id": step_id,
                "name": str(item.get("name") or ""),
                "arguments": item.get("arguments")
                if isinstance(item.get("arguments"), dict)
                else {},
                "status": str(output.get("status") or "unknown"),
                "error": str(output.get("error") or ""),
                "result_preview": str(output.get("result_preview") or ""),
                "evidences_size": int(output.get("evidences_size") or 0),
                "sources_size": int(output.get("sources_size") or 0),
            }
        )
    return merged_records


def _collect_tool_calls(
    tool_execution_records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """从工具执行记录中提取工具调用。"""
    calls: List[Dict[str, Any]] = []
    for record in tool_execution_records:
        if not isinstance(record, dict):
            continue
        name = str(record.get("name") or "").strip()
        if not name:
            continue
        calls.append(
            {
                "name": name,
                "arguments": record.get("arguments")
                if isinstance(record.get("arguments"), dict)
                else {},
                "step_id": str(record.get("step_id") or ""),
            }
        )
    return calls


def _build_tool_response_text(tool_execution_record: Dict[str, Any]) -> str:
    """把单步工具执行结果拼成稳定的文本摘要。"""
    status = str(tool_execution_record.get("status") or "unknown")
    error = str(tool_execution_record.get("error") or "")
    preview = str(tool_execution_record.get("result_preview") or "")
    lines = [f"status={status}"]
    if error:
        lines.append(f"error={error}")
    if preview:
        lines.append(f"result_preview={preview}")
    return "\n".join(lines)


def _collect_plan_text(node_records: List[Dict[str, Any]]) -> str:
    """提取计划节点文本摘要。"""
    plan_record = None
    for record in node_records:
        if isinstance(record, dict) and str(record.get("node_name") or "") == "plan":
            plan_record = record
            break
    if not isinstance(plan_record, dict):
        return ""

    final_output = _safe_json_loads(plan_record.get("final_output"))
    plan_steps_raw = final_output.get("plan_steps")
    plan_steps: List[Dict[str, Any]] = (
        plan_steps_raw if isinstance(plan_steps_raw, list) else []
    )
    reason = str(final_output.get("plan_reason") or "").strip()
    lines: List[str] = []
    if reason:
        lines.append(f"reason={reason}")
    for idx, step in enumerate(plan_steps, start=1):
        if not isinstance(step, dict):
            continue
        tool = str(step.get("tool") or "none")
        objective = str(step.get("objective") or "")
        lines.append(f"{idx}. [{tool}] {objective}")
    return "\n".join(lines)


def _collect_memory_text(node_records: List[Dict[str, Any]]) -> str:
    """提取记忆节点信息。"""
    memory_record = None
    for record in node_records:
        if (
            isinstance(record, dict)
            and str(record.get("node_name") or "") == "collect_memory_notes"
        ):
            memory_record = record
            break
    if not isinstance(memory_record, dict):
        return ""
    payload = _safe_json_loads(memory_record.get("final_output"))
    memories_raw = payload.get("memories")
    memories: List[Any] = memories_raw if isinstance(memories_raw, list) else []
    notes_raw = payload.get("notes")
    notes: List[Any] = notes_raw if isinstance(notes_raw, list) else []
    return f"memories={len(memories)}; notes={len(notes)}"


def _collect_observation_text(
    final_state_output: Dict[str, Any], tool_calls: List[Dict[str, Any]]
) -> str:
    """构建 observation 文本摘要。"""
    conflicts_raw = final_state_output.get("conflicts")
    conflicts: List[Any] = conflicts_raw if isinstance(conflicts_raw, list) else []
    pending_ids_raw = final_state_output.get("pending_ids")
    pending_ids: List[Any] = (
        pending_ids_raw if isinstance(pending_ids_raw, list) else []
    )
    completed_ids_raw = final_state_output.get("completed_ids")
    completed_ids: List[Any] = (
        completed_ids_raw if isinstance(completed_ids_raw, list) else []
    )
    return (
        f"completed={len(completed_ids)}; pending={len(pending_ids)}; "
        f"tool_calls={len(tool_calls)}; conflicts={len(conflicts)}"
    )


def _collect_evidence_items(final_state_output: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 final_state_output 提取结构化 evidence 列表。"""
    raw_items = final_state_output.get("evidence_items")
    if not isinstance(raw_items, list):
        return []
    evidence_items: List[Dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        evidence_items.append(
            {
                "title": str(item.get("title") or ""),
                "source": str(item.get("source") or ""),
                "content": str(item.get("content") or ""),
                "score": float(item.get("score") or 0.0),
                "metadata": dict(item.get("metadata") or {}),
            }
        )
    return evidence_items


def _build_evidence_summary(
    *,
    final_state_output: Dict[str, Any],
    evidence_items: List[Dict[str, Any]],
    tool_calls: List[Dict[str, Any]],
) -> str:
    """构建 evidence_summary 文本，优先使用结构化证据。"""
    if evidence_items:
        source_counts: Dict[str, int] = {}
        for item in evidence_items:
            source = str(item.get("source") or "unknown").strip() or "unknown"
            source_counts[source] = source_counts.get(source, 0) + 1
        source_stat = ", ".join(
            f"{key}:{value}" for key, value in sorted(source_counts.items())
        )
        lines = [
            f"evidence_count={len(evidence_items)}; tool_calls={len(tool_calls)}; sources={source_stat}",
        ]
        # 为避免评分提示过长，仅拼接前 6 条证据摘要。
        for index, item in enumerate(evidence_items[:6], start=1):
            lines.append(
                f"[{index}] source={item.get('source', '')}; "
                f"title={str(item.get('title') or '')[:80]}; "
                f"content={str(item.get('content') or '')[:220]}"
            )
        return "\n".join(lines)

    # 兼容旧 trace：尚未落结构化 evidence 时回退旧摘要构造逻辑。
    context_preview = str(final_state_output.get("context_preview") or "")
    answer_preview = str(final_state_output.get("answer_preview") or "")
    return (
        f"context_preview={context_preview[:500]}\n"
        f"answer_preview={answer_preview[:500]}\n"
        f"tool_calls={len(tool_calls)}"
    )


def build_trajectory_messages(
    query: str,
    answer: str,
    tool_execution_records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """构建 TrajectoryComprehensiveGrader 所需的 messages。"""
    messages: List[Dict[str, Any]] = [{"role": "user", "content": query}]
    for record in tool_execution_records:
        name = str(record.get("name") or "")
        args = (
            record.get("arguments") if isinstance(record.get("arguments"), dict) else {}
        )
        step_id = str(record.get("step_id") or "")
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": name,
                            "arguments": json.dumps(args, ensure_ascii=False),
                        }
                    }
                ],
            }
        )
        tool_response = _build_tool_response_text(record)
        if tool_response:
            messages.append(
                {"role": "tool", "content": tool_response, "tool_call_id": step_id}
            )
    messages.append({"role": "assistant", "content": answer})
    return messages


def rebuild_trace_artifacts(
    *,
    query: str,
    answer: str,
    node_records: List[Dict[str, Any]],
    final_state_output: Dict[str, Any],
    main_flow_trace: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """基于已保存 trace 载荷重建评分所需字段，供后补重评分复用。"""
    tool_execution_records = _collect_tool_execution_records(node_records)
    tool_calls = _collect_tool_calls(tool_execution_records)
    trajectory_messages = build_trajectory_messages(
        query=query,
        answer=answer,
        tool_execution_records=tool_execution_records,
    )

    plan_text = _collect_plan_text(node_records)
    memory_text = _collect_memory_text(node_records)
    observation_text = _collect_observation_text(final_state_output, tool_calls)
    evidence_items = _collect_evidence_items(final_state_output)
    evidence_summary = _build_evidence_summary(
        final_state_output=final_state_output,
        evidence_items=evidence_items,
        tool_calls=tool_calls,
    )

    return {
        "node_records": node_records,
        "final_state_output": final_state_output,
        "main_flow_trace": main_flow_trace or {},
        "tool_execution_records": tool_execution_records,
        "tool_calls": tool_calls,
        "trajectory_messages": trajectory_messages,
        "plan_text": plan_text,
        "observation_text": observation_text,
        "memory_text": memory_text,
        "evidence_items": evidence_items,
        "evidence_summary": evidence_summary,
    }


def extract_trace_artifacts(query: str, answer: str, root_run: Any) -> Dict[str, Any]:
    """从 root run 输出提取评测所需字段。"""
    outputs = getattr(root_run, "outputs", None)
    if not isinstance(outputs, dict):
        raise RuntimeError("root run 输出为空，无法提取 trace 字段")

    node_records_raw = outputs.get("node_records")
    node_records: List[Dict[str, Any]] = (
        node_records_raw if isinstance(node_records_raw, list) else []
    )
    final_state_output_raw = outputs.get("final_state_output")
    final_state_output: Dict[str, Any] = (
        final_state_output_raw if isinstance(final_state_output_raw, dict) else {}
    )
    main_flow_trace_raw = outputs.get("main_flow_trace")
    main_flow_trace: Dict[str, Any] = (
        main_flow_trace_raw if isinstance(main_flow_trace_raw, dict) else {}
    )

    return rebuild_trace_artifacts(
        query=query,
        answer=answer,
        node_records=node_records,
        final_state_output=final_state_output,
        main_flow_trace=main_flow_trace,
    )
