#!/usr/bin/env python3
from __future__ import annotations

"""
agent/scripts 公共工具函数。

设计目标：
1. 统一脚本侧的配置读取、路径解析与数据库连接逻辑。
2. 避免每个脚本重复维护同一套基础代码。
3. 保持脚本在 `python -m ...` 与直接文件路径执行时都可用。
"""

import sys
import time
from pathlib import Path
from typing import Any

import psycopg2

from fusiondata.src.utils.config_loader import load_yaml_config


def ensure_project_root_on_path() -> Path:
    """
    将仓库根目录注入 `sys.path`。

    说明：
    - `agent/scripts/*.py` 既可能通过 `python -m` 运行，也可能直接运行文件路径。
    - 直接运行文件路径时，默认模块搜索路径不包含仓库根目录，需要手动补齐。
    """
    project_root = Path(__file__).resolve().parents[2]
    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)
    return project_root


# 在导入期执行一次，保证后续模块导入路径稳定。
PROJECT_ROOT = ensure_project_root_on_path()


def resolve_project_path(root_dir: Path, path_value: str) -> Path:
    """将相对路径解析为基于项目根目录的绝对路径。"""
    path = Path(path_value)
    return path if path.is_absolute() else (root_dir / path).resolve()


def build_postgres_connect_kwargs(cfg: dict[str, Any]) -> dict[str, Any]:
    """从配置中提取 psycopg2 连接参数。"""
    return {
        "database": cfg["postgresql_database"],
        "user": cfg["postgresql_user"],
        "password": cfg["postgresql_password"],
        "host": cfg["postgresql_host"],
        "port": cfg["postgresql_port"],
    }


def open_pg_connection(cfg: dict[str, Any]) -> psycopg2.extensions.connection:
    """按统一配置创建 PostgreSQL 连接。"""
    return psycopg2.connect(**build_postgres_connect_kwargs(cfg))


def wait_for_postgres(
    cfg: dict[str, Any], timeout_seconds: int, interval_seconds: int = 2
) -> None:
    """
    轮询等待 PostgreSQL 可连接。

    算法步骤：
    1) 在超时窗口内循环尝试建立连接；
    2) 若连接成功则立即返回；
    3) 若连接失败且未超时则 sleep 后重试；
    4) 若超时则抛出异常，中断后续导入流程。
    """
    deadline = time.time() + timeout_seconds
    while True:
        try:
            conn = open_pg_connection(cfg)
            conn.close()
            return
        except Exception as exc:
            if time.time() > deadline:
                raise RuntimeError(f"PostgreSQL wait timeout: {exc}") from exc
            time.sleep(interval_seconds)
