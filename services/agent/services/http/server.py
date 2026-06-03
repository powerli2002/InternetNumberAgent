from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
import uuid
from datetime import datetime, timezone
import os
import time
from typing import Any, Dict, Iterable, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field

from agent.core.config import AgentConfig
from agent.runtime.fusion_agent import FusionAgent
from fusiondata.src.utils.logging_manager import logger


class ThreadCreateRequest(BaseModel):
    """创建线程请求。"""

    thread_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    if_exists: str = "raise"


class ThreadSearchRequest(BaseModel):
    """线程检索请求。"""

    metadata: Optional[Dict[str, Any]] = None
    limit: int = 100
    offset: int = 0
    status: Optional[str] = None
    thread_ids: Optional[List[str]] = None


class RunStreamRequest(BaseModel):
    """运行流式请求。"""

    assistant_id: Optional[str] = None
    input: Dict[str, Any] = Field(default_factory=dict)
    stream_mode: Optional[Any] = None


class ThreadStore:
    """基于 Postgres 的线程注册与 metadata 存储。"""

    def __init__(self, postgres_url: str) -> None:
        if not postgres_url:
            raise RuntimeError("缺少 POSTGRES_URL，无法初始化线程存储。")
        try:
            from sqlalchemy import create_engine, text  # type: ignore
        except Exception as exc:
            raise RuntimeError("未安装 SQLAlchemy，无法初始化线程存储。") from exc
        self._text = text
        self._engine = create_engine(postgres_url)
        self._init_tables()

    def _init_tables(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                self._text(
                    """
                    CREATE TABLE IF NOT EXISTS agent_threads (
                        thread_id UUID PRIMARY KEY,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        status TEXT NOT NULL DEFAULT 'idle',
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                    );
                    """
                )
            )

    def create_thread(self, payload: ThreadCreateRequest) -> Dict[str, Any]:
        thread_id = payload.thread_id or str(uuid.uuid4())
        metadata = payload.metadata or {}
        if_exists = payload.if_exists or "raise"
        with self._engine.begin() as conn:
            exists = conn.execute(
                self._text("SELECT 1 FROM agent_threads WHERE thread_id = :thread_id"),
                {"thread_id": thread_id},
            ).fetchone()
            if exists:
                if if_exists == "do_nothing":
                    return self.get_thread(thread_id)
                raise HTTPException(status_code=409, detail="线程已存在")
            conn.execute(
                self._text(
                    """
                    INSERT INTO agent_threads (thread_id, status, metadata)
                    VALUES (:thread_id, :status, CAST(:metadata AS jsonb))
                    """
                ),
                {"thread_id": thread_id, "status": "idle", "metadata": json.dumps(metadata)},
            )
        return self.get_thread(thread_id)

    def get_thread(self, thread_id: str) -> Dict[str, Any]:
        with self._engine.begin() as conn:
            row = conn.execute(
                self._text(
                    """
                    SELECT thread_id::text, created_at, updated_at, status, metadata
                    FROM agent_threads WHERE thread_id = :thread_id
                    """
                ),
                {"thread_id": thread_id},
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="线程不存在")
            return {
                "thread_id": row[0],
                "created_at": row[1].isoformat(),
                "updated_at": row[2].isoformat(),
                "status": row[3],
                "metadata": row[4] or {},
                "config": {},
                "values": {},
                "interrupts": {},
            }

    def search_threads(self, payload: ThreadSearchRequest) -> List[Dict[str, Any]]:
        filters = []
        params: Dict[str, Any] = {
            "limit": payload.limit,
            "offset": payload.offset,
        }
        if payload.status:
            filters.append("status = :status")
            params["status"] = payload.status
        if payload.thread_ids:
            filters.append("thread_id = ANY(:thread_ids)")
            params["thread_ids"] = payload.thread_ids
        if payload.metadata:
            for idx, (key, value) in enumerate(payload.metadata.items()):
                param_key = f"meta_{idx}"
                filters.append(f"metadata ->> '{key}' = :{param_key}")
                params[param_key] = str(value)
        where_clause = "WHERE " + " AND ".join(filters) if filters else ""
        query = f"""
            SELECT thread_id::text, created_at, updated_at, status, metadata
            FROM agent_threads
            {where_clause}
            ORDER BY updated_at DESC
            LIMIT :limit OFFSET :offset
        """
        threads: List[Dict[str, Any]] = []
        with self._engine.begin() as conn:
            rows = conn.execute(self._text(query), params).fetchall()
            for row in rows:
                thread_id = row[0]
                threads.append(
                    {
                        "thread_id": thread_id,
                        "created_at": row[1].isoformat(),
                        "updated_at": row[2].isoformat(),
                        "status": row[3],
                        "metadata": row[4] or {},
                        "config": {},
                        "values": {},
                        "interrupts": {},
                    }
                )
        return threads

    def update_metadata(self, thread_id: str, updates: Dict[str, Any]) -> None:
        if not updates:
            return
        with self._engine.begin() as conn:
            row = conn.execute(
                self._text("SELECT metadata FROM agent_threads WHERE thread_id = :thread_id"),
                {"thread_id": thread_id},
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="线程不存在")
            metadata = row[0] or {}
            metadata.update(updates)
            conn.execute(
                self._text("UPDATE agent_threads SET metadata = CAST(:metadata AS jsonb) WHERE thread_id = :thread_id"),
                {"metadata": json.dumps(metadata), "thread_id": thread_id},
            )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preview_body(body: bytes, limit: int) -> str:
    """截断并解码请求/响应体，避免日志过大。"""
    if not body:
        return ""
    preview = body[:limit]
    text = preview.decode("utf-8", errors="replace")
    if len(body) > limit:
        return f"{text}...<truncated {len(body)} bytes>"
    return text


