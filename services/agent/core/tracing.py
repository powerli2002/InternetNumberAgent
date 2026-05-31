"""LangSmith 追踪配置模块。

本模块只负责读取 LangSmith 相关环境变量并提供统一配置，
不再包装 `trace()` / `tracing_context()` 的生命周期。
调用方直接使用官方 SDK 创建 run，本模块仅负责：
1. 读取启用状态、项目名、时区、默认 tags 与 metadata；
2. 在追踪开启时初始化 LangSmith Client；
3. 生成统一的 tags / metadata，避免各调用点重复拼装。
"""

from __future__ import annotations

from datetime import datetime
import os
from typing import Any, Dict, List, Optional

from langsmith import Client

try:
    from zoneinfo import ZoneInfo
except Exception:  # Python < 3.9 兼容
    ZoneInfo = None  # type: ignore


class LangSmithTracer:
    """LangSmith 追踪配置容器。

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

    def now_local_iso(self) -> str:
        """返回当前本地时间的 ISO 字符串，便于写入 metadata。"""
        if self._tzinfo is None:
            return datetime.utcnow().isoformat()
        return datetime.now(self._tzinfo).isoformat()

    def build_tags(self, tags: Optional[List[str]] = None) -> List[str]:
        """合并默认 tags 与调用方追加 tags，并去重保序。"""
        return list(dict.fromkeys(list(self.default_tags) + list(tags or [])))

    def build_metadata(self, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """合并默认 metadata，并附加本地时间戳。"""
        return {
            **self.default_metadata,
            **(metadata or {}),
            "local_time": self.now_local_iso(),
        }
