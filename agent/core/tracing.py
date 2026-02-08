"""
链路追踪模块 - LangSmith 集成

提供完整的 LLM 和工具调用链路追踪功能：
1. 自动化的运行记录和嵌套关系
2. 性能指标收集（耗时、token 数等）
3. 错误追踪和调试信息
4. 可视化链路图和分析报表
5. 生产环境的可选启用机制

追踪策略：
- 按环境变量控制启用状态
- 支持嵌套运行（父子关系）
- 自动记录输入输出和元数据
- 提供丰富的标签和过滤能力
"""

from __future__ import annotations

import os
import random
from typing import Any, Dict, List, Optional

from langsmith import Client
from langsmith.run_helpers import trace


class LangSmithTracer:
    """LangSmith 追踪封装，按环境变量启用。"""

    def __init__(self, project_name: Optional[str] = None) -> None:
        # 通过环境变量统一开关，避免生产环境无意开销
        self.enabled = os.getenv("LANGSMITH_TRACING", "").lower() == "true"
        self.project_name = project_name or os.getenv("LANGSMITH_PROJECT", "internet-number-qa")
        # 采样率（0-1），用于降低追踪成本
        try:
            self.sample_rate = float(os.getenv("LANGSMITH_SAMPLE_RATE", "1.0"))
        except ValueError:
            self.sample_rate = 1.0
        self.sample_rate = max(0.0, min(1.0, self.sample_rate))
        # 默认标签便于集中筛选
        raw_tags = os.getenv("LANGSMITH_DEFAULT_TAGS", "")
        self.default_tags = [tag.strip() for tag in raw_tags.split(",") if tag.strip()]
        self.default_metadata = {"service": "fusion-agent"}
        self.client: Optional[Client] = None
        if self.enabled:
            # 必须配置 API key 与 workspace，否则直接报错
            api_key = os.getenv("LANGSMITH_API_KEY")
            workspace_id = os.getenv("LANGSMITH_WORKSPACE_ID")
            if not api_key or not workspace_id:
                raise RuntimeError("LangSmith 追踪已开启，但缺少 LANGSMITH_API_KEY 或 LANGSMITH_WORKSPACE_ID。")
            self.client = Client()

    def _should_sample(self) -> bool:
        if self.sample_rate >= 1.0:
            return True
        return random.random() <= self.sample_rate

    def start_run(
        self,
        name: str,
        run_type: str = "chain",
        inputs: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        parent: Optional[Any] = None,
    ):
        if not self.enabled:
            raise RuntimeError("LangSmith 追踪未启用，无法创建 run。")
        if not self._should_sample():
            return _NoopRun()
        merged_tags = list(self.default_tags)
        if tags:
            merged_tags.extend(tags)
        merged_metadata = dict(self.default_metadata)
        if metadata:
            merged_metadata.update(metadata)
        # 统一封装 trace，调用方只需关心 name/run_type/inputs
        return trace(
            name=name,
            run_type=run_type,
            inputs=inputs,
            tags=merged_tags,
            metadata=merged_metadata,
            parent=parent,
            project_name=self.project_name,
            client=self.client,
        )


class _NoopRun:
    """采样关闭时的空 run，保持上下文管理器接口。"""

    def __enter__(self):  # noqa: D401
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: D401
        return False

    def add_outputs(self, _outputs: Optional[Dict[str, Any]] = None) -> None:
        return None
