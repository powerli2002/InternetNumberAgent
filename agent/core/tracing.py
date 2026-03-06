"""
链路追踪模块 - LangSmith 集成

通过环境变量 LANGSMITH_TRACING=true 启用追踪。
启用后，对 LLM 调用、工具调用等关键节点创建 run，
自动记录输入、输出、耗时、标签和元数据，便于在 LangSmith 控制台中可视化分析。

未启用时，start_run 返回空操作对象，调用方代码无需任何条件判断。
"""

from __future__ import annotations

from datetime import datetime
import os
from typing import Any, Dict, List, Optional

from langsmith import Client
from langsmith.run_helpers import trace

try:
    from zoneinfo import ZoneInfo
except Exception:  # Python < 3.9 兼容
    ZoneInfo = None  # type: ignore


class LangSmithTracer:
    """LangSmith 链路追踪封装。

    通过环境变量统一控制启用状态，避免生产环境产生不必要的追踪开销。

    必须配置的环境变量（启用时）：
        LANGSMITH_TRACING=true
        LANGSMITH_API_KEY=<key>
        LANGSMITH_WORKSPACE_ID=<workspace>

    可选环境变量：
        LANGSMITH_PROJECT      — 项目名称，默认 internet-number-qa
        LANGSMITH_TIMEZONE     — 时间戳时区，默认 Asia/Shanghai
        LANGSMITH_DEFAULT_TAGS — 逗号分隔的默认标签
    """

    def __init__(self, project_name: Optional[str] = None) -> None:
        self.enabled = os.getenv("LANGSMITH_TRACING", "").lower() == "true"
        self.project_name = project_name or os.getenv("LANGSMITH_PROJECT", "internet-number-qa")

        # 追踪时间戳使用北京时间，方便与系统日志对照定位问题
        self.timezone = (os.getenv("LANGSMITH_TIMEZONE") or "Asia/Shanghai").strip() or "Asia/Shanghai"
        self._tzinfo = self._resolve_timezone(self.timezone)

        # 默认标签，便于在 LangSmith 控制台中快速筛选过滤
        raw_tags = os.getenv("LANGSMITH_DEFAULT_TAGS", "")
        self.default_tags: List[str] = [t.strip() for t in raw_tags.split(",") if t.strip()]

        # 每个 run 都会附带的基础元数据
        self.default_metadata: Dict[str, Any] = {
            "service": "fusion-agent",
            "timezone": self.timezone,
        }

        self.client: Optional[Client] = None
        if self.enabled:
            # 缺少凭证时直接报错，避免追踪静默失败后难以排查
            api_key = os.getenv("LANGSMITH_API_KEY")
            workspace_id = os.getenv("LANGSMITH_WORKSPACE_ID")
            if not api_key or not workspace_id:
                raise RuntimeError(
                    "LangSmith 追踪已开启，但缺少 LANGSMITH_API_KEY 或 LANGSMITH_WORKSPACE_ID。"
                )
            self.client = Client()

    def _resolve_timezone(self, timezone_name: str):
        """将时区名称解析为 ZoneInfo 对象，失败时回退到 UTC。"""
        if ZoneInfo is None:
            return None
        try:
            return ZoneInfo(timezone_name)
        except Exception:
            return ZoneInfo("UTC")

    def _now_local_iso(self) -> str:
        """返回当前本地时间的 ISO 字符串，写入 run metadata 便于调试定位。"""
        if self._tzinfo is None:
            return datetime.utcnow().isoformat()
        return datetime.now(self._tzinfo).isoformat()

    def start_run(
        self,
        name: str,
        run_type: str = "chain",
        inputs: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        parent: Optional[Any] = None,
    ):
        """创建一个追踪 run，返回上下文管理器。

        未启用追踪时返回空操作对象，调用方代码无需改变。

        用法示例：
            with tracer.start_run("llm_call", inputs={"prompt": ...}) as run:
                result = llm.invoke(...)
                run.add_outputs({"result": result})
        """
        if not self.enabled:
            # 未启用时返回空操作对象，接口保持一致
            return _NoopRun()

        # 合并默认标签与调用方传入的标签
        merged_tags = list(self.default_tags) + (tags or [])

        # 合并默认元数据，并附上本地时间戳便于排查
        merged_metadata = {
            **self.default_metadata,
            **(metadata or {}),
            "local_time": self._now_local_iso(),
        }

        run_ctx = trace(
            name=name,
            run_type=run_type,
            inputs=inputs,
            tags=merged_tags,
            metadata=merged_metadata,
            parent=parent,
            project_name=self.project_name,
            client=self.client,
        )
        return _ScopedRun(run_ctx)


class _NoopRun:
    """追踪未启用时的空操作 run，与 _ScopedRun 保持相同接口。"""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def add_outputs(self, _outputs: Optional[Dict[str, Any]] = None) -> None:
        pass


class _ScopedRun:
    """包装 LangSmith trace 上下文管理器，对外暴露统一接口。"""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __enter__(self):
        return self._inner.__enter__()

    def __exit__(self, exc_type, exc, tb):
        return self._inner.__exit__(exc_type, exc, tb)
