"""A2A HTTP+SSE 客户端。"""

from __future__ import annotations

from contextlib import nullcontext
import json
from typing import Any, Dict, Iterator, Optional

import httpx

from agent.core.tracing import LangSmithTracer
from agent.services.a2a.models import A2AEvent, A2AResultEnvelope, A2ATaskPayload, A2ATaskState


class A2AClient:
    """A2A 客户端：提交任务并通过 SSE 获取结果。"""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: int = 60,
        tracer: Optional[LangSmithTracer] = None,
    ) -> None:
        if not base_url:
            raise ValueError("A2A base_url 不能为空。")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.tracer = tracer

    def execute_task(
        self,
        payload: A2ATaskPayload,
        root_run=None,
    ) -> A2AResultEnvelope:
        """提交任务并阻塞等待最终结果。"""
        run_ctx = (
            self.tracer.start_run(
                name="a2a_execute_task",
                run_type="tool",
                inputs={"payload": payload.model_dump(mode="json")},
                tags=["a2a", f"agent:{payload.agent}"],
                metadata={"trace_id": payload.trace_id, "a2a_base_url": self.base_url},
                parent=root_run,
            )
            if self.tracer and self.tracer.enabled
            else nullcontext()
        )
        with run_ctx as run:
            task_id = self._submit_task(payload, root_run=root_run)
            for event in self._stream_events(task_id, root_run=root_run):
                if event.event_type == "completed":
                    result_raw = event.data.get("result") if isinstance(event.data, dict) else None
                    if not isinstance(result_raw, dict):
                        raise RuntimeError("A2A completed 事件缺少 result。")
                    result = A2AResultEnvelope.model_validate(result_raw)
                    if run:
                        run.add_outputs({"task_id": task_id, "result": result.model_dump(mode="json")})
                    return result
                if event.event_type == "failed":
                    error_msg = ""
                    if isinstance(event.data, dict):
                        error_msg = str(event.data.get("error", "")).strip()
                    if not error_msg:
                        error_msg = "A2A 任务执行失败。"
                    raise RuntimeError(error_msg)

            # 理论上不会走到这里，兜底拉取一次任务状态
            state = self.get_task_state(task_id, root_run=root_run)
            if state.status == "completed" and state.result:
                if run:
                    run.add_outputs({"task_id": task_id, "result": state.result.model_dump(mode="json")})
                return state.result
            raise RuntimeError(f"A2A 任务未完成，当前状态: {state.status}")

    def _submit_task(self, payload: A2ATaskPayload, root_run=None) -> str:
        run_ctx = (
            self.tracer.start_run(
                name="a2a_submit_task",
                run_type="tool",
                inputs={"payload": payload.model_dump(mode="json")},
                tags=["a2a", "submit", f"agent:{payload.agent}"],
                metadata={"trace_id": payload.trace_id},
                parent=root_run,
            )
            if self.tracer and self.tracer.enabled
            else nullcontext()
        )
        with run_ctx as run:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(f"{self.base_url}/tasks", json=payload.model_dump(mode="json"))
                response.raise_for_status()
                data = response.json()
            task_id = str(data.get("task_id", "")).strip()
            if not task_id:
                raise RuntimeError("A2A 提交响应缺少 task_id。")
            if run:
                run.add_outputs({"task_id": task_id, "status": data.get("status")})
            return task_id

    def _stream_events(self, task_id: str, root_run=None) -> Iterator[A2AEvent]:
        run_ctx = (
            self.tracer.start_run(
                name="a2a_stream_events",
                run_type="tool",
                inputs={"task_id": task_id},
                tags=["a2a", "stream"],
                metadata={},
                parent=root_run,
            )
            if self.tracer and self.tracer.enabled
            else nullcontext()
        )
        with run_ctx as run:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                with client.stream("GET", f"{self.base_url}/tasks/{task_id}/events") as response:
                    response.raise_for_status()
                    for event in self._iter_sse_events(response):
                        if run and event.event_type in {"completed", "failed"}:
                            run.add_outputs({"final_event": event.model_dump(mode="json")})
                        yield event

    @staticmethod
    def _iter_sse_events(response: httpx.Response) -> Iterator[A2AEvent]:
        """解析 SSE 数据流。"""
        event_name = "message"
        data_buf = []
        for raw_line in response.iter_lines():
            line = raw_line.strip()
            if not line:
                if data_buf:
                    raw_payload = "\n".join(data_buf)
                    payload = json.loads(raw_payload)
                    if isinstance(payload, dict):
                        if not payload.get("event_type"):
                            payload["event_type"] = event_name if event_name != "message" else "progress"
                    yield A2AEvent.model_validate(payload)
                event_name = "message"
                data_buf = []
                continue
            if line.startswith("event:"):
                event_name = line[6:].strip()
                continue
            if line.startswith("data:"):
                data_buf.append(line[5:].strip())

    def get_task_state(self, task_id: str, root_run=None) -> A2ATaskState:
        """获取任务当前状态。"""
        run_ctx = (
            self.tracer.start_run(
                name="a2a_get_task_state",
                run_type="tool",
                inputs={"task_id": task_id},
                tags=["a2a", "state"],
                metadata={},
                parent=root_run,
            )
            if self.tracer and self.tracer.enabled
            else nullcontext()
        )
        with run_ctx as run:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(f"{self.base_url}/tasks/{task_id}")
                response.raise_for_status()
                data: Dict[str, Any] = response.json()
            state = A2ATaskState.model_validate(data)
            if run:
                run.add_outputs({"status": state.status})
            return state
