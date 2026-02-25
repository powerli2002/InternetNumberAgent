#!/usr/bin/env python3
from __future__ import annotations

"""
导入 16 张核心实体表到 PostgreSQL。

关键能力：
1. 可选在导入前自动应用统一 DDL；
2. 支持清理非核心表与核心表空库检测；
3. 支持单事务导入（默认）保证 16 表一致性。
"""

import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional

from psycopg2 import sql

try:
    from agent.scripts.common import (
        load_yaml_config,
        open_pg_connection,
        resolve_project_path,
        wait_for_postgres,
    )
except ModuleNotFoundError:
    import sys

    project_root = Path(__file__).resolve().parents[2]
    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)
    from agent.scripts.common import (
        load_yaml_config,
        open_pg_connection,
        resolve_project_path,
        wait_for_postgres,
    )

from src.utils.entity_persistence import EntityPersistence
from src.utils.logging_manager import logger
from src.utils.schema_manager import apply_core_ddl, resolve_core_ddl_path

CORE_TABLES = [
    "as_entity",
    "asn_entity",
    "country_entity",
    "industry_entity",
    "ip_bgp_entity",
    "ip_inetnum_entity",
    "ip_rdap_entity",
    "ip_route_entity",
    "ipv4_entity",
    "ipv6_bgp_entity",
    "ipv6_entity",
    "ipv6_inetnum_entity",
    "ipv6_rdap_entity",
    "ipv6_route_entity",
    "org_entity",
    "website_entity",
]
CORE_TABLE_SET = set(CORE_TABLES)
PROTECTED_TABLES = {"agent_threads", "agent_messages"}

# 导入计划：按固定顺序执行，避免实体引用关系出现前后依赖错位。
CORE_IMPORT_PLAN: list[tuple[tuple[str, ...], str, str]] = [
    (("as_entity",), "as_entity_prst", "as_entity"),
    (("country_entity",), "country_entity_prst", "country_entity"),
    (("org_entity",), "org_entity_prst", "org_entity"),
    (("industry_entity",), "industry_entity_prst", "industry_entity"),
    (("ip_bgp_entity",), "ip_bgp_entity_prst", "ip_bgp_entity"),
    (("ipv6_bgp_entity",), "ipv6_bgp_entity_prst", "ipv6_bgp_entity"),
    (("ip_inetnum_entity",), "ip_inetnum_entity_prst", "ip_inetnum_entity"),
    (("ipv6_inetnum_entity",), "ipv6_inetnum_entity_prst", "ipv6_inetnum_entity"),
    (("ip_rdap_entity",), "ip_rdap_entity_prst", "ip_rdap_entity"),
    (("ipv6_rdap_entity",), "ipv6_rdap_entity_prst", "ipv6_rdap_entity"),
    (("ip_route_entity",), "ip_route_entity_prst", "ip_route_entity"),
    (("ipv6_route_entity",), "ipv6_route_entity_prst", "ipv6_route_entity"),
    (("asn_entity",), "as_delegate_entity_prst", "asn_entity"),
    (("ipv4_entity",), "ip_delegate_entity_prst", "ipv4_entity"),
    (("ipv6_entity",), "ipv6_delegate_entity_prst", "ipv6_entity"),
    (("website_entity_base", "domain_cn"), "website_entity_prst", "website_entity_base"),
]


def build_core_paths(output_dir: Path, date: str) -> dict:
    fmt_dir = output_dir / "format"
    return {
        "as_entity": fmt_dir / f"as_entity_{date}.csv",
        "country_entity": fmt_dir / f"country_entity_{date}.csv",
        "org_entity": fmt_dir / f"org_entity_{date}.csv",
        "industry_entity": fmt_dir / f"industry_entity_{date}.csv",
        "ip_bgp_entity": fmt_dir / f"ip_bgp_entity_{date}.csv",
        "ipv6_bgp_entity": fmt_dir / f"ipv6_bgp_entity_{date}.csv",
        "ip_inetnum_entity": fmt_dir / "ip_inetnum_entity.csv",
        "ipv6_inetnum_entity": fmt_dir / "ipv6_inetnum_entity.csv",
        "ip_rdap_entity": fmt_dir / "ip_rdap_entity.csv",
        "ipv6_rdap_entity": fmt_dir / "ipv6_rdap_entity.csv",
        "ip_route_entity": fmt_dir / "ip_route_entity.csv",
        "ipv6_route_entity": fmt_dir / "ipv6_route_entity.csv",
        "asn_entity": fmt_dir / "asn_entity.csv",
        "ipv4_entity": fmt_dir / "ipv4_entity.csv",
        "ipv6_entity": fmt_dir / "ipv6_entity.csv",
        "website_entity_base": fmt_dir / "website_entity_base.csv",
        "domain_cn": fmt_dir / "domain_cn.csv",
    }


def ensure_files_exist(paths: list[Path], missing: list[str]) -> bool:
    ok = True
    for p in paths:
        if not p.exists():
            missing.append(str(p))
            ok = False
    return ok


