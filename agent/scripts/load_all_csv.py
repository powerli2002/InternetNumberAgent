#!/usr/bin/env python3
from __future__ import annotations

"""
导入 16 张核心实体表到 PostgreSQL，并默认同步 Neo4j 图谱。

关键能力：
1. 可选在导入前自动应用统一 DDL；
2. 支持清理非核心表与核心表空库检测；
3. 支持 PostgreSQL + Neo4j 双库一致性导入（prepared transaction + Neo4j 单事务）。
4. 导入入库阶段统一执行列名规范化（小写 + 特殊字符转下划线）。
"""

import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from neo4j import GraphDatabase
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

from agent.core.config import AgentConfig
from agent.scripts.neo4j_graph_loader import Neo4jImportOptions, run_import_pipeline

from fusiondata.src.utils.entity_persistence import EntityPersistence
from fusiondata.src.utils.logging_manager import logger
from fusiondata.src.utils.schema_manager import apply_core_ddl, resolve_core_ddl_path

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


class _PreparedStateError(RuntimeError):
    """PG 已进入 PREPARED 阶段后的不可重试错误。"""


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


def resolve_active_tables(skip_website: bool, skip_industry: bool) -> list[str]:
    """根据命令行参数解析当前导入目标核心表集合。"""
    return [
        table
        for table in CORE_TABLES
        if not (skip_website and table == "website_entity")
        and not (skip_industry and table == "industry_entity")
    ]


def resolve_import_plan(skip_website: bool, skip_industry: bool) -> list[tuple[tuple[str, ...], str, str]]:
    """根据命令行参数解析当前导入计划。"""
    filtered_plan: list[tuple[tuple[str, ...], str, str]] = []
    for required_keys, persist_method, source_key in CORE_IMPORT_PLAN:
        if skip_website and persist_method == "website_entity_prst":
            continue
        if skip_industry and persist_method == "industry_entity_prst":
            continue
        filtered_plan.append((required_keys, persist_method, source_key))
    return filtered_plan


def import_tables_by_plan(
    ep: EntityPersistence,
    core_paths: dict[str, Path],
    missing: list[str],
    chunk_size: int,
    import_plan: list[tuple[tuple[str, ...], str, str]],
) -> None:
    """
    按解析后的导入计划执行实体导入。

    算法步骤：
    1) 按 `import_plan` 顺序遍历每个实体导入任务；
    2) 先校验该任务依赖的 CSV 文件是否齐全；
    3) 文件齐全则调用 `EntityPersistence` 对应导入方法；
    4) 文件缺失则记录到 `missing`，由上层决定是否回滚。
    """
    for required_keys, persist_method, source_key in import_plan:
        required_paths = [core_paths[key] for key in required_keys]
        if not ensure_files_exist(required_paths, missing):
            continue
        importer = getattr(ep, persist_method)
        importer(str(core_paths[source_key]), chunksize=chunk_size)


def _build_prepared_gid(date: str) -> str:
    """构造两阶段提交事务 ID。"""
    return f"fusion_load_{date}_{uuid4().hex[:8]}"


def _check_prepared_transactions_enabled(conn) -> None:
    """校验 PostgreSQL 是否开启 prepared transactions。"""
    with conn.cursor() as cur:
        cur.execute("SHOW max_prepared_transactions;")
        row = cur.fetchone()
    value = int(row[0]) if row and row[0] is not None else 0
    if value <= 0:
        raise RuntimeError("PostgreSQL `max_prepared_transactions` 未开启，无法执行双库一致性导入。")


def _prepare_transaction(conn, gid: str) -> None:
    """将当前 PostgreSQL 事务推进到 PREPARED 状态。"""
    with conn.cursor() as cur:
        cur.execute("PREPARE TRANSACTION %s;", (gid,))


def _commit_prepared(cfg: dict, gid: str) -> None:
    """提交 PREPARED 事务。"""
    conn = open_pg_connection(cfg)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("COMMIT PREPARED %s;", (gid,))
    finally:
        conn.close()


