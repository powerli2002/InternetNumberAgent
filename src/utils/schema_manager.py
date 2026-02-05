from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from src.utils.logging_manager import logger


def resolve_core_ddl_path(project_root: Path) -> Path:
    """解析核心表 DDL 的默认路径。"""
    return (project_root / "database" / "core_schema.sql").resolve()


def _strip_line_comments(sql_text: str) -> str:
    """移除以 -- 开头的行注释，保持 DDL 分割稳定。"""
    lines: List[str] = []
    for line in sql_text.splitlines():
        if line.lstrip().startswith("--"):
            continue
        lines.append(line)
    return "\n".join(lines)


def split_sql_statements(sql_text: str) -> Iterable[str]:
    """按分号切分 SQL 语句，忽略空片段。"""
    cleaned = _strip_line_comments(sql_text)
    for chunk in cleaned.split(";"):
        stmt = chunk.strip()
        if stmt:
            yield stmt


def apply_core_ddl(conn, ddl_path: Path) -> None:
    """执行核心表 DDL，确保表结构一致。"""
    if not ddl_path.exists():
        raise FileNotFoundError(f"DDL 文件不存在: {ddl_path}")
    ddl_text = ddl_path.read_text(encoding="utf-8")
    statements = list(split_sql_statements(ddl_text))
    if not statements:
        raise RuntimeError(f"DDL 文件为空: {ddl_path}")
    try:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
        conn.commit()
        logger.info("核心表 DDL 已执行: %s", ddl_path)
    except Exception as exc:
        conn.rollback()
        raise RuntimeError(f"执行核心表 DDL 失败: {exc}") from exc