def list_public_tables(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public';")
        return [row[0] for row in cur.fetchall()]


def drop_non_core_tables(conn) -> list[str]:
    existing = list_public_tables(conn)
    to_drop = [t for t in existing if t not in CORE_TABLE_SET and t not in PROTECTED_TABLES]
    if not to_drop:
        return []
    with conn.cursor() as cur:
        for table in to_drop:
            cur.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE;").format(sql.Identifier(table)))
    conn.commit()
    return to_drop


def drop_audit_triggers(conn) -> None:
    # 关闭审计触发器，避免自动生成 _audit 表
    try:
        with conn.cursor() as cur:
            cur.execute("DROP EVENT TRIGGER IF EXISTS create_audit_with_timestamp;")
            cur.execute("DROP EVENT TRIGGER IF EXISTS trg_drop_dependent_functions;")
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.warning("审计触发器删除失败，将继续执行后续流程：%s", exc)


def get_table_counts(conn, tables: list[str], existing: set[str]) -> dict[str, Optional[int]]:
    counts: dict[str, Optional[int]] = {}
    with conn.cursor() as cur:
        for table in tables:
            if table not in existing:
                counts[table] = None
                continue
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {};").format(sql.Identifier(table)))
            counts[table] = cur.fetchone()[0]
    return counts


def import_core_tables(ep: EntityPersistence, core_paths: dict[str, Path], missing: list[str], chunk_size: int) -> None:
    """
    按导入计划执行 16 张核心表导入。

    算法步骤：
    1) 按 `CORE_IMPORT_PLAN` 顺序遍历每个实体导入任务；
    2) 先校验该任务依赖的 CSV 文件是否齐全；
    3) 文件齐全则调用 `EntityPersistence` 对应导入方法；
    4) 文件缺失则记录到 `missing`，由上层决定是否回滚。
    """
    for required_keys, persist_method, source_key in CORE_IMPORT_PLAN:
        required_paths = [core_paths[key] for key in required_keys]
        if not ensure_files_exist(required_paths, missing):
            continue
        importer = getattr(ep, persist_method)
        importer(str(core_paths[source_key]), chunksize=chunk_size)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load core CSVs into PostgreSQL")
    parser.add_argument("--config", default="conf/config.docker.yaml", help="YAML config path")
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument("--date", default=None, help="Date for entity persistence")
    parser.add_argument("--cleanup-only", action="store_true", help="Drop non-core tables and exit")
    parser.add_argument("--ddl-path", default=None, help="Core DDL file path, default database/core_schema.sql")
    parser.add_argument("--skip-ddl", action="store_true", help="Skip applying core DDL before import")
    parser.add_argument(
        "--ensure-core",
        action="store_true",
        help="Drop non-core tables, then import if core tables are missing or empty",
    )
    parser.add_argument("--chunk-size", type=int, default=100000, help="CSV chunk size, 0 means no chunking")
    parser.add_argument("--wait-seconds", type=int, default=120, help="Wait seconds for DB ready")
    parser.add_argument(
        "--single-transaction",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否使用单事务导入 16 张核心表（默认开启）",
    )
    args = parser.parse_args()

    root_dir = Path(args.root).resolve()
    config_path = Path(args.config).resolve()
    cfg = load_yaml_config(config_path)
    date = args.date or cfg.get("current_date") or datetime.now().strftime("%Y-%m-%d")
    output_dir = resolve_project_path(root_dir, cfg.get("output_dir", "./data/"))
    ddl_path = resolve_project_path(root_dir, args.ddl_path) if args.ddl_path else resolve_core_ddl_path(root_dir)

    wait_for_postgres(cfg, args.wait_seconds)

    should_apply_ddl = not args.skip_ddl and not args.cleanup_only
    if should_apply_ddl and not (args.cleanup_only or args.ensure_core):
        conn = open_pg_connection(cfg)
        try:
            apply_core_ddl(conn, ddl_path)
        finally:
            conn.close()

    if args.cleanup_only or args.ensure_core:
        conn = open_pg_connection(cfg)
        try:
            if should_apply_ddl:
                apply_core_ddl(conn, ddl_path)
            drop_audit_triggers(conn)
            dropped = drop_non_core_tables(conn)
            if dropped:
                logger.info("已删除非核心表：%s", dropped)
            existing = set(list_public_tables(conn))
            counts = get_table_counts(conn, CORE_TABLES, existing)
            missing = [t for t in CORE_TABLES if t not in existing]
            total_rows = sum(v for v in counts.values() if isinstance(v, int))
            if args.cleanup_only:
                if missing:
                    logger.warning("核心表缺失：%s", missing)
                logger.info("核心表总行数：%s", total_rows)
                return
            if missing or total_rows == 0:
                logger.info("核心表缺失或无数据，开始导入 16 张实体表")
            else:
                logger.info("核心表已存在且有数据，跳过导入")
                return
        finally:
            conn.close()

    core_paths = build_core_paths(output_dir, date)
    missing: list[str] = []

    ep = EntityPersistence(str(config_path), date)
    if args.single_transaction:
        # 单事务语义：
        # 1) 绑定同一连接给所有导入操作；
        # 2) 任一实体失败或文件缺失时回滚；
        # 3) 全部成功后一次性提交，保证 16 表一致性。
        conn = open_pg_connection(cfg)
        conn.autocommit = False
        ep.bind_connection(conn)
        try:
            import_core_tables(ep, core_paths, missing, args.chunk_size)
            if missing:
                raise RuntimeError(f"核心表导入文件缺失，触发回滚：{missing}")
            conn.commit()
            logger.info("核心表单事务导入完成，已提交。")
        except Exception as exc:
            conn.rollback()
            logger.error("核心表单事务导入失败，已回滚：%s", exc)
            raise
        finally:
            ep.unbind_connection()
            conn.close()
    else:
        # 非单事务模式仅用于兼容旧的大批量历史导入场景。
        import_core_tables(ep, core_paths, missing, args.chunk_size)

    if missing:
        logger.warning("缺失 CSV 文件：%s", missing)


if __name__ == "__main__":
    main()
