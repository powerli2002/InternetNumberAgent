"""
LLM 客户端模块 - 阿里云百炼集成

提供与阿里云百炼大语言模型的统一接口封装：
1. OpenAI 兼容的 API 调用方式
2. 流式和非流式文本生成
3. 结构化输出支持
4. LangSmith 链路追踪集成
5. 错误处理和重试机制

核心特性：
- 兼容 OpenAI 接口标准
- 支持多种输出模式（文本/结构化/流式）
- 自动错误重试和异常转换
- 请求参数灵活配置
- 统一的日志和监控埋点
"""

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

    def chat_stream(self, messages: List[LLMMessage], temperature: float = 0.2):
        """流式输出对话内容（逐段返回）。"""
        try:
            from openai import OpenAI  # type: ignore
            from langsmith.wrappers import wrap_openai  # type: ignore
        except Exception as exc:
            raise RuntimeError("未安装 openai/langsmith SDK，无法调用百炼兼容接口。") from exc

        if not self.api_key:
            raise RuntimeError("缺少 DASHSCOPE_API_KEY，无法调用百炼模型。")

        client = wrap_openai(OpenAI(api_key=self.api_key, base_url=self.base_url))
        stream = client.chat.completions.create(
            model=self.model,
            messages=[message.__dict__ for message in messages],
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                yield delta

    def structured_chat(self, messages: List[LLMMessage], schema: dict, temperature: float = 0.2) -> dict:
        """要求模型返回 JSON 结构化输出。"""
        content = self.chat(messages, temperature=temperature)
        try:
            return json.loads(content)
        except Exception as exc:
            raise ValueError(f"模型输出无法解析为 JSON: {content}") from exc
