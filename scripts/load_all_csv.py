#!/usr/bin/env python3
import argparse
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import psycopg2
from psycopg2 import sql
import yaml

from src.utils.entity_persistence import EntityPersistence
from src.utils.logging_manager import logger

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


def load_config(config_path: Path) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def resolve_path(root_dir: Path, path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else (root_dir / path).resolve()


def wait_for_db(cfg: dict, timeout_seconds: int) -> None:
    # 等待数据库可用，避免首次连接失败
    deadline = time.time() + timeout_seconds
    while True:
        try:
            conn = psycopg2.connect(
                database=cfg["postgresql_database"],
                user=cfg["postgresql_user"],
                password=cfg["postgresql_password"],
                host=cfg["postgresql_host"],
                port=cfg["postgresql_port"],
            )
            conn.close()
            return
        except Exception as exc:
            if time.time() > deadline:
                raise RuntimeError(f"PostgreSQL wait timeout: {exc}") from exc
            time.sleep(2)


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Load core CSVs into PostgreSQL")
    parser.add_argument("--config", default="conf/config.docker.yaml", help="YAML config path")
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument("--date", default=None, help="Date for entity persistence")
    parser.add_argument("--cleanup-only", action="store_true", help="Drop non-core tables and exit")
    parser.add_argument(
        "--ensure-core",
        action="store_true",
        help="Drop non-core tables, then import if core tables are missing or empty",
    )
    parser.add_argument("--chunk-size", type=int, default=100000, help="CSV chunk size, 0 means no chunking")
    parser.add_argument("--wait-seconds", type=int, default=120, help="Wait seconds for DB ready")
    args = parser.parse_args()

    root_dir = Path(args.root).resolve()
    config_path = Path(args.config).resolve()
    cfg = load_config(config_path)
    date = args.date or cfg.get("current_date") or datetime.now().strftime("%Y-%m-%d")
    output_dir = resolve_path(root_dir, cfg.get("output_dir", "./data/"))

    wait_for_db(cfg, args.wait_seconds)

    if args.cleanup_only or args.ensure_core:
        conn = psycopg2.connect(
            database=cfg["postgresql_database"],
            user=cfg["postgresql_user"],
            password=cfg["postgresql_password"],
            host=cfg["postgresql_host"],
            port=cfg["postgresql_port"],
        )
        try:
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

    if ensure_files_exist([core_paths["as_entity"]], missing):
        ep.as_entity_prst(str(core_paths["as_entity"]), chunksize=args.chunk_size)
    if ensure_files_exist([core_paths["country_entity"]], missing):
        ep.country_entity_prst(str(core_paths["country_entity"]), chunksize=args.chunk_size)
    if ensure_files_exist([core_paths["org_entity"]], missing):
        ep.org_entity_prst(str(core_paths["org_entity"]), chunksize=args.chunk_size)
    if ensure_files_exist([core_paths["industry_entity"]], missing):
        ep.industry_entity_prst(str(core_paths["industry_entity"]), chunksize=args.chunk_size)
    if ensure_files_exist([core_paths["ip_bgp_entity"]], missing):
        ep.ip_bgp_entity_prst(str(core_paths["ip_bgp_entity"]), chunksize=args.chunk_size)
    if ensure_files_exist([core_paths["ipv6_bgp_entity"]], missing):
        ep.ipv6_bgp_entity_prst(str(core_paths["ipv6_bgp_entity"]), chunksize=args.chunk_size)
    if ensure_files_exist([core_paths["ip_inetnum_entity"]], missing):
        ep.ip_inetnum_entity_prst(str(core_paths["ip_inetnum_entity"]), chunksize=args.chunk_size)
    if ensure_files_exist([core_paths["ipv6_inetnum_entity"]], missing):
        ep.ipv6_inetnum_entity_prst(str(core_paths["ipv6_inetnum_entity"]), chunksize=args.chunk_size)
    if ensure_files_exist([core_paths["ip_rdap_entity"]], missing):
        ep.ip_rdap_entity_prst(str(core_paths["ip_rdap_entity"]), chunksize=args.chunk_size)
    if ensure_files_exist([core_paths["ipv6_rdap_entity"]], missing):
        ep.ipv6_rdap_entity_prst(str(core_paths["ipv6_rdap_entity"]), chunksize=args.chunk_size)
    if ensure_files_exist([core_paths["ip_route_entity"]], missing):
        ep.ip_route_entity_prst(str(core_paths["ip_route_entity"]), chunksize=args.chunk_size)
    if ensure_files_exist([core_paths["ipv6_route_entity"]], missing):
        ep.ipv6_route_entity_prst(str(core_paths["ipv6_route_entity"]), chunksize=args.chunk_size)
    if ensure_files_exist([core_paths["asn_entity"]], missing):
        ep.as_delegate_entity_prst(str(core_paths["asn_entity"]), chunksize=args.chunk_size)
    if ensure_files_exist([core_paths["ipv4_entity"]], missing):
        ep.ip_delegate_entity_prst(str(core_paths["ipv4_entity"]), chunksize=args.chunk_size)
    if ensure_files_exist([core_paths["ipv6_entity"]], missing):
        ep.ipv6_delegate_entity_prst(str(core_paths["ipv6_entity"]), chunksize=args.chunk_size)
    if ensure_files_exist([core_paths["website_entity_base"], core_paths["domain_cn"]], missing):
        ep.website_entity_prst(str(core_paths["website_entity_base"]), chunksize=args.chunk_size)

    if missing:
        logger.warning("Missing CSV files: %s", missing)


if __name__ == "__main__":
    main()
