"""工具层基类：BaseTool + ToolResult。

设计参考 OpenJudge agentic/tools.py，适配 Anthropic tool_use 格式（input_schema
而非 OpenAI 的 function.parameters），异步优先，同步包装供脚本调用。
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


__all__ = ["ToolResult", "BaseTool"]


@dataclass
class ToolResult:
    """工具调用的标准化返回结构。

    所有继承 BaseTool 的工具都应返回此类型，调用方通过 success 判断是否成功，
    通过 metadata 获取耗时、来源等溯源信息。
    """

    success: bool = True
    output: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    """工具基类，schema 遵循 Anthropic tool_use 格式。

    子类必须：
    1. 覆盖 schema 类属性，填入 name / description / input_schema；
    2. 实现 aexecute(**kwargs) → ToolResult。

    执行耗时由 execute / aexecute_timed 自动写入 metadata["elapsed_ms"]。
    """

    schema: Dict[str, Any] = {
        "name": "base_tool",
        "description": "工具基类，子类必须覆盖此属性。",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    }

    @property
    def name(self) -> str:
        return self.schema.get("name", "unknown")

    @property
    def description(self) -> str:
        return self.schema.get("description", "")

    @property
    def input_schema(self) -> Dict[str, Any]:
        return self.schema.get("input_schema", {})

    @abstractmethod
    async def aexecute(self, **kwargs: Any) -> ToolResult:
        """异步执行工具，子类必须实现。"""

    async def aexecute_timed(self, **kwargs: Any) -> ToolResult:
        """执行工具并将耗时写入 metadata["elapsed_ms"]。"""
        t0 = time.monotonic()
        result = await self.aexecute(**kwargs)
        result.metadata.setdefault("elapsed_ms", int((time.monotonic() - t0) * 1000))
        result.metadata.setdefault("tool", self.name)
        return result

    def execute(self, **kwargs: Any) -> ToolResult:
        """同步包装，供脚本或测试调用。"""
        return asyncio.run(self.aexecute_timed(**kwargs))
