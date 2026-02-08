"""FastMCP 客户端封装。"""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Optional

from fastmcp import Client

from agent.core.tracing import LangSmithTracer


class MCPToolClient:
    """统一 MCP 工具调用客户端。"""

    def __init__(
        self,
        server_url: str,
        timeout_seconds: int = 60,
        tracer: Optional[LangSmithTracer] = None,
    ) -> None:
        if not server_url:
            raise ValueError("MCP server_url 不能为空。")
        self.server_url = server_url.rstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.tracer = tracer

    def call_tool(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
        root_run=None,
    ) -> Any:
        """同步调用 MCP 工具。"""
        return asyncio.run(
            self.call_tool_async(
                name=name,
                arguments=arguments,
                trace_id=trace_id,
                root_run=root_run,
            )
        )

    async def call_tool_async(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
        root_run=None,
    ) -> Any:
        """异步调用 MCP 工具。"""
        payload = arguments or {}
        run_ctx = (
            self.tracer.start_run(
                name=f"mcp_tool:{name}",
                run_type="tool",
                inputs={"name": name, "arguments": payload},
                tags=["mcp", f"tool:{name}"],
                metadata={"trace_id": trace_id, "mcp_server": self.server_url},
                parent=root_run,
            )
            if self.tracer and self.tracer.enabled
            else nullcontext()
        )
        with run_ctx as run:
            async with Client(self.server_url, timeout=self.timeout_seconds) as client:
                result = await client.call_tool(
                    name=name,
                    arguments=payload,
                    meta={"trace_id": trace_id},
                    raise_on_error=True,
                )
            normalized = self._normalize_result(result)
            if run:
                run.add_outputs({"name": name, "result": normalized})
            return normalized

    @staticmethod
    def _normalize_result(result: Any) -> Any:
        """将 FastMCP 返回结果规整为 JSON 友好结构。"""
        if hasattr(result, "data") and result.data is not None:
            data = result.data
            if hasattr(data, "model_dump"):
                return data.model_dump(mode="json")
            if is_dataclass(data):
                return asdict(data)
            return data
        if hasattr(result, "structured_content") and result.structured_content is not None:
            return result.structured_content
        if hasattr(result, "content"):
            blocks = result.content or []
            texts = []
            for block in blocks:
                text = getattr(block, "text", None)
                if text is None and isinstance(block, dict):
                    text = block.get("text")
                if text:
                    texts.append(str(text))
            return {"text": "\n".join(texts)}
        return result

