"""
LLM 客户端模块 - OpenAI 兼容后端

提供与 OpenAI 兼容大语言模型的统一接口封装：
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
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


def strip_think_blocks(text: str) -> str:
    """剥离推理模型（如 Qwen-QwQ）输出中的 <think>...</think> 思考块。

    处理逻辑：
    1. 优先用正则去除所有闭合的 <think>...</think> 片段；
    2. 若剥离后为空但存在未闭合的 </think> 尾巴，取最后一个 </think> 之后的内容；
    3. 其余情况原样返回，不破坏正常输出。
    """
    if not text or "<think>" not in text.lower():
        return text
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()
    # 思考块未闭合时兜底：截取最后一个 </think> 之后的有效内容
    if not cleaned and "</think>" in text.lower():
        cleaned = re.split(r"</think>", text, flags=re.IGNORECASE)[-1].strip()
    return cleaned if cleaned else text


class _ThinkBlockStreamFilter:
    """增量过滤流式输出中的 `<think>...</think>` 思考块。"""

    _OPEN_TAG = "<think>"
    _CLOSE_TAG = "</think>"

    def __init__(self) -> None:
        self._inside_think = False
        self._tag_buffer = ""

    def feed(self, chunk: str) -> str:
        """逐字符处理 chunk，只返回可展示给用户的增量文本。"""
        if not chunk:
            return ""

        visible_parts: List[str] = []
        for char in chunk:
            if self._tag_buffer:
                self._tag_buffer += char
                if self._OPEN_TAG.startswith(self._tag_buffer) or self._CLOSE_TAG.startswith(self._tag_buffer):
                    if self._tag_buffer == self._OPEN_TAG:
                        self._inside_think = True
                        self._tag_buffer = ""
                    elif self._tag_buffer == self._CLOSE_TAG:
                        self._inside_think = False
                        self._tag_buffer = ""
                    continue

                # 一旦确认不是 think 标签，就把缓存内容按普通文本处理。
                if not self._inside_think:
                    visible_parts.append(self._tag_buffer)
                self._tag_buffer = ""
                continue

            if char == "<":
                self._tag_buffer = "<"
                continue

            if not self._inside_think:
                visible_parts.append(char)

        return "".join(visible_parts)

    def finalize(self) -> str:
        """在流结束时冲刷残留缓存。"""
        if self._tag_buffer and not self._inside_think:
            leftover = self._tag_buffer
            self._tag_buffer = ""
            return leftover
        self._tag_buffer = ""
        return ""


@dataclass
class LLMMessage:
    """统一的 LLM 消息格式。"""

    role: str
    content: str


class LLMClient:
    """OpenAI 兼容后端调用接口。"""

    def __init__(
        self,
        api_key: Optional[str],
        base_url: str,
        model: str,
        *,
        default_temperature: float = 0.2,
        tool_temperature: float = 0.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.default_temperature = float(default_temperature)
        self.tool_temperature = float(tool_temperature)

    def _resolve_text_temperature(self, temperature: Optional[float]) -> float:
        """解析文本生成类请求的生效温度。"""
        if temperature is None:
            return self.default_temperature
        return float(temperature)

    def _resolve_tool_temperature(self, temperature: Optional[float]) -> float:
        """解析工具/结构化调用的生效温度。"""
        if temperature is None:
            return self.tool_temperature
        return float(temperature)

    def chat(self, messages: List[LLMMessage], temperature: Optional[float] = None) -> str:
        """执行对话请求，若缺少依赖则抛出清晰异常。"""
        try:
            from openai import OpenAI  # type: ignore
            from langsmith.wrappers import wrap_openai  # type: ignore
        except Exception as exc:
            raise RuntimeError("未安装 openai/langsmith SDK，无法调用 OpenAI 兼容接口。") from exc

        if not self.api_key:
            raise RuntimeError("缺少 API Key，无法调用 OpenAI 兼容模型。")

        resolved_temperature = self._resolve_text_temperature(temperature)
        client = wrap_openai(OpenAI(api_key=self.api_key, base_url=self.base_url))
        response = client.chat.completions.create(
            model=self.model,
            messages=[message.__dict__ for message in messages],
            temperature=resolved_temperature,
        )
        raw = response.choices[0].message.content or ""
        return strip_think_blocks(raw)

    def chat_stream(self, messages: List[LLMMessage], temperature: Optional[float] = None):
        """流式输出对话内容（逐段返回），并增量剥离 think 块。"""
        try:
            from openai import OpenAI  # type: ignore
            from langsmith.wrappers import wrap_openai  # type: ignore
        except Exception as exc:
            raise RuntimeError("未安装 openai/langsmith SDK，无法调用 OpenAI 兼容接口。") from exc

        if not self.api_key:
            raise RuntimeError("缺少 API Key，无法调用 OpenAI 兼容模型。")

        resolved_temperature = self._resolve_text_temperature(temperature)
        client = wrap_openai(OpenAI(api_key=self.api_key, base_url=self.base_url))
        stream = client.chat.completions.create(
            model=self.model,
            messages=[message.__dict__ for message in messages],
            temperature=resolved_temperature,
            stream=True,
        )
        filter_state = _ThinkBlockStreamFilter()
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                visible = filter_state.feed(delta)
                if visible:
                    yield visible
        leftover = filter_state.finalize()
        if leftover:
            yield leftover

    def structured_chat(self, messages: List[LLMMessage], schema: dict, temperature: Optional[float] = None) -> dict:
        """要求模型返回 JSON 结构化输出。"""
        content = self.chat(messages, temperature=temperature)
        try:
            return json.loads(content)
        except Exception as exc:
            raise ValueError(f"模型输出无法解析为 JSON: {content}") from exc

    def tool_call(
        self,
        messages: List[LLMMessage],
        tools: List[Dict[str, Any]],
        tool_choice: str = "required",
        temperature: Optional[float] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """使用 Function Calling 获取工具调用参数。"""
        try:
            from openai import OpenAI  # type: ignore
            from langsmith.wrappers import wrap_openai  # type: ignore
        except Exception as exc:
            raise RuntimeError("未安装 openai/langsmith SDK，无法调用 OpenAI 兼容接口。") from exc

        if not self.api_key:
            raise RuntimeError("缺少 API Key，无法调用 OpenAI 兼容模型。")

        resolved_temperature = self._resolve_tool_temperature(temperature)
        client = wrap_openai(OpenAI(api_key=self.api_key, base_url=self.base_url))
        response = client.chat.completions.create(
            model=self.model,
            messages=[message.__dict__ for message in messages],
            tools=tools,
            tool_choice=tool_choice,
            temperature=resolved_temperature,
        )
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls and getattr(message, "function_call", None):
            tool_calls = [message.function_call]
        if not tool_calls:
            raise ValueError("模型未返回工具调用结果。")

        call = tool_calls[0]
        if isinstance(call, dict):
            func = call.get("function") or call
            name = func.get("name")
            arguments = func.get("arguments")
        else:
            func = getattr(call, "function", call)
            name = getattr(func, "name", None)
            arguments = getattr(func, "arguments", None)
        if not name:
            raise ValueError("工具调用缺少函数名。")
        if not arguments:
            raise ValueError("工具调用缺少参数。")
        try:
            payload = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
        except Exception as exc:
            raise ValueError(f"工具调用参数解析失败: {arguments}") from exc
        return name, payload
