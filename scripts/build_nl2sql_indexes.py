from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 兼容以脚本路径直接执行：将项目根目录加入模块搜索路径
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.core.config import AgentConfig
from agent.tools.nl2sql_tool import NL2SQLTool


def _parse_tables(raw: str | None) -> list[str] | None:
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

    config = AgentConfig.load()
    tool = NL2SQLTool(
        postgres_url=config.postgres_url or "",
        allowed_tables=config.allowed_tables,
        api_key=config.dashscope_api_key,
        base_url=config.dashscope_base_url,
        model=config.dashscope_model,
        embedding_model=config.dashscope_embedding_model,
        index_cache_dir=config.nl2sql_index_cache_dir,
        enable_index_cache=True,
        force_rebuild_cache=config.nl2sql_index_cache_force_rebuild,
    )

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
