"""FastMCP 客户端封装。"""

from __future__ import annotations

import asyncio
import contextvars
from dataclasses import asdict, is_dataclass
from concurrent.futures import ThreadPoolExecutor
import time
from typing import Any, Dict, List, Optional

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from langsmith.run_helpers import get_current_run_tree

from fusiondata.src.utils.logging_manager import logger


class MCPToolClient:
    """统一 MCP 工具调用客户端。"""

    def __init__(
        self,
        server_url: str,
        timeout_seconds: int = 60,
    ) -> None:
        if not server_url:
            raise ValueError("MCP server_url 不能为空。")
        self.server_url = server_url.rstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds))
        self._tools_cache: List[Dict[str, Any]] = []
        self._tools_cache_expires_at: float = 0.0

    def call_tool(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
    ) -> Any:
        """同步调用 MCP 工具，并在控制台输出开始/结束与耗时。"""
        started_at = time.monotonic()
        logger.info("MCP 工具开始 name=%s trace_id=%s", name, trace_id or "-")
        try:
            result = self._run_sync(
                self.call_tool_async(
                    name=name,
                    arguments=arguments,
                    trace_id=trace_id,
                )
            )
            logger.info(
                "MCP 工具完成 name=%s trace_id=%s elapsed=%.2fs",
                name,
                trace_id or "-",
                time.monotonic() - started_at,
            )
            return result
        except Exception as exc:
            logger.warning(
                "MCP 工具失败 name=%s trace_id=%s elapsed=%.2fs error=%s",
                name,
                trace_id or "-",
                time.monotonic() - started_at,
                exc,
            )
            raise

    def list_tools_sync(
        self,
        trace_id: str = "",
        refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """同步获取 MCP 工具列表。"""
        return self._run_sync(
            self.list_tools(
                trace_id=trace_id,
                refresh=refresh,
            )
        )

    async def call_tool_async(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
    ) -> Any:
        """异步调用 MCP 工具。"""
        payload = arguments or {}
        # 只透传当前 LangSmith trace 头，客户端不再手工创建 mcp_tool:* span，
        # 工具级 span 统一由 MCP Server 侧的 TracingMiddleware + ls_trace() 记录。
        transport = self._build_transport()
        async with Client(transport, timeout=self.timeout_seconds) as client:
            result = await client.call_tool(
                name=name,
                arguments=payload,
                timeout=self.timeout_seconds,
                meta={"trace_id": trace_id},
                raise_on_error=True,
            )
        return self._normalize_result(result)

    async def list_tools(
        self,
        trace_id: str = "",
        refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """异步读取 MCP 工具元数据，并做短时缓存。"""
        now = time.monotonic()
        if not refresh and self._tools_cache and now < self._tools_cache_expires_at:
            return list(self._tools_cache)

        transport = self._build_transport()
        async with Client(transport, timeout=self.timeout_seconds) as client:
            tools = await client.list_tools()
        normalized = [self._normalize_tool(tool) for tool in tools]
        self._tools_cache = normalized
        self._tools_cache_expires_at = time.monotonic() + 30.0
        return list(normalized)

    def _build_transport(self) -> StreamableHttpTransport:
        """构造带 LangSmith 分布式追踪头的 HTTP 传输层。"""
        ls_headers: Dict[str, str] = {}
        if rt := get_current_run_tree():
            ls_headers = {key: str(value) for key, value in rt.to_headers().items()}
        return StreamableHttpTransport(url=self.server_url, headers=ls_headers or None)

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
            # 已有事件循环时切到新线程运行协程，并显式继承 contextvars。
            ctx = contextvars.copy_context()
            with ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(lambda: ctx.run(asyncio.run, coro)).result()
        return asyncio.run(coro)
