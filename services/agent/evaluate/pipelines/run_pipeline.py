"""一键执行评测流水线。"""

from __future__ import annotations

import argparse
from pathlib import Path

from agent.core.config import AgentConfig
from agent.evaluate.pipelines.build_graders import generate_rubrics
from agent.evaluate.core.config import (
    EvalRuntimeConfig,
    ensure_langsmith_tracing_enabled,
    ensure_workdir,
)
from agent.evaluate.pipelines.convert_gold_readable import convert_readable_to_gold
from agent.evaluate.pipelines.fill_answers import fill_answers
from agent.evaluate.pipelines.generate_queries import generate_queries
from agent.evaluate.core.schemas import load_answer_samples, load_query_samples
from agent.evaluate.pipelines.score_pipeline import run_scoring


def run_pipeline(
    runtime_cfg: EvalRuntimeConfig,
    push_langsmith: bool,
    dataset_name: str,
    experiment_prefix: str,
    rubric_labeled_data: Path | None,
    model_name: str,
    gold_readable_path: Path | None,
    gold_out_path: Path | None,
    gold_base_path: Path | None,
    langsmith_mode: str = "writeback",
) -> None:
    """串行执行 A->B->C->D。"""
    ensure_workdir(runtime_cfg.workdir)
    ensure_langsmith_tracing_enabled()

    # 阶段 A
    generate_queries(
        count=runtime_cfg.query_count,
        out_path=runtime_cfg.queries_path,
        summary_path=runtime_cfg.summary_path,
    )

    # 阶段 B
    query_samples = load_query_samples(runtime_cfg.queries_path)
    fill_answers(
        query_samples=query_samples,
        out_path=runtime_cfg.answers_path,
        trace_since_hours=runtime_cfg.trace_since_hours,
        langsmith_limit=runtime_cfg.langsmith_limit,
        max_failure_rate=runtime_cfg.max_failure_rate,
    )

    # 阶段 C
    generate_rubrics(
        out_path=runtime_cfg.rubrics_path,
        labeled_data_path=rubric_labeled_data,
        model_name=model_name,
    )

    # 阶段 D
    answer_samples = load_answer_samples(runtime_cfg.answers_path)
    run_scoring(
        answer_samples=answer_samples,
        rubrics_path=runtime_cfg.rubrics_path,
        scored_out_path=runtime_cfg.scored_path,
        summary_out_path=runtime_cfg.summary_json_path,
        manual_review_csv_path=runtime_cfg.manual_review_csv_path,
        push_langsmith=push_langsmith,
        langsmith_mode=langsmith_mode,
        dataset_name=dataset_name,
        experiment_prefix=experiment_prefix,
        model_name=model_name,
    )

    # 阶段 E（可选）：将人工可读标注 YAML 转换为 gold.jsonl。
    if gold_readable_path:
        resolved_gold_out = gold_out_path or (runtime_cfg.workdir / "gold.jsonl")
        resolved_gold_base = gold_base_path or resolved_gold_out
        convert_readable_to_gold(
            readable_path=gold_readable_path,
            out_path=resolved_gold_out,
            base_gold_path=resolved_gold_base,
            answers_path=runtime_cfg.answers_path,
            score_source=str(gold_readable_path),
        )


def build_arg_parser() -> argparse.ArgumentParser:
    """构建命令行参数。"""
    parser = argparse.ArgumentParser(description="一键执行 OpenJudge 评测流水线")
    parser.add_argument("--count", type=int, default=30, help="题目数量，默认 30")
    parser.add_argument("--workdir", default="agent/evaluate/data", help="产物目录")
    parser.add_argument("--summary", default="summary.md", help="summary.md 路径")
    parser.add_argument(
        "--push-langsmith", action="store_true", help="是否写入 LangSmith Experiment"
    )
    parser.add_argument(
        "--langsmith-mode",
        default="writeback",
        choices=["writeback", "evaluate"],
        help="LangSmith 推送模式：writeback=直写本地分数，evaluate=在 LangSmith 中再次执行 grader",
    )
    parser.add_argument(
        "--dataset-name", default="fusion-openjudge-eval", help="LangSmith dataset 名称"
    )
    parser.add_argument(
        "--experiment-prefix",
        default="fusion-openjudge",
        help="LangSmith experiment 前缀",
    )
    parser.add_argument(
        "--rubric-labeled-data", default="", help="可选 rubric 标注数据 JSON/JSONL"
    )
    parser.add_argument("--model", default="", help="可选覆盖评分模型名")
    parser.add_argument(
        "--trace-since-hours",
        type=float,
        default=24.0,
        help="trace 查询时间窗口（小时）",
    )
    parser.add_argument(
        "--langsmith-limit", type=int, default=100, help="list_runs 拉取上限"
    )
    parser.add_argument(
        "--max-failure-rate", type=float, default=0.2, help="阶段 B 最大失败率"
    )
    parser.add_argument(
        "--gold-readable", default="", help="可选：人工可读 gold YAML 路径"
    )
    parser.add_argument("--gold-out", default="", help="可选：gold.jsonl 输出路径")
    parser.add_argument(
        "--gold-base", default="", help="可选：旧 gold.jsonl 路径（补齐元字段）"
    )
    return parser


def main() -> int:
    """脚本入口。"""
    # 统一在入口阶段加载 conf/.env，避免评测命令依赖手工 source。
    AgentConfig.load()
    args = build_arg_parser().parse_args()
    runtime_cfg = EvalRuntimeConfig(
        workdir=Path(args.workdir).resolve(),
        summary_path=Path(args.summary).resolve(),
        query_count=int(args.count),
        trace_since_hours=float(args.trace_since_hours),
        langsmith_limit=int(args.langsmith_limit),
        max_failure_rate=float(args.max_failure_rate),
    )
    rubric_labeled_data = (
        Path(args.rubric_labeled_data).resolve() if args.rubric_labeled_data else None
    )
    gold_readable_path = (
        Path(args.gold_readable).resolve() if args.gold_readable else None
    )
    gold_out_path = Path(args.gold_out).resolve() if args.gold_out else None
    gold_base_path = Path(args.gold_base).resolve() if args.gold_base else None

    run_pipeline(
        runtime_cfg=runtime_cfg,
        push_langsmith=bool(args.push_langsmith),
        langsmith_mode=str(args.langsmith_mode),
        dataset_name=str(args.dataset_name),
        experiment_prefix=str(args.experiment_prefix),
        rubric_labeled_data=rubric_labeled_data,
        model_name=str(args.model or "").strip(),
        gold_readable_path=gold_readable_path,
        gold_out_path=gold_out_path,
        gold_base_path=gold_base_path,
    )
    print(f"[run_pipeline] 完成，产物目录: {runtime_cfg.workdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
