#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path


def _run_command(cmd: list[str], cwd: Path) -> None:
    """执行外部命令，失败时抛异常并终止后续流程。"""
    print(f"[RUN] {shlex.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=str(cwd))


def _build_pg_command(args: argparse.Namespace, root: Path, python_bin: str) -> list[str]:
    """
    构造 PostgreSQL 导入命令。

    设计说明：
    - 强制追加 `--single-transaction`，确保 16 表导入失败可回滚；
    - 仅在用户显式提供参数时拼接可选项，保持命令最小化。
    """
    cmd: list[str] = [
        python_bin,
        "-m",
        "agent.scripts.load_all_csv",
        "--root",
        str(root),
        "--config",
        args.config,
        "--chunk-size",
        str(args.chunk_size),
        "--wait-seconds",
        str(args.wait_seconds),
        "--single-transaction",
    ]
    if args.date:
        cmd.extend(["--date", args.date])
    if args.skip_ddl:
        cmd.append("--skip-ddl")
    if args.ddl_path:
        cmd.extend(["--ddl-path", args.ddl_path])
    if args.ensure_core:
        cmd.append("--ensure-core")
    return cmd


def _build_neo4j_command(args: argparse.Namespace, python_bin: str) -> list[str]:
    """
    构造 Neo4j 导入命令。

    设计说明：
    - 保持与 `neo4j_graph_loader` 参数一一对应；
    - 支持可选功能与单事务开关透传。
    """
    cmd: list[str] = [
        python_bin,
        "-m",
        "agent.tools.neo4j_graph_loader",
        "--batch-size",
        str(args.neo4j_batch_size),
    ]
    if args.include_website:
        cmd.append("--include-website")
    if args.include_industry:
        cmd.append("--include-industry")
    if args.skip_as_relations:
        cmd.append("--skip-as-relations")
    if args.no_progress:
        cmd.append("--no-progress")
    cmd.append("--single-transaction" if args.neo4j_single_transaction else "--no-single-transaction")
    return cmd


def main() -> None:
    parser = argparse.ArgumentParser(description="原子化导入网络数据到 PostgreSQL 与 Neo4j（顺序编排）")
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--config", default="conf/config.docker.yaml", help="CSV 导入配置文件")
    parser.add_argument("--date", default=None, help="快照日期，默认读取配置中的 current_date")
    parser.add_argument("--chunk-size", type=int, default=100000, help="CSV 导入分块大小")
    parser.add_argument("--wait-seconds", type=int, default=120, help="等待 PostgreSQL 就绪秒数")
    parser.add_argument("--skip-ddl", action="store_true", help="跳过核心表 DDL")
    parser.add_argument("--ddl-path", default=None, help="自定义核心 DDL 路径")
    parser.add_argument("--ensure-core", action="store_true", help="按既有规则先检查核心表再导入")

    parser.add_argument("--neo4j-batch-size", type=int, default=1000, help="Neo4j 每批写入大小")
    parser.add_argument("--include-website", action="store_true", help="导入 website 图数据")
    parser.add_argument("--include-industry", action="store_true", help="导入 industry 图数据")
    parser.add_argument("--skip-as-relations", action="store_true", help="跳过 AS 关系边导入")
    parser.add_argument("--no-progress", action="store_true", help="禁用进度条输出")
    parser.add_argument(
        "--neo4j-single-transaction",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Neo4j 是否单事务导入（默认开启，失败整批回滚）",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    python_bin = sys.executable

    pg_cmd = _build_pg_command(args, root=root, python_bin=python_bin)
    neo4j_cmd = _build_neo4j_command(args, python_bin=python_bin)

    # 先导入 PostgreSQL；若失败直接退出，不触发图导入。
    _run_command(pg_cmd, cwd=root)
    # PostgreSQL 成功后再导入 Neo4j。
    _run_command(neo4j_cmd, cwd=root)
    print("网络数据导入完成：PostgreSQL 与 Neo4j 均执行成功。")


if __name__ == "__main__":
    main()
