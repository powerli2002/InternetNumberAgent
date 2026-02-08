"""A2A Worker HTTP+SSE 服务。"""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from datetime import datetime, timezone
import json
from typing import Dict, List

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from agent.core.config import AgentConfig
from agent.core.tracing import LangSmithTracer
from agent.protocols.a2a.models import (
    A2AEvent,
    A2AResultEnvelope,
    A2ATaskPayload,
    A2ATaskState,
    A2ATaskSubmitResponse,
)
from agent.workers.executor import WorkerExecutor


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sse(event_type: str, payload: Dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


class _TaskStore:
    """内存任务仓库（支持事件订阅）。"""

    def __init__(self) -> None:
        self._tasks: Dict[str, A2ATaskState] = {}
        self._events: Dict[str, List[A2AEvent]] = {}
        self._subscribers: Dict[str, List[asyncio.Queue[A2AEvent]]] = {}
        self._lock = asyncio.Lock()

    async def create_task(self, payload: A2ATaskPayload) -> A2ATaskState:
        async with self._lock:
            state = A2ATaskState(
                task_id=payload.task_id,
                agent=payload.agent,
                trace_id=payload.trace_id,
                payload=payload,
            )
            self._tasks[payload.task_id] = state
            accepted = A2AEvent(
                event_type="accepted",
                task_id=payload.task_id,
                agent=payload.agent,
                trace_id=payload.trace_id,
                status="accepted",
                data={"payload": payload.model_dump(mode="json")},
            )
            self._events[payload.task_id] = [accepted]
            self._subscribers.setdefault(payload.task_id, [])
            await self._publish_locked(accepted)
            return state

    async def get_task(self, task_id: str) -> A2ATaskState:
        async with self._lock:
            state = self._tasks.get(task_id)
            if not state:
                raise KeyError(task_id)
            return state

    async def get_history(self, task_id: str) -> List[A2AEvent]:
        async with self._lock:
            return list(self._events.get(task_id, []))

    async def subscribe(self, task_id: str) -> asyncio.Queue[A2AEvent]:
        async with self._lock:
            if task_id not in self._tasks:
                raise KeyError(task_id)
            queue: asyncio.Queue[A2AEvent] = asyncio.Queue()
            self._subscribers.setdefault(task_id, []).append(queue)
            return queue

    async def unsubscribe(self, task_id: str, queue: asyncio.Queue[A2AEvent]) -> None:
        async with self._lock:
            queues = self._subscribers.get(task_id, [])
            if queue in queues:
                queues.remove(queue)

    async def mark_running(self, task_id: str) -> None:
        await self._update_status(task_id, "running", "started", {})

    async def mark_progress(self, task_id: str, data: Dict) -> None:
        await self._update_status(task_id, "running", "progress", data)

    async def mark_completed(self, task_id: str, result: A2AResultEnvelope) -> None:
        async with self._lock:
            state = self._tasks.get(task_id)
            if not state:
                return
            state.status = "completed"
            state.updated_at = _now_iso()
            state.result = result
            event = A2AEvent(
                event_type="completed",
                task_id=task_id,
                agent=state.agent,
                trace_id=state.trace_id,
                status="completed",
                data={"result": result.model_dump(mode="json")},
            )
            self._events.setdefault(task_id, []).append(event)
            await self._publish_locked(event)

    async def mark_failed(self, task_id: str, error: str) -> None:
        async with self._lock:
            state = self._tasks.get(task_id)
            if not state:
                return
            state.status = "failed"
            state.updated_at = _now_iso()
            state.error = error
            event = A2AEvent(
                event_type="failed",
                task_id=task_id,
                agent=state.agent,
                trace_id=state.trace_id,
                status="failed",
                data={"error": error},
            )
            self._events.setdefault(task_id, []).append(event)
            await self._publish_locked(event)

    async def _update_status(self, task_id: str, status: str, event_type: str, data: Dict) -> None:
        async with self._lock:
            state = self._tasks.get(task_id)
            if not state:
                return
            state.status = status  # type: ignore[assignment]
            state.updated_at = _now_iso()
            event = A2AEvent(
                event_type=event_type,  # type: ignore[arg-type]
                task_id=task_id,
                agent=state.agent,
                trace_id=state.trace_id,
                status=status,  # type: ignore[arg-type]
                data=data,
            )
            self._events.setdefault(task_id, []).append(event)
            await self._publish_locked(event)

    async def _publish_locked(self, event: A2AEvent) -> None:
        queues = list(self._subscribers.get(event.task_id, []))
        for queue in queues:
            await queue.put(event)


def create_a2a_app(config: AgentConfig | None = None) -> FastAPI:
    """创建 A2A FastAPI 服务。"""
    cfg = config or AgentConfig.load()
    tracer = LangSmithTracer()
    executor = WorkerExecutor(cfg, tracer=tracer)
    store = _TaskStore()
    app = FastAPI(title="Fusion A2A Worker API")

    async def _execute_task(task_id: str) -> None:
        try:
            state = await store.get_task(task_id)
        except KeyError:
            return
        payload = state.payload
        await store.mark_running(task_id)
        run_ctx = (
            tracer.start_run(
                name="a2a_task_execute",
                run_type="chain",
                inputs={"payload": payload.model_dump(mode="json")},
                tags=["a2a", "worker", f"agent:{payload.agent}"],
                metadata={"trace_id": payload.trace_id},
            )
            if tracer.enabled
            else nullcontext()
        )
        with run_ctx as run:
            try:
                result = await asyncio.to_thread(executor.execute, payload, run if run else None)
                if result.status == "ok":
                    await store.mark_completed(task_id, result)
                else:
                    await store.mark_failed(task_id, "; ".join(result.errors) or "A2A 任务失败")
                if run:
                    run.add_outputs({"result": result.model_dump(mode="json")})
            except Exception as exc:
                await store.mark_failed(task_id, str(exc))
                if run:
                    run.add_outputs({"error": str(exc)})

    @app.get("/health")
    async def health() -> Dict[str, str]:
        return {"status": "ok", "time": _now_iso()}

    @app.post("/a2a/tasks", response_model=A2ATaskSubmitResponse)
    async def submit_task(payload: A2ATaskPayload) -> A2ATaskSubmitResponse:
        await store.create_task(payload)
        asyncio.create_task(_execute_task(payload.task_id))
        return A2ATaskSubmitResponse(task_id=payload.task_id, status="accepted")

    @app.get("/a2a/tasks/{task_id}", response_model=A2ATaskState)
    async def get_task(task_id: str) -> A2ATaskState:
        try:
            return await store.get_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc

    @app.get("/a2a/tasks/{task_id}/events")
    async def stream_events(task_id: str, request: Request) -> StreamingResponse:
        try:
            history = await store.get_history(task_id)
            queue = await store.subscribe(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc
        poll_timeout_seconds = max(1.0, float(cfg.a2a_event_poll_timeout_seconds))

        async def generator():
            try:
                for event in history:
                    yield _sse(event.event_type, event.model_dump(mode="json"))
                if history and history[-1].event_type in {"completed", "failed"}:
                    return
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=poll_timeout_seconds)
                        yield _sse(event.event_type, event.model_dump(mode="json"))
                        if event.event_type in {"completed", "failed"}:
                            break
                    except asyncio.TimeoutError:
                        heartbeat = A2AEvent(
                            event_type="heartbeat",
                            task_id=task_id,
                            agent="system",
                            status="running",
                            data={},
                        )
                        yield _sse("heartbeat", heartbeat.model_dump(mode="json"))
            finally:
                await store.unsubscribe(task_id, queue)

        return StreamingResponse(generator(), media_type="text/event-stream")

    return app


config = AgentConfig.load()
app = create_a2a_app(config)
