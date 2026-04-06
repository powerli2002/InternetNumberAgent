"""backend 对 agent 的适配层。"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple

from agent.runtime.public_api import AgentRuntimeFacade


class AgentRuntimeService:
    """将 Agent 原生事件映射为产品事件。"""

    def __init__(self, facade: AgentRuntimeFacade) -> None:
        self.facade = facade

    @staticmethod
    def split_event(event: Any) -> Tuple[str, Any]:
        """拆分 LangGraph stream 事件。"""
        if isinstance(event, tuple) and len(event) == 2:
            return str(event[0]), event[1]
        return "custom", event

    def stream(self, user_message: str, thread_id: str) -> Tuple[Iterable[Any], Dict[str, Any]]:
        """发起流式问答。"""
        return self.facade.stream(user_message, thread_id=thread_id)
