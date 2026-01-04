from __future__ import annotations

import argparse

from agent.agent_loop import FusionAgent
from agent.models import ConversationTurn


def main() -> None:
    parser = argparse.ArgumentParser(description="互联网号码资源问答智能体 CLI")
    parser.add_argument("--once", default=None, help="单轮提问模式")
    args = parser.parse_args()

    agent = FusionAgent()
    history: list[ConversationTurn] = []

    if args.once:
        try:
            answer, _ = agent.respond(args.once, history=history)
            print(answer)
        except Exception as exc:
            print(f"执行失败: {exc}")
        return

    while True:
        user_input = input("用户> ").strip()
        if user_input in ("exit", "quit", "q"):
            break
        try:
            answer, _ = agent.respond(user_input, history=history)
            print(f"助手> {answer}")
            history.append(ConversationTurn(role="user", content=user_input))
            history.append(ConversationTurn(role="assistant", content=answer))
        except Exception as exc:
            print(f"执行失败: {exc}")


if __name__ == "__main__":
    main()
