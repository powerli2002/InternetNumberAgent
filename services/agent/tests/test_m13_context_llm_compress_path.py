from __future__ import annotations

from typing import Callable, Optional

import pytest

from agent.runtime.context_builder import ContextBuilder


class _FakeLLM:
    """可控的 LLM 桩对象。"""

    def __init__(
        self,
        response: str = "",
        raise_error: bool = False,
        handler: Optional[Callable[[str, int], str]] = None,
    ) -> None:
        self.response = response
        self.raise_error = raise_error
        self.handler = handler
        self.called = 0
        self.last_messages = None
        self.contents: list[str] = []

    def chat(self, messages, temperature: float = 0.2) -> str:
        self.called += 1
        self.last_messages = messages
        content = str(messages[-1].content)
        self.contents.append(content)
        if self.raise_error:
            raise RuntimeError("mock llm error")
        if self.handler is not None:
            return self.handler(content, self.called)
        return self.response


def test_context_compress_always_uses_llm_even_when_within_budget() -> None:
    """即使原始上下文未超预算，也统一走 LLM 压缩。"""
    llm = _FakeLLM(response="压缩后上下文")
    builder = ContextBuilder(
        max_tokens=200,
        token_counter=lambda text: len(text),
        llm_client=llm,  # type: ignore[arg-type]
    )

    compressed = builder.compress("[Task]\n查询 AS4134")
    assert llm.called == 1
    assert compressed == "压缩后上下文"


def test_build_with_trace_skips_llm_when_context_within_budget() -> None:
    """完整构建流程在未超预算时不应触发 LLM 压缩。"""
    llm = _FakeLLM(response="压缩后上下文")
    builder = ContextBuilder(
        max_tokens=200,
        token_counter=lambda text: len(text),
        llm_client=llm,  # type: ignore[arg-type]
    )

    context, trace_payload = builder.build_with_trace(
        system_prompt="系统提示",
        user_query="查询 AS4134",
        history=[],
        memories=[],
        evidences=[],
        notes=[],
    )

    assert llm.called == 0
    assert context == trace_payload["context_before_compress"]
    assert trace_payload["token_stats"]["compression_applied"] is False


def test_context_compress_splits_evidence_and_other_then_calls_llm() -> None:
    """包含 Evidence 时，应分成 Evidence 与 Other 两桶分别调用 LLM。"""
    llm = _FakeLLM(
        handler=lambda content, _: "证据压缩" if content.startswith("[Evidence]") else "其他压缩",
    )
    builder = ContextBuilder(
        max_tokens=80,
        token_counter=lambda text: len(text),
        llm_client=llm,  # type: ignore[arg-type]
    )
    context = (
        "[Role & Policy]\n规则说明\n\n"
        "[Evidence]\nSQL 结果：AS4134\n\n"
        "[Context]\n历史对话"
    )

    compressed = builder.compress(context)
    assert llm.called == 2
    assert compressed == "其他压缩\n\n证据压缩"


def test_context_compress_chunks_large_input_before_calling_llm() -> None:
    """单段输入超出单次请求预算时，应分块多次调用 LLM。"""
    llm = _FakeLLM(handler=lambda _content, call_index: f"压缩块{call_index}")
    builder = ContextBuilder(
        max_tokens=80,
        token_counter=lambda text: len(text),
        llm_client=llm,  # type: ignore[arg-type]
    )
    context = "[Context]\n" + ("超长内容段落\n" * 40)

    compressed = builder.compress(context)
    assert llm.called > 1
    assert compressed
    assert all(len(content) <= builder._llm_input_budget() for content in llm.contents)


def test_split_into_llm_chunks_uses_fixed_token_window_after_paragraph_split() -> None:
    """段落仍超预算时，应直接按固定 token 窗口切分，而不是按行聚合。"""
    builder = ContextBuilder(
        max_tokens=100,
        token_counter=lambda text: len(text),
        llm_client=_FakeLLM(response="压缩后上下文"),  # type: ignore[arg-type]
    )
    long_paragraph = "第1行\n" * 30

    chunks = builder._split_into_llm_chunks(long_paragraph, builder._llm_input_budget())
    assert len(chunks) > 1
    assert all(len(chunk) <= builder._llm_input_budget() for chunk in chunks)


def test_context_compress_raises_when_llm_fails() -> None:
    """统一 LLM 压缩失败时应直接抛错，不再回退截断。"""
    llm = _FakeLLM(raise_error=True)
    builder = ContextBuilder(
        max_tokens=80,
        token_counter=lambda text: len(text),
        llm_client=llm,  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="mock llm error"):
        builder.compress("[Context]\n需要压缩的上下文")
