"""互联网号码资源问答系统的智能体入口包。"""

from __future__ import annotations

from typing import Any

from agent.core.config import AgentConfig

__all__ = ["AgentConfig", "FusionAgent"]


def __getattr__(name: str) -> Any:
    """按需导出重量级对象，避免轻量模块导入时拉起全部运行时依赖。"""
    if name == "FusionAgent":
        from agent.runtime.fusion_agent import FusionAgent

        return FusionAgent
    raise AttributeError(f"module 'agent' has no attribute {name!r}")
