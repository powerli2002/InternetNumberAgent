"""智能体命令行界面。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import uuid

# 直接脚本启动时，确保优先从项目根目录解析 `agent.*` 包。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.core.config import AgentConfig
from agent.runtime.fusion_agent import FusionAgent


def main() -> None:
    parser = argparse.ArgumentParser(description="互联网号码资源问答智能体 CLI")
    parser.add_argument("--once", default=None, help="单轮提问模式，处理单个问题后退出")
    args = parser.parse_args()

    config = AgentConfig.load()
    agent = FusionAgent(config)
    thread_id = str(uuid.uuid4())

    if args.once:
        try:
            # CLI 默认不设置外层超时，持续执行直到本轮请求自然结束。
            answer, _ = agent.respond(args.once, thread_id=thread_id)
            print(answer)
        except Exception as exc:
            print(f"执行失败: {exc}")
        return

    while True:
        user_input = input("用户> ").strip()
        if user_input in ("exit", "quit", "q"):
            break
        try:
            # CLI 默认不设置外层超时，持续执行直到本轮请求自然结束。
            answer, _ = agent.respond(user_input, thread_id=thread_id)
            print(f"助手> {answer}")
        except Exception as exc:
            print(f"执行失败: {exc}")


if __name__ == "__main__":
    main()
