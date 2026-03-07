"""FusionAgent：LangGraph 编排入口。"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Tuple

from agent.core.config import AgentConfig
from agent.runtime.langgraph_orchestrator import LangGraphOrchestrator


class FusionAgent:
    """对外兼容的主代理接口，内部使用 LangGraph 编排。"""

    def __init__(self, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.load()
        self._orchestrator = LangGraphOrchestrator(self.config)

    def respond(self, user_message: str, thread_id: Optional[str] = None) -> Tuple[str, dict]:
        """同步问答。"""
        answer, metadata = self._orchestrator.respond(user_message, thread_id=thread_id)
        return answer, metadata

    def stream_response(
        self,
        user_message: str,
        thread_id: Optional[str] = None,
    ) -> Tuple[Iterable[Any], dict]:
        """流式问答。"""
        return self._orchestrator.stream_response(user_message, thread_id=thread_id)

    def get_state(self, thread_id: str):
        """读取线程当前状态。"""
        return self._orchestrator.get_state(thread_id)

    def get_state_history(self, thread_id: str, limit: Optional[int] = None):
        """读取线程 checkpoint 历史。"""
        return self._orchestrator.get_state_history(thread_id, limit=limit)
