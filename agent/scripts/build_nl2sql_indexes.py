from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from agent.scripts.common import ensure_project_root_on_path
except ModuleNotFoundError:
    import sys

    project_root = Path(__file__).resolve().parents[2]
    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)
    from agent.scripts.common import ensure_project_root_on_path

# 兼容脚本路径直接执行，确保 `agent.*` 可导入。
ensure_project_root_on_path()

from agent.core.config import AgentConfig
from agent.tools.nl2sql_tool import NL2SQLTool


def _parse_tables(raw: str | None) -> list[str] | None:
    """解析逗号分隔表名参数。"""
    if not raw:
        return None
    tables = [item.strip() for item in raw.split(",") if item.strip()]
    return tables or None


def main() -> None:
    parser = argparse.ArgumentParser(description="预构建 NL2SQL 表/列检索索引")
    parser.add_argument("--tables", default=None, help="可选，逗号分隔表名")
    parser.add_argument("--skip-columns", action="store_true", help="仅构建表索引，不构建列索引")
    parser.add_argument("--force", action="store_true", help="强制重建索引")
    args = parser.parse_args()

    # 读取统一配置，保持 NL2SQL 在线调用与离线预构建参数一致。
    config = AgentConfig.load()
    tool = NL2SQLTool(
        postgres_url=config.postgres_url or "",
        allowed_tables=config.allowed_tables,
        milvus_host=config.milvus_host,
        milvus_port=config.milvus_port,
        milvus_collection=config.nl2sql_vector_collection,
        api_key=config.dashscope_api_key,
        base_url=config.dashscope_base_url,
        model=config.dashscope_model,
        embedding_backend=config.nl2sql_embedding_backend,
        embedding_model=config.nl2sql_embedding_model,
        embedding_device=config.nl2sql_embedding_device,
        embedding_batch_size=config.nl2sql_embedding_batch_size,
        embedding_normalize=config.nl2sql_embedding_normalize,
        index_cache_dir=config.nl2sql_index_cache_dir,
        enable_index_cache=True,
        force_rebuild_cache=config.nl2sql_index_cache_force_rebuild,
    )

    # 未显式指定表时，默认按 allowlist 全量构建。
    table_names = _parse_tables(args.tables) or config.allowed_tables
    result = tool.prepare_index_cache(
        table_names=table_names,
        build_tables=True,
        build_columns=not args.skip_columns,
        force=args.force,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
