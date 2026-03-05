"""阶段 B：调用 FusionAgent 自动补齐答案并提取 trace。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import List

from agent.core.config import AgentConfig
from agent.evaluate.core.config import (
    DEFAULT_FAILURE_RATE_THRESHOLD,
    DEFAULT_LANGSMITH_LIMIT,
    DEFAULT_TRACE_SINCE_HOURS,
    resolve_langsmith_project,
)
from agent.evaluate.core.schemas import AnswerSample, QuerySample, load_query_samples, write_jsonl
from agent.evaluate.core.trace_extract import extract_trace_artifacts, fetch_root_run_by_trace


def _ensure_langsmith_tracing_enabled() -> None:
    """检查 LangSmith tracing 已开启。"""
    enabled = (os.getenv("LANGSMITH_TRACING") or "").strip().lower()
    if enabled != "true":
        raise RuntimeError("必须开启 LANGSMITH_TRACING=true 才能执行 fill_answers")


def fill_answers(
    query_samples: List[QuerySample],
    out_path: Path,
    trace_since_hours: float,
    langsmith_limit: int,
    max_failure_rate: float,
) -> List[AnswerSample]:
    """执行批量问答并产出 AnswerSample。"""
    _ensure_langsmith_tracing_enabled()
    if not query_samples:
        raise ValueError("query_samples 为空")

    # 延迟导入，避免仅使用查询生成等轻量脚本时强制依赖 LangGraph 运行时。
    from agent.runtime.fusion_agent import FusionAgent

    config = AgentConfig.load()
    agent = FusionAgent(config=config)
    project = resolve_langsmith_project()

    answers: List[AnswerSample] = []
    failed = 0
    for index, sample in enumerate(query_samples, start=1):
        trace_id = ""
        metadata = {}
        try:
            answer_text, metadata = agent.respond(sample.query)
            trace_id = str((metadata or {}).get("trace_id") or "").strip()
            if not trace_id:
                raise RuntimeError("FusionAgent 未返回 trace_id")

            root_run = fetch_root_run_by_trace(
                trace_id=trace_id,
                project=project,
                since_hours=trace_since_hours,
                limit=langsmith_limit,
            )
            artifacts = extract_trace_artifacts(query=sample.query, answer=answer_text, root_run=root_run)

            answers.append(
                AnswerSample(
                    id=sample.id,
                    query=sample.query,
                    answer=str(answer_text or ""),
                    status="ok",
                    error="",
                    trace_id=trace_id,
                    agent_metadata=dict(metadata or {}),
                    node_records=list(artifacts.get("node_records") or []),
                    final_state_output=dict(artifacts.get("final_state_output") or {}),
                    main_flow_trace=dict(artifacts.get("main_flow_trace") or {}),
                    tool_calls=list(artifacts.get("tool_calls") or []),
                    trajectory_messages=list(artifacts.get("trajectory_messages") or []),
                    plan_text=str(artifacts.get("plan_text") or ""),
                    observation_text=str(artifacts.get("observation_text") or ""),
                    memory_text=str(artifacts.get("memory_text") or ""),
                    evidence_items=list(artifacts.get("evidence_items") or []),
                    evidence_summary=str(artifacts.get("evidence_summary") or ""),
                    expected_tools=list(sample.expected_tools),
                    expected_tool_calls=list(sample.expected_tool_calls),
                    reference_answer=sample.reference_answer,
                )
            )
            print(f"[fill_answers] {index}/{len(query_samples)} ok id={sample.id} trace_id={trace_id}")
        except Exception as exc:
            failed += 1
            answers.append(
                AnswerSample(
                    id=sample.id,
                    query=sample.query,
                    answer="",
                    status="error",
                    error=str(exc),
                    trace_id=trace_id,
                    agent_metadata=dict(metadata or {}),
                    expected_tools=list(sample.expected_tools),
                    expected_tool_calls=list(sample.expected_tool_calls),
                    reference_answer=sample.reference_answer,
                )
            )
            print(f"[fill_answers] {index}/{len(query_samples)} error id={sample.id} error={exc}")

    write_jsonl(out_path, [item.to_dict() for item in answers])

    failure_rate = failed / len(query_samples)
    print(
        f"[fill_answers] 写入完成: {out_path} | total={len(query_samples)} failed={failed} failure_rate={failure_rate:.2%}"
    )
    if failure_rate > max_failure_rate:
        raise RuntimeError(
            f"失败率超阈值: {failure_rate:.2%} > {max_failure_rate:.2%}，请先排查系统再继续评分"
        )
    return answers


def build_arg_parser() -> argparse.ArgumentParser:
    """构建命令行参数。"""
    parser = argparse.ArgumentParser(description="批量补齐答案并提取 LangSmith trace")
    parser.add_argument("--in", dest="in_path", required=True, help="输入 queries.jsonl")
    parser.add_argument("--out", dest="out_path", required=True, help="输出 answers.jsonl")
    parser.add_argument(
        "--trace-since-hours",
        type=float,
        default=DEFAULT_TRACE_SINCE_HOURS,
        help="LangSmith 查询时间窗口（小时）",
    )
    parser.add_argument(
        "--langsmith-limit",
        type=int,
        default=DEFAULT_LANGSMITH_LIMIT,
        help="LangSmith list_runs 限制（最大 100）",
    )
    parser.add_argument(
        "--max-failure-rate",
        type=float,
        default=DEFAULT_FAILURE_RATE_THRESHOLD,
        help="允许最大失败率（默认 0.2）",
    )
    return parser


def main() -> int:
    """脚本入口。"""
    args = build_arg_parser().parse_args()
    in_path = Path(args.in_path).resolve()
    out_path = Path(args.out_path).resolve()

    query_samples = load_query_samples(in_path)
    fill_answers(
        query_samples=query_samples,
        out_path=out_path,
        trace_since_hours=float(args.trace_since_hours),
        langsmith_limit=int(args.langsmith_limit),
        max_failure_rate=float(args.max_failure_rate),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
