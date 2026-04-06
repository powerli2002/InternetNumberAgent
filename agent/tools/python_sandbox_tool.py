"""Python 沙箱工具。

职责分层：
1. 由 Agent 侧 LLM 根据 task/context 生成 Python 代码；
2. 通过 HTTP 调用产品后端内部沙箱接口执行代码；
3. 返回 stdout/stderr/产物摘要给 LangGraph 主流程。

本模块不依赖 backend 包，只依赖公开 HTTP 契约，保持模块边界单向。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import httpx

from agent.core.config import AgentConfig
from agent.core.llm import LLMClient, LLMMessage


PYTHON_CODEGEN_PROMPT = """你是 Python 执行助手。你的任务是根据用户 task 编写可直接执行的 Python 3.11 代码。

硬约束：
1) 只输出 Python 代码，不要输出 Markdown、解释或 ``` 代码块；
2) 如需生成图片、CSV、JSON、TXT、PDF 等文件，统一写入 /workspace/artifacts；
3) 如需打印结果，使用 print；
4) 代码必须自包含，可直接作为 main.py 执行；
5) 如果 task 提到图表，请优先生成 PNG；
6) 禁止访问系统敏感路径，只能使用 /workspace 目录；
7) 若 task 需要第三方依赖，只假设 packages 中已提前安装。
"""


class PythonSandboxTool:
    """通过产品后端沙箱接口执行 Python。"""

    def __init__(self, config: AgentConfig, llm_client: LLMClient) -> None:
        self.config = config
        self.llm = llm_client

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        """剥离模型偶发输出的 Markdown 代码围栏。"""
        raw = str(text or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-zA-Z0-9_+-]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        return raw.strip()

    def generate_code(
        self,
        task: str,
        *,
        context: str = "",
        packages: Optional[List[str]] = None,
    ) -> str:
        """使用当前主模型生成 Python 代码。"""
        package_list = [str(item).strip() for item in (packages or []) if str(item).strip()]
        payload = {
            "task": str(task or "").strip(),
            "context": str(context or "").strip(),
            "packages": package_list,
        }
        messages = [
            LLMMessage(role="system", content=PYTHON_CODEGEN_PROMPT),
            LLMMessage(role="user", content=str(payload)),
        ]
        code = self.llm.chat(messages, temperature=0.0)
        cleaned = self._strip_code_fence(code)
        if not cleaned:
            raise RuntimeError("Python 代码生成失败：模型返回为空。")
        return cleaned

    def execute(
        self,
        task: str,
        *,
        context: str = "",
        packages: Optional[List[str]] = None,
        timeout_seconds: Optional[int] = None,
        trace_id: str = "",
        thread_id: str = "",
        run_id: str = "",
    ) -> Dict[str, Any]:
        """生成代码并调用后端内部沙箱接口执行。"""
        code = self.generate_code(task, context=context, packages=packages)
        api_url = self.config.sandbox_api_url.rstrip("/")
        if not api_url:
            raise RuntimeError("缺少 SANDBOX_API_URL，无法调用产品后端沙箱服务。")
        payload = {
            "task": str(task or "").strip(),
            "context": str(context or "").strip(),
            "packages": [str(item).strip() for item in (packages or []) if str(item).strip()],
            "timeout_seconds": int(timeout_seconds or self.config.sandbox_timeout_seconds),
            "trace_id": str(trace_id or ""),
            "thread_id": str(thread_id or ""),
            "run_id": str(run_id or ""),
            "code": code,
        }
        headers: Dict[str, str] = {}
        if self.config.sandbox_service_token:
            headers["X-Service-Token"] = self.config.sandbox_service_token
        response = httpx.post(
            f"{api_url}/internal/sandbox/python",
            json=payload,
            headers=headers or None,
            timeout=max(5, int(timeout_seconds or self.config.sandbox_timeout_seconds)),
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise RuntimeError("产品后端沙箱接口返回了无效响应。")
        result["code"] = code
        return result
