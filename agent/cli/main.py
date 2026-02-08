"""
智能体命令行界面

提供命令行方式与融合智能体交互的入口程序：
1. 单轮问答模式：处理单个问题后退出
2. 交互对话模式：持续对话直到用户退出
3. 超时控制：防止长时间运行阻塞终端
4. 错误处理：捕获异常并提供友好提示

使用场景：
- 快速测试智能体回答质量
- 开发调试过程中的问题验证
- 生产环境的简单问答接口
"""

from __future__ import annotations

import argparse
import sys
import os
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

# 直接脚本启动时，确保优先从项目根目录解析 `agent.*` 包，避免命中 `agent/agent` 子目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.core.config import AgentConfig
from agent.core.models import ConversationTurn
from agent.runtime.fusion_agent import FusionAgent


def _run_with_timeout(agent: FusionAgent, user_input: str, history: list[ConversationTurn], timeout_seconds: int):
    """在独立线程中执行单次请求，超时则抛出异常。"""
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(agent.respond, user_input, history=history)
        return future.result(timeout=timeout_seconds)


def _parse_tables(raw: str | None) -> list[str] | None:
    """解析逗号分隔的表名列表。"""
    if not raw:
        return None
    tables = [item.strip() for item in raw.split(",") if item.strip()]
    return tables or None


def main() -> None:
    """
    主函数：智能体命令行界面入口

    支持两种运行模式：
    1. 单轮模式（--once）：处理单个问题后退出，适合脚本调用
    2. 交互模式：持续对话，适合人工交互测试

    执行流程：
    - 解析命令行参数
    - 加载配置和初始化智能体
    - 根据模式选择执行路径
    - 处理超时和异常情况
    - 维护对话历史记录
    """
    parser = argparse.ArgumentParser(description="互联网号码资源问答智能体 CLI")
    parser.add_argument("--once", default=None, help="单轮提问模式，处理单个问题后退出")
    parser.add_argument("--build-index", action="store_true", help="手动构建 NL2SQL 索引后退出")
    parser.add_argument("--preload-index", action="store_true", help="预热 NL2SQL 索引，进入交互前加载到内存")
    parser.add_argument("--preload-columns", action="store_true", help="预热时同时加载列索引")
    parser.add_argument("--index-tables", default=None, help="构建索引的表名，逗号分隔")
    parser.add_argument("--skip-columns", action="store_true", help="仅构建表索引，不构建列索引")
    parser.add_argument("--force-index", action="store_true", help="强制重建索引")
    args = parser.parse_args()

    # 加载配置并初始化智能体
    config = AgentConfig.load()
    agent = FusionAgent(config)

    if args.build_index:
        try:
            table_names = _parse_tables(args.index_tables) or config.allowed_tables
            result = agent.nl2sql_tool.prepare_index_cache(
                table_names=table_names,
                build_tables=True,
                build_columns=not args.skip_columns,
                force=args.force_index,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as exc:
            print(f"构建索引失败: {exc}")
        return

    if args.preload_index:
        try:
            table_names = _parse_tables(args.index_tables) or config.allowed_tables
            result = agent.nl2sql_tool.warmup_retrievers(table_names, load_columns=args.preload_columns)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as exc:
            print(f"预热索引失败: {exc}")

    # 设置超时时间，确保不会无限等待
    timeout_seconds = max(1, int(config.cli_timeout_seconds))
    history: list[ConversationTurn] = []

    if args.once:
        try:
            answer, _ = _run_with_timeout(agent, args.once, history, timeout_seconds)
            print(answer)
        except FuturesTimeoutError:
            print(f"执行失败: 请求超时（超过 {timeout_seconds} 秒）")
        except Exception as exc:
            print(f"执行失败: {exc}")
        return

    while True:
        user_input = input("用户> ").strip()
        if user_input in ("exit", "quit", "q"):
            break
        try:
            answer, _ = _run_with_timeout(agent, user_input, history, timeout_seconds)
            print(f"助手> {answer}")
            history.append(ConversationTurn(role="user", content=user_input))
            history.append(ConversationTurn(role="assistant", content=answer))
        except FuturesTimeoutError:
            print(f"执行失败: 请求超时（超过 {timeout_seconds} 秒）")
        except Exception as exc:
            print(f"执行失败: {exc}")


if __name__ == "__main__":

    main()
