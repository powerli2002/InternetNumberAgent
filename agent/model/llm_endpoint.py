"""
统一解析当前生效的 OpenAI 兼容 LLM 端点配置。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LLMEndpoint:
    """当前生效的 LLM 端点。"""

    backend: str
    api_key: str
    base_url: str
    model: str


def _require_non_empty(value: Optional[str], env_name: str, backend: str) -> str:
    """校验关键字段，缺失时直接报错并给出修复项。"""
    text = (value or "").strip()
    if not text:
        raise ValueError(f"LLM_BACKEND={backend} 时缺少环境变量 {env_name}。")
    return text


def resolve_llm_endpoint(
    *,
    backend: str,
    dashscope_api_key: Optional[str],
    dashscope_base_url: Optional[str],
    dashscope_model: Optional[str],
    local_llm_api_key: Optional[str],
    local_llm_base_url: Optional[str],
    local_llm_model: Optional[str],
) -> LLMEndpoint:
    """按 backend 解析并返回唯一生效的端点配置（不做回退）。"""
    normalized_backend = (backend or "").strip().lower()
    if normalized_backend not in {"cloud", "local"}:
        raise ValueError("LLM_BACKEND 仅支持 cloud 或 local。")

    if normalized_backend == "cloud":
        return LLMEndpoint(
            backend="cloud",
            api_key=_require_non_empty(dashscope_api_key, "DASHSCOPE_API_KEY", "cloud"),
            base_url=_require_non_empty(dashscope_base_url, "DASHSCOPE_BASE_URL", "cloud"),
            model=_require_non_empty(dashscope_model, "DASHSCOPE_MODEL", "cloud"),
        )

    return LLMEndpoint(
        backend="local",
        api_key=_require_non_empty(local_llm_api_key, "LOCAL_LLM_API_KEY", "local"),
        base_url=_require_non_empty(local_llm_base_url, "LOCAL_LLM_BASE_URL", "local"),
        model=_require_non_empty(local_llm_model, "LOCAL_LLM_MODEL", "local"),
    )
