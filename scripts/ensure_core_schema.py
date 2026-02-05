#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import psycopg2
import yaml

from src.utils.schema_manager import apply_core_ddl, resolve_core_ddl_path
from src.utils.logging_manager import logger


def load_config(config_path: Path) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def resolve_path(root_dir: Path, path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else (root_dir / path).resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ensure core schema DDL in PostgreSQL")
    parser.add_argument("--config", default="conf/config.docker.yaml", help="YAML config path")
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument("--ddl-path", default=None, help="DDL file path (default: database/core_schema.sql)")
    args = parser.parse_args()

    root_dir = Path(args.root).resolve()
    config_path = Path(args.config).resolve()
    cfg = load_config(config_path)

    ddl_path = resolve_path(root_dir, args.ddl_path) if args.ddl_path else resolve_core_ddl_path(root_dir)

    conn = psycopg2.connect(
        database=cfg["postgresql_database"],
        user=cfg["postgresql_user"],
        password=cfg["postgresql_password"],
        host=cfg["postgresql_host"],
        port=cfg["postgresql_port"],
    )
    try:
        apply_core_ddl(conn, ddl_path)
    finally:
        conn.close()

    logger.info("核心表结构已确保完成。")


if __name__ == "__main__":
    main()