def _rollback_prepared(cfg: dict, gid: str) -> None:
    """回滚 PREPARED 事务。"""
    conn = open_pg_connection(cfg)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("ROLLBACK PREPARED %s;", (gid,))
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="导入核心 CSV 到 PostgreSQL，并默认同步导入 Neo4j 图谱")
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
    parser.add_argument("--skip-website", action="store_true", help="PostgreSQL 导入阶段跳过 website_entity")
    parser.add_argument("--skip-industry", action="store_true", help="PostgreSQL 导入阶段跳过 industry_entity")
    parser.add_argument(
        "--single-transaction",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否使用单事务导入 16 张核心表（默认开启）",
    )
    parser.add_argument("--no-neo4j", action="store_true", help="仅导入 PostgreSQL，不执行 Neo4j 图导入")
    parser.add_argument("--neo4j-uri", default=None, help="Neo4j Bolt URI（默认读取 AgentConfig）")
    parser.add_argument("--neo4j-user", default=None, help="Neo4j 用户名（默认读取 AgentConfig）")
    parser.add_argument("--neo4j-password", default=None, help="Neo4j 密码（默认读取 AgentConfig）")
    parser.add_argument("--neo4j-batch-size", type=int, default=1000, help="Neo4j 导入每批写入行数")
    parser.add_argument("--include-website", action="store_true", help="Neo4j 导入 website 图数据")
    parser.add_argument("--include-industry", action="store_true", help="Neo4j 导入 industry 图数据")
    parser.add_argument("--skip-as-relations", action="store_true", help="Neo4j 跳过 AS 上下游/对等关系边")
    parser.add_argument("--neo4j-no-progress", action="store_true", help="Neo4j 导入禁用进度条")
    parser.add_argument("--neo4j-max-retries", type=int, default=1, help="Neo4j 导入失败后的最大重试次数（默认 1）")
    parser.add_argument(
        "--neo4j-single-transaction",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Neo4j 是否启用单事务导入（双库一致性模式下必须为 true）",
    )
    args = parser.parse_args()

    if not args.no_neo4j and not args.single_transaction:
        raise RuntimeError("启用 Neo4j 联合导入时，`--single-transaction` 必须开启。")
    if not args.no_neo4j and not args.neo4j_single_transaction:
        raise RuntimeError("双库一致性模式要求 `--neo4j-single-transaction` 必须开启。")
    if args.skip_website and args.include_website and not args.no_neo4j:
        raise RuntimeError("已跳过 website_entity 的 PostgreSQL 导入，不能同时启用 `--include-website`。")
    if args.skip_industry and args.include_industry and not args.no_neo4j:
        raise RuntimeError("已跳过 industry_entity 的 PostgreSQL 导入，不能同时启用 `--include-industry`。")

    active_tables = resolve_active_tables(skip_website=args.skip_website, skip_industry=args.skip_industry)
    import_plan = resolve_import_plan(skip_website=args.skip_website, skip_industry=args.skip_industry)

    root_dir = Path(args.root).resolve()
    config_path = Path(args.config).resolve()
    cfg = load_yaml_config(config_path)
    date = args.date or cfg.get("current_date") or datetime.now().strftime("%Y-%m-%d")
    output_dir = resolve_project_path(root_dir, cfg.get("output_dir", "./fusiondata/data/"))
    ddl_path = resolve_project_path(root_dir, args.ddl_path) if args.ddl_path else resolve_core_ddl_path(root_dir)
    logger.info("导入阶段启用列名规范化策略：lowercase + underscore")
    if args.skip_website or args.skip_industry:
        skipped_entities = []
        if args.skip_website:
            skipped_entities.append("website_entity")
        if args.skip_industry:
            skipped_entities.append("industry_entity")
        logger.info("本次 PostgreSQL 导入跳过实体：%s", skipped_entities)

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
            counts = get_table_counts(conn, active_tables, existing)
            missing = [t for t in active_tables if t not in existing]
            total_rows = sum(v for v in counts.values() if isinstance(v, int))
            if args.cleanup_only:
                if missing:
                    logger.warning("核心表缺失：%s", missing)
                logger.info("核心表总行数：%s", total_rows)
                return
            if missing or total_rows == 0:
                logger.info("核心表缺失或无数据，开始导入 %s 张实体表", len(active_tables))
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
        # 3) 全部成功后一次性提交，保证当前导入目标表一致性。
        conn = open_pg_connection(cfg)
        conn.autocommit = False
        ep.bind_connection(conn)
        try:
            import_tables_by_plan(ep, core_paths, missing, args.chunk_size, import_plan)
            if missing:
                raise RuntimeError(f"核心表导入文件缺失，触发回滚：{missing}")

            if args.no_neo4j:
                conn.commit()
                logger.info("核心表单事务导入完成，已提交（未执行 Neo4j 导入）。")
            else:
                _check_prepared_transactions_enabled(conn)
                gid = _build_prepared_gid(date)
                agent_cfg = AgentConfig.load(project_root=root_dir)
                neo4j_uri = args.neo4j_uri or agent_cfg.neo4j_uri
                neo4j_user = args.neo4j_user or agent_cfg.neo4j_user
                neo4j_password = args.neo4j_password or agent_cfg.neo4j_password
                neo4j_options = Neo4jImportOptions(
                    batch_size=max(1, int(args.neo4j_batch_size)),
                    include_website=bool(args.include_website),
                    include_industry=bool(args.include_industry),
                    no_progress=bool(args.neo4j_no_progress),
                    skip_as_relations=bool(args.skip_as_relations),
                    single_transaction=True,
                )
                max_retries = max(0, int(args.neo4j_max_retries))
                attempts = max_retries + 1
                logger.info("开始双库一致性导入：gid=%s，Neo4j 最多尝试 %s 次。", gid, attempts)
                prepared = False

                for attempt in range(1, attempts + 1):
                    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
                    try:
                        with driver.session() as session:
                            tx = session.begin_transaction()
                            try:
                                run_import_pipeline(conn, tx, neo4j_options)
                                _prepare_transaction(conn, gid)
                                prepared = True
                                try:
                                    tx.commit()
                                except Exception as exc:
                                    _rollback_prepared(cfg, gid)
                                    prepared = False
                                    raise _PreparedStateError(f"Neo4j 事务提交失败，已回滚 PG PREPARED 事务: {exc}") from exc
                            except Exception:
                                tx.rollback()
                                raise

                        try:
                            _commit_prepared(cfg, gid)
                        except Exception as exc:
                            raise _PreparedStateError(f"COMMIT PREPARED 执行失败，需人工核查事务状态 gid={gid}: {exc}") from exc
                        prepared = False
                        logger.info("双库一致性导入成功：gid=%s。", gid)
                        break
                    except Exception as exc:
                        if prepared:
                            _rollback_prepared(cfg, gid)
                            prepared = False
                        if isinstance(exc, _PreparedStateError):
                            logger.error("双库一致性导入进入 PREPARED 阶段后失败，不执行自动重试：%s", exc)
                            raise
                        if attempt >= attempts:
                            conn.rollback()
                            logger.error("Neo4j 导入失败且重试耗尽，PG 与 Neo4j 均已回滚到旧快照：%s", exc)
                            raise
                        logger.warning("Neo4j 导入失败，将重试（%s/%s）：%s", attempt, attempts, exc)
                    finally:
                        driver.close()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error("核心表单事务导入失败，已回滚：%s", exc)
            raise
        finally:
            ep.unbind_connection()
            conn.close()
    else:
        # 非单事务模式仅用于兼容旧的大批量历史导入场景。
        import_tables_by_plan(ep, core_paths, missing, args.chunk_size, import_plan)

    if missing:
        logger.warning("缺失 CSV 文件：%s", missing)


if __name__ == "__main__":
    main()
