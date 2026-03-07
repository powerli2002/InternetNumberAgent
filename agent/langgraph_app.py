"""LangGraph 应用入口。"""

from __future__ import annotations

from agent.core.config import AgentConfig
from agent.runtime.langgraph_orchestrator import LangGraphOrchestrator


_config = AgentConfig.load()
# LangGraph CLI / Studio 入口必须使用平台内置持久化。
# 如果这里继续暴露带 PostgresSaver 的已编译图，langgraph dev 会拒绝加载。
_orchestrator = LangGraphOrchestrator(_config, enable_checkpointer=False)

# 供 LangGraph CLI/调试工具直接加载。
graph = _orchestrator.graph
