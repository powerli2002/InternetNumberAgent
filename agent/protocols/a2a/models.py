"""A2A 协议模型定义。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
import uuid

from pydantic import BaseModel, Field


def _utc_now() -> str:
    """返回 UTC ISO 时间戳。"""
    return datetime.now(timezone.utc).isoformat()


def _task_id() -> str:
    """生成短任务 ID。"""
    return str(uuid.uuid4())


TaskStatus = Literal["accepted", "running", "completed", "failed", "cancelled"]
EventType = Literal["accepted", "started", "progress", "completed", "failed", "heartbeat"]


class A2ATaskPayload(BaseModel):
    """A2A 任务输入载荷。"""

    task_id: str = Field(default_factory=_task_id)
    agent: str = "supervisor"
    objective: str
    constraints: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)
    expected_output: str = "结构化结果 + 证据摘要"
    budget: Dict[str, Any] = Field(default_factory=lambda: {"max_tokens": 1200, "max_time_ms": 15000})
    trace_id: str = ""
    created_at: str = Field(default_factory=_utc_now)


class A2AResultEvidence(BaseModel):
    """A2A 返回证据。"""

    source: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class A2AResultEnvelope(BaseModel):
    """A2A 任务结果。"""

    status: Literal["ok", "error"]
    agent: str
    trace_id: str = ""
    result: Dict[str, Any] = Field(default_factory=dict)
    evidence: List[A2AResultEvidence] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)


class A2AEvent(BaseModel):
    """A2A 事件（用于 SSE 流）。"""

    event_type: EventType
    task_id: str
    agent: str
    trace_id: str = ""
    status: TaskStatus
    timestamp: str = Field(default_factory=_utc_now)
    data: Dict[str, Any] = Field(default_factory=dict)


class A2ATaskState(BaseModel):
    """任务状态快照。"""

    task_id: str
    agent: str
    trace_id: str = ""
    status: TaskStatus = "accepted"
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)
    payload: A2ATaskPayload
    result: Optional[A2AResultEnvelope] = None
    error: Optional[str] = None


class A2ATaskSubmitResponse(BaseModel):
    """提交任务响应。"""

    task_id: str
    status: TaskStatus
    accepted_at: str = Field(default_factory=_utc_now)

