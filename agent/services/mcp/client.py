"""FastMCP 客户端封装。"""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import asdict, is_dataclass
from concurrent.futures import ThreadPoolExecutor
import time
from typing import Any, Dict, List, Optional

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
        self._tools_cache: List[Dict[str, Any]] = []
        self._tools_cache_expires_at: float = 0.0

    def call_tool(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
        root_run=None,
    ) -> Any:
        """同步调用 MCP 工具。"""
        return self._run_sync(
            self.call_tool_async(
                name=name,
                arguments=arguments,
                trace_id=trace_id,
                root_run=root_run,
            )
        )

    def list_tools_sync(
        self,
        trace_id: str = "",
        root_run=None,
        refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """同步获取 MCP 工具列表。"""
        return self._run_sync(
            self.list_tools(
                trace_id=trace_id,
                root_run=root_run,
                refresh=refresh,
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
                    timeout=self.timeout_seconds,
                    meta={"trace_id": trace_id},
                    raise_on_error=True,
                )
            normalized = self._normalize_result(result)
            if run:
                run.add_outputs({"name": name, "result": normalized})
            return normalized

    async def list_tools(
        self,
        trace_id: str = "",
        root_run=None,
        refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """异步读取 MCP 工具元数据，并做短时缓存。"""
        now = time.monotonic()
        if not refresh and self._tools_cache and now < self._tools_cache_expires_at:
            return list(self._tools_cache)

        run_ctx = (
            self.tracer.start_run(
                name="mcp_list_tools",
                run_type="tool",
                inputs={"server_url": self.server_url},
                tags=["mcp", "tools", "list"],
                metadata={"trace_id": trace_id, "mcp_server": self.server_url},
                parent=root_run,
            )
            if self.tracer and self.tracer.enabled
            else nullcontext()
        )
        with run_ctx as run:
            async with Client(self.server_url, timeout=self.timeout_seconds) as client:
                tools = await client.list_tools()
            normalized = [self._normalize_tool(tool) for tool in tools]
            self._tools_cache = normalized
            self._tools_cache_expires_at = time.monotonic() + 30.0
            if run:
                run.add_outputs({"count": len(normalized), "names": [item.get("name") for item in normalized]})
            return list(normalized)

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

    @staticmethod
    def _normalize_tool(tool: Any) -> Dict[str, Any]:
        """将 MCP 工具对象规整为轻量字典。"""
        if hasattr(tool, "model_dump"):
            data = tool.model_dump(mode="json")
            if isinstance(data, dict):
                return data
        if isinstance(tool, dict):
            return dict(tool)
        return {
            "name": getattr(tool, "name", ""),
            "description": getattr(tool, "description", ""),
            "inputSchema": getattr(tool, "inputSchema", {}),
        }

    @staticmethod
    def _run_sync(coro):
        """在同步上下文安全运行异步协程。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # 运行在线程内，避免在已有事件循环中直接 asyncio.run。
            with ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(lambda: asyncio.run(coro)).result()
        return asyncio.run(coro)
