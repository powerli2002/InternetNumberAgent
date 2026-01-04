from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class LLMMessage:
    """统一的 LLM 消息格式。"""

    role: str
    content: str


class LLMClient:
    """阿里云百炼兼容 OpenAI 模式调用接口。"""

    def __init__(
        self,
        api_key: Optional[str],
        base_url: str,
        model: str,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def chat(self, messages: List[LLMMessage], temperature: float = 0.2) -> str:
        """执行对话请求，若缺少依赖则抛出清晰异常。"""
        try:
            from openai import OpenAI  # type: ignore
            from langsmith.wrappers import wrap_openai  # type: ignore
        except Exception as exc:
            raise RuntimeError("未安装 openai/langsmith SDK，无法调用百炼兼容接口。") from exc

        if not self.api_key:
            raise RuntimeError("缺少 DASHSCOPE_API_KEY，无法调用百炼模型。")

        client = wrap_openai(OpenAI(api_key=self.api_key, base_url=self.base_url))
        response = client.chat.completions.create(
            model=self.model,
            messages=[message.__dict__ for message in messages],
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    def structured_chat(self, messages: List[LLMMessage], schema: dict, temperature: float = 0.2) -> dict:
        """要求模型返回 JSON 结构化输出。"""
        content = self.chat(messages, temperature=temperature)
        try:
            return json.loads(content)
        except Exception as exc:
            raise ValueError(f"模型输出无法解析为 JSON: {content}") from exc
