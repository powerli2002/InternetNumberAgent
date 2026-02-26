"""FusionAgent：LangGraph 编排入口。"""

from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

from agent.core.config import AgentConfig
from agent.core.models import ConversationTurn
from agent.runtime.langgraph_orchestrator import LangGraphOrchestrator


class FusionAgent:
    """对外兼容的主代理接口，内部使用 LangGraph 编排。"""

    def __init__(self, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.load()
        self._orchestrator = LangGraphOrchestrator(self.config)

    def respond(self, user_message: str, history: Optional[List[ConversationTurn]] = None) -> Tuple[str, dict]:
        """同步问答。"""
        answer, metadata = self._orchestrator.respond(user_message, history=history)
        return answer, metadata

    def stream_response(
        self,
        user_message: str,
        history: Optional[List[ConversationTurn]] = None,
    ) -> Tuple[Iterable[str], dict]:
        """流式问答。"""
        return self._orchestrator.stream_response(user_message, history=history)
