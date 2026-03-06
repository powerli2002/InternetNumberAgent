"""FastMCP 客户端封装。"""

from __future__ import annotations

import asyncio
import contextvars
from contextlib import nullcontext
from dataclasses import asdict, is_dataclass
from concurrent.futures import ThreadPoolExecutor
import time
from typing import Any, Dict, List, Optional

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from langsmith.run_helpers import get_current_run_tree

from agent.core.tracing import LangSmithTracer
from fusiondata.src.utils.logging_manager import logger


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
        """同步调用 MCP 工具，并在控制台输出开始/结束与耗时。"""
        started_at = time.monotonic()
        logger.info("MCP 工具开始 name=%s trace_id=%s", name, trace_id or "-")
        try:
            result = self._run_sync(
                self.call_tool_async(
                    name=name,
                    arguments=arguments,
                    trace_id=trace_id,
                    root_run=root_run,
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
        run_ctx = self._build_tool_run_context(
            name=f"mcp_tool:{name}",
            trace_id=trace_id,
            inputs={
                "name": name,
                "arguments": MCPToolClient._summarize_for_trace(payload),
            },
            tags=["mcp", f"tool:{name}"],
            root_run=root_run,
        )
        with run_ctx as run:
            # 提取当前 LangSmith run tree 的传播 headers，注入到 HTTP 请求，
            # 使 MCP Server 侧的 @traceable 工具调用能嵌套挂到本链路 trace 树下。
            ls_headers: Dict[str, str] = {}
            if rt := get_current_run_tree():
                ls_headers = {k: str(v) for k, v in rt.to_headers().items()}
            transport = StreamableHttpTransport(url=self.server_url, headers=ls_headers or None)
            async with Client(transport, timeout=self.timeout_seconds) as client:
                result = await client.call_tool(
                    name=name,
                    arguments=payload,
                    timeout=self.timeout_seconds,
                    meta={"trace_id": trace_id},
                    raise_on_error=True,
                )
            normalized = self._normalize_result(result)
            if run and hasattr(run, "add_outputs"):
                run.add_outputs({"name": name, "result": MCPToolClient._summarize_for_trace(normalized)})
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

        run_ctx = self._build_tool_run_context(
            name="mcp_list_tools",
            trace_id=trace_id,
            inputs={"server_url": self.server_url, "refresh": bool(refresh)},
            tags=["mcp", "tools", "list"],
            root_run=root_run,
        )
        with run_ctx as run:
            async with Client(self.server_url, timeout=self.timeout_seconds) as client:
                tools = await client.list_tools()
            normalized = [self._normalize_tool(tool) for tool in tools]
            self._tools_cache = normalized
            self._tools_cache_expires_at = time.monotonic() + 30.0
            if run and hasattr(run, "add_outputs"):
                run.add_outputs(
                    {
                        "count": len(normalized),
                        "names": [str(item.get("name") or "") for item in normalized[:50]],
                    }
                )
            return list(normalized)

    def _build_tool_run_context(
        self,
        name: str,
        trace_id: str,
        inputs: Dict[str, Any],
        tags: List[str],
        root_run=None,
    ):
        """构造 MCP 客户端子 run 上下文，且仅允许挂载到已有 root run。"""
        if not self.tracer or not self.tracer.enabled:
            return nullcontext()
        # 强制要求 parent run 存在且具备 id，避免误创建新的根 trace。
        if root_run is None or not hasattr(root_run, "id"):
            logger.debug("跳过 MCP 子 run：缺少可用 root_run name=%s trace_id=%s", name, trace_id or "-")
            return nullcontext()
        return self.tracer.start_run(
            name=name,
            run_type="tool",
            inputs=inputs,
            tags=tags,
            metadata={"trace_id": trace_id, "mcp_server": self.server_url},
            parent=root_run,
        )

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
    def _summarize_for_trace(value: Any, depth: int = 0) -> Any:
        """将输入输出压缩为可读摘要，降低 LangSmith 噪声。"""
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            if len(value) <= 200:
                return value
            return f"{value[:200]}...<truncated {len(value)} chars>"
        if depth >= 2:
            text = str(value)
            if len(text) > 200:
                text = f"{text[:200]}...<truncated {len(text)} chars>"
            return {"type": type(value).__name__, "preview": text}
        if isinstance(value, list):
            return {
                "type": "list",
                "length": len(value),
                "sample": [MCPToolClient._summarize_for_trace(item, depth + 1) for item in value[:3]],
            }
        if isinstance(value, dict):
            raw_keys = list(value.keys())[:20]
            keys = [str(k) for k in raw_keys]
            summary: Dict[str, Any] = {
                "type": "dict",
                "size": len(value),
                "keys": keys,
            }
            if isinstance(value.get("chunks"), list):
                summary["chunk_count"] = len(value["chunks"])
            if isinstance(value.get("notes"), list):
                summary["note_count"] = len(value["notes"])
            if "sql" in value:
                sql_text = str(value.get("sql") or "")
                summary["sql_preview"] = sql_text[:200] + (f"...<truncated {len(sql_text)} chars>" if len(sql_text) > 200 else "")
            sample_keys = raw_keys[:5]
            if sample_keys:
                summary["sample"] = {
                    str(key): MCPToolClient._summarize_for_trace(value.get(key), depth + 1)
                    for key in sample_keys
                }
            return summary
        text = str(value)
        if len(text) <= 200:
            return {"type": type(value).__name__, "preview": text}
        return {"type": type(value).__name__, "preview": f"{text[:200]}...<truncated {len(text)} chars>"}

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
