from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from langsmith import Client
from langsmith.run_helpers import trace


class LangSmithTracer:
    """LangSmith 追踪封装，按环境变量启用。"""

    def __init__(self, project_name: Optional[str] = None) -> None:
        # 通过环境变量统一开关，避免生产环境无意开销
        self.enabled = os.getenv("LANGSMITH_TRACING", "").lower() == "true"
        self.project_name = project_name or os.getenv("LANGSMITH_PROJECT", "internet-number-qa")
        self.client: Optional[Client] = None
        if self.enabled:
            # 必须配置 API key 与 workspace，否则直接报错
            api_key = os.getenv("LANGSMITH_API_KEY")
            workspace_id = os.getenv("LANGSMITH_WORKSPACE_ID")
            if not api_key or not workspace_id:
                raise RuntimeError("LangSmith 追踪已开启，但缺少 LANGSMITH_API_KEY 或 LANGSMITH_WORKSPACE_ID。")
            self.client = Client()

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
        # 统一封装 trace，调用方只需关心 name/run_type/inputs
        return trace(
            name=name,
            run_type=run_type,
            inputs=inputs,
            tags=tags,
            metadata=metadata,
            parent=parent,
            project_name=self.project_name,
            client=self.client,
        )
