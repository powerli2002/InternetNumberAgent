"""评测流水线配置与常量定义。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKDIR = PROJECT_ROOT / "agent" / "evaluate" / "data"
DEFAULT_SUMMARY_PATH = PROJECT_ROOT / "summary.md"
DEFAULT_QUERY_COUNT = 30
DEFAULT_FAILURE_RATE_THRESHOLD = 0.2
DEFAULT_TRACE_SINCE_HOURS = 24.0
DEFAULT_LANGSMITH_LIMIT = 100

# 评分维度与权重
DIMENSION_WEIGHTS: Dict[str, float] = {
    "reasoning_planning": 0.15,
    "tool_use_accuracy": 0.15,
    "final_response_quality": 0.35,
    "evidence_groundedness": 0.35,
}

# 用于 ToolSelection/ToolParameter 等评分器的工具定义。
# 这里采用编排层的抽象工具名（nl2sql/rag/graph/todo/none），
# 与运行时 step.tool 保持一致，避免跨层命名不一致带来的误判。
EVAL_TOOL_DEFINITIONS: List[dict] = [
    {
        "name": "nl2sql",
        "description": "通过自然语言生成 SQL 并查询 PostgreSQL。",
        "parameters": {
            "question": "string",
            "tables": "array[string]",
            "enable_column_retrieval": "boolean",
            "query_mode": "string",
        },
    },
    {
        "name": "rag",
        "description": "从知识库检索相关文档片段。",
        "parameters": {
            "query": "string",
            "top_k": "integer",
        },
    },
    {
        "name": "graph",
        "description": "执行图谱查询并返回结构化结果。",
        "parameters": {
            "question": "string",
            "max_rows": "integer",
        },
    },
    {
        "name": "todo",
        "description": "将复杂目标拆分为子步骤并执行。",
        "parameters": {},
    },
    {
        "name": "none",
        "description": "无需工具执行，仅进行汇总。",
        "parameters": {},
    },
]


@dataclass
class EvalRuntimeConfig:
    """评测运行时配置。"""

    workdir: Path = DEFAULT_WORKDIR
    summary_path: Path = DEFAULT_SUMMARY_PATH
    query_count: int = DEFAULT_QUERY_COUNT
    max_failure_rate: float = DEFAULT_FAILURE_RATE_THRESHOLD
    trace_since_hours: float = DEFAULT_TRACE_SINCE_HOURS
    langsmith_limit: int = DEFAULT_LANGSMITH_LIMIT

    @property
    def queries_path(self) -> Path:
        return self.workdir / "queries.jsonl"

    @property
    def answers_path(self) -> Path:
        return self.workdir / "answers.jsonl"

    @property
    def rubrics_path(self) -> Path:
        return self.workdir / "rubrics.json"

    @property
    def scored_path(self) -> Path:
        return self.workdir / "scored.jsonl"

    @property
    def summary_json_path(self) -> Path:
        return self.workdir / "score_summary.json"

    @property
    def manual_review_csv_path(self) -> Path:
        return self.workdir / "manual_review.csv"


def ensure_workdir(path: Path) -> Path:
    """确保评测目录存在。"""
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_langsmith_project(default: str = "internet-number-qa") -> str:
    """读取 LangSmith 项目名。"""
    return (os.getenv("LANGSMITH_PROJECT") or default).strip() or default
