"""阶段 A：生成评测 query 数据集。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from agent.evaluate.core.config import DEFAULT_QUERY_COUNT, DEFAULT_SUMMARY_PATH
from agent.evaluate.core.query_bank import build_query_samples
from agent.evaluate.core.schemas import QuerySample, write_jsonl


def generate_queries(count: int, out_path: Path, summary_path: Path) -> List[QuerySample]:
    """生成 query 并写出 JSONL。"""
    samples = build_query_samples(count=count, summary_path=summary_path)
    write_jsonl(out_path, [item.to_dict() for item in samples])
    return samples


def build_arg_parser() -> argparse.ArgumentParser:
    """构建命令行参数。"""
    parser = argparse.ArgumentParser(description="生成 OpenJudge 评测 query 数据集")
    parser.add_argument("--count", type=int, default=DEFAULT_QUERY_COUNT, help="题目数量（默认 30）")
    parser.add_argument(
        "--out",
        type=str,
        default="agent/evaluate/data/queries.jsonl",
        help="输出 JSONL 路径",
    )
    parser.add_argument(
        "--summary",
        type=str,
        default=str(DEFAULT_SUMMARY_PATH),
        help="summary.md 路径（用于输入约束校验）",
    )
    return parser


def main() -> int:
    """脚本入口。"""
    args = build_arg_parser().parse_args()
    out_path = Path(args.out).resolve()
    summary_path = Path(args.summary).resolve()
    samples = generate_queries(count=int(args.count), out_path=out_path, summary_path=summary_path)
    print(f"[generate_queries] 写入完成: {out_path}")
    print(f"[generate_queries] 样本数量: {len(samples)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