def _get_client_ip(request: Request) -> str:
    client = request.client
    return client.host if client else "-"


def _get_request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or str(uuid.uuid4())


API_LOG_ENABLED = os.getenv("API_LOG_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
API_LOG_BODY_LIMIT = max(256, int(os.getenv("API_LOG_BODY_LIMIT", "2000")))


def _extract_user_message(payload: Dict[str, Any]) -> str:
    if "messages" in payload and payload["messages"]:
        last = payload["messages"][-1]
        if isinstance(last, dict) and "content" in last:
            return _content_to_text(last["content"])
    for key in ("message", "question", "content", "text"):
        if key in payload:
            return _content_to_text(payload[key])
    raise HTTPException(status_code=400, detail="未找到用户消息")


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(p for p in parts if p)
    return str(content)


def _split_stream_event(event: Any) -> tuple[str, Any]:
    """拆分 LangGraph 原生 stream 事件。

    `graph.stream(stream_mode=[...])` 会返回 `(mode, payload)` 二元组。
    为了兼容少量非标准调用，这里也接受裸 payload，并默认视为 custom 事件。
    """
    if isinstance(event, tuple) and len(event) == 2:
        return str(event[0]), event[1]
    return "custom", event


def _message_to_api_dict(message: Any, index: int = 0) -> Dict[str, Any]:
    """将 LangGraph state 中的消息对象统一序列化为前端可消费结构。"""
    if isinstance(message, BaseMessage):
        msg_type = str(getattr(message, "type", "") or "").strip().lower()
        role = "user" if msg_type == "human" else "assistant" if msg_type == "ai" else "system" if msg_type == "system" else msg_type or "unknown"
        return {
            "content": str(message.content or ""),
            "type": msg_type or role,
            "role": role,
            "id": str(getattr(message, "id", None) or f"msg-{index}"),
            "name": getattr(message, "name", None),
            "additional_kwargs": dict(getattr(message, "additional_kwargs", {}) or {}),
            "response_metadata": dict(getattr(message, "response_metadata", {}) or {}),
            "tool_calls": list(getattr(message, "tool_calls", []) or []),
            "invalid_tool_calls": list(getattr(message, "invalid_tool_calls", []) or []),
            "usage_metadata": getattr(message, "usage_metadata", None),
        }

    if isinstance(message, dict):
        # 兼容 LangChain messages_to_dict 结果：{"type": "...", "data": {...}}
        if isinstance(message.get("data"), dict):
            data = dict(message.get("data") or {})
            raw_type = str(message.get("type") or data.get("type") or "").strip().lower()
            role = "user" if raw_type == "human" else "assistant" if raw_type == "ai" else "system" if raw_type == "system" else raw_type or "unknown"
            return {
                "content": str(data.get("content") or ""),
                "type": raw_type or role,
                "role": role,
                "id": str(data.get("id") or f"msg-{index}"),
                "name": data.get("name"),
                "additional_kwargs": dict(data.get("additional_kwargs") or {}),
                "response_metadata": dict(data.get("response_metadata") or {}),
                "tool_calls": list(data.get("tool_calls") or []),
                "invalid_tool_calls": list(data.get("invalid_tool_calls") or []),
                "usage_metadata": data.get("usage_metadata"),
            }
        role = str(message.get("role") or "").strip().lower()
        raw_type = str(message.get("type") or "").strip().lower()
        if not role:
            role = "user" if raw_type == "human" else "assistant" if raw_type == "ai" else raw_type or "unknown"
        return {
            "content": str(message.get("content") or ""),
            "type": raw_type or role,
            "role": role,
            "id": str(message.get("id") or f"msg-{index}"),
            "name": message.get("name"),
            "additional_kwargs": dict(message.get("additional_kwargs") or {}),
            "response_metadata": dict(message.get("response_metadata") or {}),
            "tool_calls": list(message.get("tool_calls") or []),
            "invalid_tool_calls": list(message.get("invalid_tool_calls") or []),
            "usage_metadata": message.get("usage_metadata"),
        }

    return {
        "content": str(message or ""),
        "type": "unknown",
        "role": "unknown",
        "id": f"msg-{index}",
        "name": None,
        "additional_kwargs": {},
        "response_metadata": {},
        "tool_calls": [],
        "invalid_tool_calls": [],
        "usage_metadata": None,
    }


def _to_api_json(value: Any) -> Any:
    """递归序列化 LangGraph state / checkpoint 结果。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, BaseMessage):
        return _message_to_api_dict(value)
    if is_dataclass(value):
        return _to_api_json(asdict(value))
    if hasattr(value, "model_dump"):
        try:
            return _to_api_json(value.model_dump(mode="json"))
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): _to_api_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_api_json(item) for item in value]
    return str(value)


def _serialize_values(values: Any) -> Dict[str, Any]:
    """将 StateSnapshot.values 转成 API 返回结构。"""
    if not isinstance(values, dict):
        return {"messages": []}
    payload = {str(key): _to_api_json(item) for key, item in values.items()}
    raw_messages = values.get("messages")
    if isinstance(raw_messages, list):
        payload["messages"] = [_message_to_api_dict(message, index=idx) for idx, message in enumerate(raw_messages, start=1)]
    else:
        payload.setdefault("messages", [])
    return payload


def _serialize_snapshot(snapshot: Any) -> Dict[str, Any]:
    """序列化 LangGraph StateSnapshot，供 history API 直接返回。"""
    config_payload = _to_api_json(getattr(snapshot, "config", None) or {})
    configurable = config_payload.get("configurable") if isinstance(config_payload, dict) else {}
    checkpoint_id = ""
    if isinstance(configurable, dict):
        checkpoint_id = str(configurable.get("checkpoint_id") or "")
    return {
        "checkpoint_id": checkpoint_id,
        "metadata": _to_api_json(getattr(snapshot, "metadata", None) or {}),
        "values": _serialize_values(getattr(snapshot, "values", None)),
        "next": list(getattr(snapshot, "next", ()) or ()),
        "created_at": getattr(snapshot, "created_at", None),
        "config": config_payload,
        "parent_config": _to_api_json(getattr(snapshot, "parent_config", None) or {}),
        "interrupts": _to_api_json(list(getattr(snapshot, "interrupts", ()) or ())),
    }


def _hydrate_thread(thread_payload: Dict[str, Any]) -> Dict[str, Any]:
    """用 LangGraph 原生 state 覆盖线程 values/history 视图。"""
    thread_id = str(thread_payload.get("thread_id") or "")
    snapshot = agent.get_state(thread_id)
    config_payload = _to_api_json(getattr(snapshot, "config", None) or {"configurable": {"thread_id": thread_id}})
    hydrated = dict(thread_payload)
    hydrated["config"] = config_payload
    hydrated["values"] = _serialize_values(getattr(snapshot, "values", None))
    hydrated["interrupts"] = _to_api_json(list(getattr(snapshot, "interrupts", ()) or ()))
    return hydrated


config = AgentConfig.load()
store = ThreadStore(config.postgres_url or "")
agent = FusionAgent(config)

app = FastAPI(title="Fusion Agent LangGraph API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_request_response(request: Request, call_next):
    """统一记录请求与响应日志。"""
    if not API_LOG_ENABLED:
        return await call_next(request)

    request_id = _get_request_id(request)
    start_time = time.monotonic()
    body_bytes = await request.body()
    request_body = _preview_body(body_bytes, API_LOG_BODY_LIMIT)
    logger.info(
        "HTTP请求 id=%s method=%s path=%s ip=%s query=%s body=%s",
        request_id,
        request.method,
        request.url.path,
        _get_client_ip(request),
        request.url.query,
        request_body,
    )

    try:
        response = await call_next(request)
    except Exception as exc:
        cost_ms = int((time.monotonic() - start_time) * 1000)
        logger.exception(
            "HTTP异常 id=%s method=%s path=%s cost_ms=%s error=%s",
            request_id,
            request.method,
            request.url.path,
            cost_ms,
            exc,
        )
        raise

    if isinstance(response, StreamingResponse):
        original_iterator = response.body_iterator

        async def _wrap_iterator():
            preview_parts: List[bytes] = []
            total_size = 0
            async for chunk in original_iterator:
                chunk_bytes: bytes
                if isinstance(chunk, str):
                    chunk_bytes = chunk.encode("utf-8", errors="replace")
                else:
                    chunk_bytes = bytes(chunk) if chunk is not None else b""
                if chunk_bytes and total_size < API_LOG_BODY_LIMIT:
                    remaining = API_LOG_BODY_LIMIT - total_size
                    preview_parts.append(chunk_bytes[:remaining])
                    total_size += len(chunk_bytes[:remaining])
                yield chunk
            cost_ms = int((time.monotonic() - start_time) * 1000)
            preview_body = _preview_body(b"".join(preview_parts), API_LOG_BODY_LIMIT)
            logger.info(
                "HTTP回复 id=%s method=%s path=%s status=%s cost_ms=%s body=%s",
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                cost_ms,
                preview_body,
            )

        response.body_iterator = _wrap_iterator()
        return response

    response_body = _preview_body(getattr(response, "body", b"") or b"", API_LOG_BODY_LIMIT)
    cost_ms = int((time.monotonic() - start_time) * 1000)
    logger.info(
        "HTTP回复 id=%s method=%s path=%s status=%s cost_ms=%s body=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        cost_ms,
        response_body,
    )
    return response


@app.get("/health")
async def health() -> Dict[str, Any]:
    """健康检查。"""
    return {"status": "ok", "time": _now_iso()}


@app.get("/info")
async def info() -> Dict[str, Any]:
    """LangGraph 兼容信息接口，用于前端连通性检查。"""
    return {
        "status": "ok",
        "assistant_id": "fusion-agent",
        "graph_id": "fusion-agent",
        "mcp_server_url": config.mcp_server_url,
        "orchestrator": "langgraph",
        "version": "local",
        "time": _now_iso(),
    }


@app.post("/threads")
async def create_thread(payload: ThreadCreateRequest) -> Dict[str, Any]:
    """创建线程。"""
    return _hydrate_thread(store.create_thread(payload))


@app.get("/threads/{thread_id}")
async def get_thread(thread_id: str) -> Dict[str, Any]:
    """获取线程详情。"""
    return _hydrate_thread(store.get_thread(thread_id))


@app.post("/threads/search")
async def search_threads(payload: ThreadSearchRequest) -> List[Dict[str, Any]]:
    """检索线程列表。"""
    return [_hydrate_thread(item) for item in store.search_threads(payload)]


@app.post("/threads/{thread_id}/history")
async def thread_history(thread_id: str) -> List[Dict[str, Any]]:
    """返回线程历史状态（LangGraph 原生 checkpoint 视图）。"""
    return [_serialize_snapshot(snapshot) for snapshot in agent.get_state_history(thread_id)]


@app.post("/threads/{thread_id}/runs")
async def run_thread(thread_id: str, payload: RunStreamRequest) -> Dict[str, Any]:
    """同步运行一次对话。"""
    assistant_id = payload.assistant_id or "fusion-agent"
    store.update_metadata(thread_id, {"assistant_id": assistant_id, "graph_id": assistant_id})
    user_message = _extract_user_message(payload.input)
    answer, metadata = agent.respond(user_message, thread_id=thread_id)
    snapshot = agent.get_state(thread_id)
    return {
        "run_id": str(metadata.get("trace_id") or uuid.uuid4()),
        "thread_id": thread_id,
        "created_at": _now_iso(),
        "values": _serialize_values(getattr(snapshot, "values", None)),
    }


@app.post("/threads/{thread_id}/runs/stream")
async def run_thread_stream(thread_id: str, payload: RunStreamRequest, request: Request) -> StreamingResponse:
    """以 SSE 形式流式返回结果。"""
    assistant_id = payload.assistant_id or "fusion-agent"
    store.update_metadata(thread_id, {"assistant_id": assistant_id, "graph_id": assistant_id})
    user_message = _extract_user_message(payload.input)
    stream_iter, metadata = agent.stream_response(user_message, thread_id=thread_id)
    run_id = str(metadata.get("trace_id") or uuid.uuid4())
    message_id = f"msg-{run_id}"

    stream_modes = payload.stream_mode or "messages"
    if isinstance(stream_modes, str):
        stream_modes = [stream_modes]
    stream_modes = [mode for mode in stream_modes if mode]
    if not stream_modes:
        stream_modes = ["messages"]

    def event_stream() -> Iterable[str]:
        event_id = 1
        yield _sse(event_id, "metadata", {"run_id": run_id, "thread_id": thread_id})
        event_id += 1

        for raw_event in stream_iter:
            mode, event_payload = _split_stream_event(raw_event)

            if mode == "custom":
                if (
                    isinstance(event_payload, dict)
                    and event_payload.get("event") == "messages"
                    and ("messages" in stream_modes or "messages-tuple" in stream_modes)
                ):
                    chunk = str(event_payload.get("content") or "")
                    if not chunk:
                        continue
                    serialized = {
                        "id": message_id,
                        "type": "ai",
                        "content": chunk,
                    }
                    chunk_meta = {
                        "role": str(event_payload.get("role") or "assistant"),
                        "chunk": True,
                        "node": event_payload.get("node"),
                    }
                    yield _sse(event_id, "messages", [serialized, chunk_meta])
                    event_id += 1
                    continue

                if "custom" in stream_modes:
                    yield _sse(event_id, "custom", _to_api_json(event_payload))
                    event_id += 1
                continue

            if mode == "updates":
                if "updates" in stream_modes:
                    yield _sse(event_id, "updates", _to_api_json(event_payload))
                    event_id += 1
                continue

            if mode == "values":
                if "values" in stream_modes:
                    yield _sse(event_id, "values", _serialize_values(event_payload))
                    event_id += 1
                continue

            if mode in stream_modes:
                yield _sse(event_id, mode, _to_api_json(event_payload))
                event_id += 1

        if "values" in stream_modes:
            snapshot = agent.get_state(thread_id)
            values = _serialize_values(getattr(snapshot, "values", None))
            yield _sse(event_id, "values", values)
            event_id += 1

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/assistants")
async def list_assistants() -> List[Dict[str, Any]]:
    """返回可用 assistant 列表。"""
    return [
        {
            "assistant_id": "fusion-agent",
            "name": "fusion-agent",
            "description": "互联网号码资源问答智能体",
        }
    ]


@app.get("/assistants/{assistant_id}")
async def get_assistant(assistant_id: str) -> Dict[str, Any]:
    """返回 assistant 详情。"""
    return {
        "assistant_id": assistant_id,
        "name": "fusion-agent",
        "description": "互联网号码资源问答智能体",
    }


def _sse(event_id: int, event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"id: {event_id}\nevent: {event}\ndata: {payload}\n\n"
