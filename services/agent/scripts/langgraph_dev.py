"""将 LangGraph 开发态热重载范围限制在 agent/ 目录。"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

import langgraph_cli.config
from langgraph_api.cli import run_server


def main() -> None:
    parser = argparse.ArgumentParser(
        description="运行 LangGraph 开发服务器，并将热重载目录显式限制为 agent/"
    )
    parser.add_argument("--host", default="127.0.0.1", help="服务监听地址")
    parser.add_argument("--port", type=int, default=2024, help="服务端口")
    parser.add_argument("--config", default="langgraph.json", help="LangGraph 配置文件路径")
    parser.add_argument(
        "--n-jobs-per-worker",
        type=int,
        help="每个 worker 的最大并发任务数",
    )
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--no-reload", action="store_true", help="禁用自动热重载")
    parser.add_argument("--debug-port", type=int, help="远程调试端口")
    parser.add_argument(
        "--wait-for-client",
        action="store_true",
        help="等待调试器连接后再继续启动",
    )
    parser.add_argument("--studio-url", type=str, help="自定义 Studio 地址")
    parser.add_argument(
        "--allow-blocking",
        action="store_true",
        help="允许同步阻塞 I/O",
    )
    parser.add_argument("--tunnel", action="store_true", help="通过隧道暴露本地服务")
    parser.add_argument(
        "--server-log-level",
        type=str,
        default="WARNING",
        help="LangGraph API 服务日志级别",
    )
    args = parser.parse_args()

    config_path = pathlib.Path(args.config)
    config_json = langgraph_cli.config.validate_config_file(config_path)
    if config_json.get("node_version"):
        raise ValueError(
            "当前脚本仅支持 Python in-memory LangGraph 服务，JS graph 请继续使用官方 CLI。"
        )

    cwd = os.getcwd()
    sys.path.append(cwd)

    # 保持与官方 dev 命令一致，把本地依赖目录加入导入路径。
    for dep in config_json.get("dependencies", []):
        dep_path = pathlib.Path(cwd) / dep
        if dep_path.is_dir() and dep_path.exists():
            sys.path.append(str(dep_path))

    run_server(
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
        reload_dirs=["agent"],
        graphs=config_json.get("graphs", {}),
        n_jobs_per_worker=args.n_jobs_per_worker,
        open_browser=not args.no_browser,
        debug_port=args.debug_port,
        env=config_json.get("env"),
        store=config_json.get("store"),
        wait_for_client=args.wait_for_client,
        auth=config_json.get("auth"),
        http=config_json.get("http"),
        ui=config_json.get("ui"),
        ui_config=config_json.get("ui_config"),
        webhooks=config_json.get("webhooks"),
        checkpointer=config_json.get("checkpointer"),
        studio_url=args.studio_url,
        allow_blocking=args.allow_blocking,
        tunnel=args.tunnel,
        server_level=args.server_log_level,
    )


if __name__ == "__main__":
    main()
