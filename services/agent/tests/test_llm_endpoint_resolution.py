from __future__ import annotations

import pytest

from agent.model.llm_endpoint import resolve_llm_endpoint


def test_resolve_cloud_endpoint_success() -> None:
    endpoint = resolve_llm_endpoint(
        backend="cloud",
        dashscope_api_key="cloud-key",
        dashscope_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        dashscope_model="qwen3-max-preview",
        local_llm_api_key="",
        local_llm_base_url="",
        local_llm_model="",
    )
    assert endpoint.backend == "cloud"
    assert endpoint.api_key == "cloud-key"
    assert endpoint.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert endpoint.model == "qwen3-max-preview"


def test_resolve_local_endpoint_success() -> None:
    endpoint = resolve_llm_endpoint(
        backend="local",
        dashscope_api_key="",
        dashscope_base_url="",
        dashscope_model="",
        local_llm_api_key="local-key",
        local_llm_base_url="http://127.0.0.1:2222/v1",
        local_llm_model="qwen3.5-7b-instruct",
    )
    assert endpoint.backend == "local"
    assert endpoint.api_key == "local-key"
    assert endpoint.base_url == "http://127.0.0.1:2222/v1"
    assert endpoint.model == "qwen3.5-7b-instruct"


def test_resolve_invalid_backend_raises() -> None:
    with pytest.raises(ValueError, match="LLM_BACKEND"):
        resolve_llm_endpoint(
            backend="invalid",
            dashscope_api_key="x",
            dashscope_base_url="x",
            dashscope_model="x",
            local_llm_api_key="x",
            local_llm_base_url="x",
            local_llm_model="x",
        )


@pytest.mark.parametrize(
    ("api_key", "base_url", "model", "missing_env"),
    [
        ("", "http://127.0.0.1:2222/v1", "qwen3.5-7b-instruct", "LOCAL_LLM_API_KEY"),
        ("local-key", "", "qwen3.5-7b-instruct", "LOCAL_LLM_BASE_URL"),
        ("local-key", "http://127.0.0.1:2222/v1", "", "LOCAL_LLM_MODEL"),
    ],
)
def test_resolve_local_missing_required_fields(api_key: str, base_url: str, model: str, missing_env: str) -> None:
    with pytest.raises(ValueError, match=missing_env):
        resolve_llm_endpoint(
            backend="local",
            dashscope_api_key="cloud-key",
            dashscope_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            dashscope_model="qwen3-max-preview",
            local_llm_api_key=api_key,
            local_llm_base_url=base_url,
            local_llm_model=model,
        )
