from __future__ import annotations

from agent.runtime.context_builder import ContextBuilder


class _FakeLLM:
    """可控的 LLM 桩对象。"""

    def __init__(self, response: str = "", raise_error: bool = False) -> None:
        self.response = response
        self.raise_error = raise_error
        self.called = 0

    def chat(self, _messages, temperature: float = 0.2) -> str:
        self.called += 1
        if self.raise_error:
            raise RuntimeError("mock llm error")
        return self.response


def test_context_compress_uses_llm_when_over_budget() -> None:
    """超预算时应走 LLM 压缩路径。"""
    llm = _FakeLLM(response="压缩后上下文")
    builder = ContextBuilder(
        max_tokens=20,
        token_counter=lambda text: len(text),
        llm_client=llm,  # type: ignore[arg-type]
        compress_mode="llm",
    )
    context = "原始上下文" * 20

    compressed = builder.compress(context)
    assert llm.called == 1
    assert compressed == "压缩后上下文"


def test_context_compress_fallbacks_to_truncate_when_llm_fails() -> None:
    """LLM 压缩失败时应回退截断策略。"""
    llm = _FakeLLM(raise_error=True)
    builder = ContextBuilder(
        max_tokens=60,
        token_counter=lambda text: len(text),
        llm_client=llm,  # type: ignore[arg-type]
        compress_mode="hybrid",
    )
    context = "A" * 400

    compressed = builder.compress(context)
    assert llm.called == 1
    assert len(compressed) <= 60
