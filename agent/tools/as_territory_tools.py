#!/usr/bin/env python3
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# 确保可导入项目内模块
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "fusiondata" / "src"
for path in (PROJECT_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.append(str(path))

from agent_tools.as_territory_tools import (
    build_as_territory_from_csv,
    build_neo4j_datasets,
    load_as_entity,
    load_country_entity,
    load_to_neo4j,
)
from fusiondata.src.utils.config_loader import load_yaml_config
from utils.logging_manager import logger


def load_config(config_path: Path) -> dict:
    return load_yaml_config(config_path)


def find_latest_date(format_dir: Path, prefix: str) -> Optional[str]:
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d{{4}}-\d{{2}}-\d{{2}})\.csv$")
    if not format_dir.exists():
        return None
    dates = []
    for path in format_dir.glob(f"{prefix}_*.csv"):
        match = pattern.match(path.name)
        if not match:
            continue
        dates.append(match.group(1))
    if not dates:
        return None
    return sorted(dates)[-1]


def resolve_path(root_dir: Path, path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else (root_dir / path).resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description="AS 疆域分析工具（IPv4 前缀 → 国家）")
    parser.add_argument(
        "--config", default="conf/config.docker.yaml", help="YAML 配置路径"
    )
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--date", default=None, help="已弃用，脚本自动使用最新日期")
    parser.add_argument(
        "--output-dir", default=None, help="输出目录（默认 fusiondata/data/output）"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="仅处理前 N 行用于快速测试"
    )
    parser.add_argument("--chunk-size", type=int, default=200000, help="分块处理行数")
    parser.add_argument("--neo4j-uri", default=None, help="Neo4j Bolt URI")
    parser.add_argument("--neo4j-user", default=None, help="Neo4j 用户名")
    parser.add_argument("--neo4j-password", default=None, help="Neo4j 密码")
    parser.add_argument("--load-neo4j", action="store_true", help="写入 Neo4j")
    args = parser.parse_args()

    root_dir = Path(args.root).resolve()
    config_path = Path(args.config).resolve()
    cfg = load_config(config_path)
    date = args.date or cfg.get("current_date") or datetime.now().strftime("%Y-%m-%d")

    output_root = resolve_path(root_dir, cfg.get("output_dir", "./fusiondata/data/"))
    output_dir = Path(args.output_dir) if args.output_dir else output_root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    format_dir = output_root / "format"
    latest_date = find_latest_date(format_dir, "ip_bgp_entity")
    if latest_date:
        if args.date:
            logger.info("已忽略 --date=%s，自动使用最新日期 %s", args.date, latest_date)
        date = latest_date
    else:
        logger.error("未找到 ip_bgp_entity_*.csv，无法继续执行")
        return

    ip_bgp_path = format_dir / f"ip_bgp_entity_{date}.csv"
    as_entity_path = format_dir / f"as_entity_{date}.csv"
    country_entity_path = format_dir / f"country_entity_{date}.csv"

    if not ip_bgp_path.exists():
        logger.error("缺少 IPv4 BGP 实体文件: %s", ip_bgp_path)
        return

    summary, detail = build_as_territory_from_csv(
        ip_bgp_path, chunksize=args.chunk_size, limit=args.limit
    )

    as_df = load_as_entity(as_entity_path)
    country_df = load_country_entity(country_entity_path)

    summary_path = output_dir / f"as_territory_summary_{date}.csv"
    detail_path = output_dir / f"as_territory_detail_{date}.csv"
    summary.to_csv(summary_path, index=False)
    detail.to_csv(detail_path, index=False)
    logger.info("已输出: %s", summary_path)
    logger.info("已输出: %s", detail_path)

    if not args.load_neo4j:
        logger.info("未启用 Neo4j 写入，分析结束")
        return

    neo4j_uri = args.neo4j_uri or "bolt://localhost:7687"
    neo4j_user = args.neo4j_user or "neo4j"
    neo4j_password = args.neo4j_password or "neo4j123"

    as_nodes, country_nodes, territory_rels = build_neo4j_datasets(
        summary=summary,
        detail=detail,
        as_df=as_df,
        country_df=country_df,
    )

    load_to_neo4j(
        uri=neo4j_uri,
        user=neo4j_user,
        password=neo4j_password,
        as_nodes=as_nodes,
        country_nodes=country_nodes,
        territory_rels=territory_rels,
    )


if __name__ == "__main__":
    main()
