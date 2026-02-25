#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

try:
    from agent.scripts.common import load_yaml_config, open_pg_connection, resolve_project_path
except ModuleNotFoundError:
    import sys

    project_root = Path(__file__).resolve().parents[2]
    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)
    from agent.scripts.common import load_yaml_config, open_pg_connection, resolve_project_path

from src.utils.schema_manager import apply_core_ddl, resolve_core_ddl_path
from src.utils.logging_manager import logger


def main() -> None:
    parser = argparse.ArgumentParser(description="Ensure core schema DDL in PostgreSQL")
    parser.add_argument("--config", default="conf/config.docker.yaml", help="YAML config path")
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument("--ddl-path", default=None, help="DDL file path (default: database/core_schema.sql)")
    args = parser.parse_args()

    root_dir = Path(args.root).resolve()
    config_path = Path(args.config).resolve()
    cfg = load_yaml_config(config_path)

    ddl_path = resolve_project_path(root_dir, args.ddl_path) if args.ddl_path else resolve_core_ddl_path(root_dir)

    # 统一 DDL 入口：确保 16 张核心表结构与字段类型保持一致。
    conn = open_pg_connection(cfg)
    try:
        apply_core_ddl(conn, ddl_path)
    finally:
        conn.close()

    logger.info("核心表结构已确保完成。")


if __name__ == "__main__":
    main()
