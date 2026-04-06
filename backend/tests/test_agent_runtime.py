"""backend 对 agent 适配层测试。"""

from __future__ import annotations

from backend.agent_runtime import AgentRuntimeService


class _StubFacade:
    """测试用 facade。"""


def test_split_event_with_tuple() -> None:
    """LangGraph 原生 tuple 事件应被正确拆分。"""
    service = AgentRuntimeService(_StubFacade())  # type: ignore[arg-type]
    mode, payload = service.split_event(("custom", {"event": "process"}))
    assert mode == "custom"
    assert payload == {"event": "process"}


def test_split_event_with_raw_payload() -> None:
    """裸 payload 应回退到 custom 模式。"""
    service = AgentRuntimeService(_StubFacade())  # type: ignore[arg-type]
    mode, payload = service.split_event({"event": "messages"})
    assert mode == "custom"
    assert payload == {"event": "messages"}
