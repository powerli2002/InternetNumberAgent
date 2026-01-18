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
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

# sys.path.append("../")
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent_loop import FusionAgent
from agent.config import AgentConfig
from agent.models import ConversationTurn


def _run_with_timeout(agent: FusionAgent, user_input: str, history: list[ConversationTurn], timeout_seconds: int):
    """在独立线程中执行单次请求，超时则抛出异常。"""
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(agent.respond, user_input, history=history)
        return future.result(timeout=timeout_seconds)


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
    args = parser.parse_args()

    # 加载配置并初始化智能体
    config = AgentConfig.load()
    agent = FusionAgent(config)

    # 设置超时时间，确保不会无限等待
    timeout_seconds = max(1, int(config.request_timeout_seconds))
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
