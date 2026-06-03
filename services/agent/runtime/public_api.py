"""Agent 对外公共运行时接口。

该模块为 backend 提供稳定边界，避免产品服务层直接依赖 LangGraph 细节。
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from langchain_core.messages import BaseMessage

from agent.core.config import AgentConfig
from agent.runtime.fusion_agent import FusionAgent


def _message_to_dict(message: Any, index: int = 0) -> Dict[str, Any]:
    """统一序列化 LangChain/LangGraph 消息。"""
    if isinstance(message, BaseMessage):
        msg_type = str(getattr(message, "type", "") or "").strip().lower()
        role = (
            "user"
            if msg_type == "human"
            else "assistant"
            if msg_type == "ai"
            else "system"
            if msg_type == "system"
            else msg_type or "unknown"
        )
        return {
            "id": str(getattr(message, "id", None) or f"msg-{index}"),
            "role": role,
            "type": msg_type or role,
            "content": str(getattr(message, "content", "") or ""),
        }
    if isinstance(message, dict):
        data = message.get("data") if isinstance(message.get("data"), dict) else message
        role = str(data.get("role") or data.get("type") or "unknown").strip().lower()
        if role == "human":
            role = "user"
        if role == "ai":
            role = "assistant"
        return {
            "id": str(data.get("id") or f"msg-{index}"),
            "role": role,
            "type": str(data.get("type") or role),
            "content": str(data.get("content") or ""),
        }
    return {
        "id": f"msg-{index}",
        "role": "unknown",
        "type": "unknown",
        "content": str(message or ""),
    }


def _to_json(value: Any) -> Any:
    """递归序列化 LangGraph 值。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, BaseMessage):
        return _message_to_dict(value)
    if is_dataclass(value):
        return _to_json(asdict(value))
    if hasattr(value, "model_dump"):
        try:
            return _to_json(value.model_dump(mode="json"))
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): _to_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json(item) for item in value]
    return str(value)


class AgentRuntimeFacade:
    """供 backend 使用的 Agent 运行时门面。"""

    def __init__(self, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.load()
        self.agent = FusionAgent(self.config)

    def respond(self, user_message: str, thread_id: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        """执行一次同步问答。"""
        return self.agent.respond(user_message, thread_id=thread_id)

    def stream(
        self, user_message: str, thread_id: Optional[str] = None
    ) -> Tuple[Iterable[Any], Dict[str, Any]]:
        """执行一次流式问答。"""
        return self.agent.stream_response(user_message, thread_id=thread_id)

    def get_state(self, thread_id: str) -> Any:
        """读取线程当前状态。"""
        return self.agent.get_state(thread_id)

    def get_messages(self, thread_id: str) -> List[Dict[str, Any]]:
        """读取线程消息列表。"""
        snapshot = self.agent.get_state(thread_id)
        values = getattr(snapshot, "values", None)
        raw_messages = values.get("messages") if isinstance(values, dict) else []
        if not isinstance(raw_messages, list):
            return []
        return [_message_to_dict(item, index=idx) for idx, item in enumerate(raw_messages, start=1)]

    def get_state_history(self, thread_id: str, limit: Optional[int] = None) -> List[Any]:
        """读取线程 checkpoint 历史。"""
        return list(self.agent.get_state_history(thread_id, limit=limit))

    def close(self) -> None:
        """关闭底层 Agent 资源。"""
        self.agent.close()

    @staticmethod
    def serialize_snapshot(snapshot: Any) -> Dict[str, Any]:
        """序列化单个状态快照。"""
        return {
            "config": _to_json(getattr(snapshot, "config", None) or {}),
            "metadata": _to_json(getattr(snapshot, "metadata", None) or {}),
            "values": _to_json(getattr(snapshot, "values", None) or {}),
            "created_at": getattr(snapshot, "created_at", None),
            "parent_config": _to_json(getattr(snapshot, "parent_config", None) or {}),
        }
