"""
Text2SQL 批量评测脚本。

功能：
1. 读取自然语言-期望 SQL 数据集（JSON）。
2. 调用 agent/demo/text2sql.py 中的 Text2SQLEngine 生成 SQL。
3. 分别执行期望 SQL 与真实 SQL，输出“自然语言-期望sql结果-真实sql结果”。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.demo.text2sql import (
    AgentConfig,
    DEFAULT_LOCAL_BGE_MODEL,
    DEFAULT_MILVUS_HOST,
    DEFAULT_MILVUS_PORT,
    SQLGuard,
    TABLE_SCHEMA,
    Text2SQLEngine,
    Text2SQLSettings,
)


def _load_dataset(path: Path) -> List[Dict[str, Any]]:
    """加载评测集 JSON 文件。"""
    if not path.exists():
        raise RuntimeError(f"评测集不存在: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError("评测集格式错误，必须是 JSON 数组。")
    return data


def _to_jsonable(value: Any) -> Any:
    """把数据库结果转成可 JSON 序列化对象。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]
    return str(value)


def _run_sql_result(
    engine: Text2SQLEngine,
    guard: SQLGuard,
    sql: str,
    timeout_ms: int,
    max_rows: int,
    preview_rows: int,
) -> Dict[str, Any]:
    """执行 SQL，并返回精简结果（列名 + 前 N 行）。"""
    sql = (sql or "").strip()
    if not sql:
        return {"error": "SQL 为空"}
    try:
        safe_sql, _ = guard.sanitize(sql)
        result = engine.db.run_sql(sql=safe_sql, timeout_ms=timeout_ms, max_rows=max_rows)
        rows = result.get("rows") or []
        preview = rows[: max(1, int(preview_rows))]
        return {
            "columns": result.get("columns") or [],
            "rows": [_to_jsonable(list(row)) for row in preview],
            "truncated": bool(result.get("truncated")) or len(rows) > len(preview),
            "safe_sql": safe_sql,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _build_parser() -> argparse.ArgumentParser:
    """评测脚本参数。"""
    parser = argparse.ArgumentParser(description="批量执行 Text2SQL 评测。")
    parser.add_argument(
        "--dataset",
        default=str(PROJECT_ROOT / "agent" / "demo" / "dataset" / "text2sql_eval_dataset.json"),
        help="评测集 JSON 文件路径。",
    )
    parser.add_argument(
        "--output-json",
        default=str(PROJECT_ROOT / "agent" / "demo" / "output" / "text2sql_eval_results.json"),
        help="详细评测结果输出路径（JSON）。",
    )
    parser.add_argument(
        "--output-tsv",
        default=str(PROJECT_ROOT / "agent" / "demo" / "output" / "text2sql_eval_results.tsv"),
        help="三列输出路径（自然语言-期望sql结果-真实sql结果）。",
    )
    parser.add_argument("--max-cases", type=int, default=20, help="最大评测条数。")
    parser.add_argument("--postgres-url", default="", help="覆盖 PostgreSQL 连接串。")
    parser.add_argument("--api-key", default="", help="覆盖百炼 API Key。")
    parser.add_argument("--milvus-host", default=DEFAULT_MILVUS_HOST, help=f"Milvus 主机（默认 {DEFAULT_MILVUS_HOST}）。")
    parser.add_argument("--milvus-port", type=int, default=DEFAULT_MILVUS_PORT, help=f"Milvus 端口（默认 {DEFAULT_MILVUS_PORT}）。")
    parser.add_argument("--base-url", default="https://dashscope.aliyuncs.com/compatible-mode/v1", help="覆盖百炼兼容 API Base URL。")
    parser.add_argument("--model", default="qwen-turbo", help="覆盖 LLM 模型名。")
    parser.add_argument(
        "--embedding-backend",
        choices=["local_bge", "dashscope"],
        default="local_bge",
        help="embedding 后端。",
    )
    parser.add_argument(
        "--embedding-model",
        default=DEFAULT_LOCAL_BGE_MODEL,
        help=f"embedding 模型名或本地目录（默认 {DEFAULT_LOCAL_BGE_MODEL}）。",
    )
    parser.add_argument("--embedding-device", choices=["cuda"], default="cuda", help="embedding 设备（固定 cuda）。")
    parser.add_argument("--embedding-batch-size", type=int, default=2, help="embedding 批大小。")
    parser.add_argument("--disable-embedding-normalize", action="store_true", help="关闭 embedding 归一化。")
    parser.add_argument(
        "--print-llama-context",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="打印 LlamaIndex 默认拼装的表结构上下文（输出到 stderr）。",
    )
    parser.add_argument(
        "--column-retrieval",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否开启列检索（默认开启）。",
    )
    parser.add_argument("--preview-rows", type=int, default=5, help="结果预览行数。")
    return parser


def main() -> int:
    """执行批量评测并写出结果文件。"""
    args = _build_parser().parse_args()

    cfg = AgentConfig.load(project_root=PROJECT_ROOT)
    # 按要求仅使用代码参数/配置文件，不读取环境变量兜底。
    postgres_url = args.postgres_url or cfg.postgres_url or ""
    api_key = args.api_key or cfg.dashscope_api_key or ""
    if not postgres_url:
        raise RuntimeError("未找到 POSTGRES_URL，无法连接 PostgreSQL。")
    if not api_key:
        raise RuntimeError("未找到 DASHSCOPE_API_KEY，无法调用 LLM。")

    dataset = _load_dataset(Path(args.dataset))
    cases = dataset[: max(1, int(args.max_cases))]
    allowed_tables = list(cfg.allowed_tables) if cfg.allowed_tables else list(TABLE_SCHEMA.keys())

    settings = Text2SQLSettings(
        postgres_url=postgres_url,
        api_key=api_key,
        base_url=args.base_url,
        llm_model=args.model,
        embedding_backend=args.embedding_backend,
        embedding_model=args.embedding_model,
        embedding_device=args.embedding_device,
        embedding_batch_size=max(1, int(args.embedding_batch_size)),
        embedding_normalize=not args.disable_embedding_normalize,
        print_llama_context=args.print_llama_context,
        allowed_tables=allowed_tables,
        milvus_host=str(args.milvus_host or DEFAULT_MILVUS_HOST),
        milvus_port=int(args.milvus_port or DEFAULT_MILVUS_PORT),
        visualize_pipeline=False,
        enable_column_retrieval=bool(args.column_retrieval),
        max_rows=cfg.nl2sql_max_rows,
        statement_timeout_ms=cfg.nl2sql_statement_timeout_ms,
        max_sql_length=cfg.nl2sql_max_sql_length,
        allow_subquery=cfg.nl2sql_allow_subquery,
    )
    engine = Text2SQLEngine(settings=settings)
    guard = SQLGuard(
        allowed_tables=allowed_tables,
        max_rows=settings.max_rows,
        max_sql_length=settings.max_sql_length,
        allow_subquery=settings.allow_subquery,
    )

    output_rows: List[Dict[str, Any]] = []
    for idx, sample in enumerate(cases, start=1):
        question = str(sample.get("question", "")).strip()
        expected_sql = str(sample.get("expected_sql", "")).strip()
        generated_sql = ""
        generate_error = ""
        if question:
            try:
                generated_sql = engine.text_to_sql(
                    question=question,
                    tables=allowed_tables,
                    enable_column_retrieval=bool(args.column_retrieval),
                    execute_sql=False,
                )
            except Exception as exc:
                generate_error = str(exc)
        else:
            generate_error = "问题为空"

        expected_sql_result = _run_sql_result(
            engine=engine,
            guard=guard,
            sql=expected_sql,
            timeout_ms=settings.statement_timeout_ms,
            max_rows=settings.max_rows,
            preview_rows=args.preview_rows,
        )
        actual_sql_result = _run_sql_result(
            engine=engine,
            guard=guard,
            sql=generated_sql,
            timeout_ms=settings.statement_timeout_ms,
            max_rows=settings.max_rows,
            preview_rows=args.preview_rows,
        )
        if generate_error:
            actual_sql_result = {"error": generate_error}

        row = {
            "id": sample.get("id", idx),
            "question": question,
            "expected_sql": expected_sql,
            "generated_sql": generated_sql,
            "trace": engine.last_trace() if generated_sql else {},
            "expected_sql_result": expected_sql_result,
            "actual_sql_result": actual_sql_result,
        }
        output_rows.append(row)
        print(f"[eval] {idx}/{len(cases)} 完成: {question}")

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(output_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    output_tsv = Path(args.output_tsv)
    output_tsv.parent.mkdir(parents=True, exist_ok=True)
    with output_tsv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["自然语言", "期望sql结果", "真实sql结果"])
        for row in output_rows:
            writer.writerow(
                [
                    row["question"],
                    json.dumps(row["expected_sql_result"], ensure_ascii=False),
                    json.dumps(row["actual_sql_result"], ensure_ascii=False),
                ]
            )

    print(f"[eval] 详细结果已写入: {output_json}")
    print(f"[eval] 三列输出已写入: {output_tsv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
