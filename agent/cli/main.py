"""智能体命令行界面。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import sys
from pathlib import Path

# 直接脚本启动时，确保优先从项目根目录解析 `agent.*` 包。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.core.config import AgentConfig
from agent.core.models import ConversationTurn
from agent.runtime.fusion_agent import FusionAgent


def _run_with_timeout(
    agent: FusionAgent,
    user_input: str,
    history: list[ConversationTurn],
    timeout_seconds: int,
):
    """在独立线程中执行单次请求，超时则抛出异常。"""
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(agent.respond, user_input, history=history)
        return future.result(timeout=timeout_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="互联网号码资源问答智能体 CLI")
    parser.add_argument("--once", default=None, help="单轮提问模式，处理单个问题后退出")
    args = parser.parse_args()

    config = AgentConfig.load()
    agent = FusionAgent(config)

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
