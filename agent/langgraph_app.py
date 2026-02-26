"""LangGraph 应用入口。"""

from __future__ import annotations

from agent.core.config import AgentConfig
from agent.runtime.langgraph_orchestrator import LangGraphOrchestrator


_config = AgentConfig.load()
_orchestrator = LangGraphOrchestrator(_config)

# 供 LangGraph CLI/调试工具直接加载。
graph = _orchestrator.graph
