from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

import pytest

from agent.core.config import AgentConfig
from agent.core.llm import LLMClient, LLMMessage

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_context_builder_class():
    """按文件路径加载 ContextBuilder，避免测试环境缺少 LangGraph 依赖时触发包级导入。"""
    module_path = PROJECT_ROOT / "agent" / "runtime" / "context_builder.py"
    spec = importlib.util.spec_from_file_location("agent_runtime_context_builder_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 ContextBuilder 模块: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.ContextBuilder


class _CaptureCompressLLM:
    """记录上下文压缩调用温度的最小桩对象。"""

    def __init__(self) -> None:
        self.temperatures: list[float | None] = []

    def chat(self, messages, temperature: float | None = None) -> str:
        self.temperatures.append(temperature)
        return "压缩后上下文"


def test_agent_config_loads_llm_temperatures_from_env(tmp_path, monkeypatch) -> None:
    """AgentConfig 应从 conf/.env 读取三类 LLM 温度。"""
    conf_dir = tmp_path / "conf"
    conf_dir.mkdir(parents=True, exist_ok=True)
    (conf_dir / ".env").write_text(
        "\n".join(
            [
                "LLM_BACKEND=local",
                "LOCAL_LLM_API_KEY=local-dev-key",
                "LOCAL_LLM_BASE_URL=http://127.0.0.1:2222/v1",
                "LOCAL_LLM_MODEL=Qwen/Qwen3.5-4B",
                "LLM_TEMPERATURE=0.35",
                "LLM_TOOL_TEMPERATURE=0.05",
                "LLM_CONTEXT_COMPRESS_TEMPERATURE=0.01",
            ]
        ),
        encoding="utf-8",
    )

    for key in (
        "LLM_BACKEND",
        "LOCAL_LLM_API_KEY",
        "LOCAL_LLM_BASE_URL",
        "LOCAL_LLM_MODEL",
        "LLM_TEMPERATURE",
        "LLM_TOOL_TEMPERATURE",
        "LLM_CONTEXT_COMPRESS_TEMPERATURE",
    ):
        monkeypatch.delenv(key, raising=False)

    cfg = AgentConfig.load(project_root=tmp_path)

    assert cfg.llm_temperature == pytest.approx(0.35)
    assert cfg.llm_tool_temperature == pytest.approx(0.05)
    assert cfg.llm_context_compress_temperature == pytest.approx(0.01)


def test_context_builder_uses_configured_compress_temperature() -> None:
    """上下文压缩应透传独立的压缩温度，而不是复用普通生成温度。"""
    ContextBuilder = _load_context_builder_class()
    llm = _CaptureCompressLLM()
    builder = ContextBuilder(
        max_tokens=128,
        token_counter=lambda text: len(text),
        llm_client=llm,  # type: ignore[arg-type]
        compress_temperature=0.15,
    )

    compressed = builder.compress("[Context]\n需要压缩的证据")

    assert compressed == "压缩后上下文"
    assert llm.temperatures == [0.15]


def test_llm_client_separates_text_and_tool_temperatures(monkeypatch) -> None:
    """统一 LLM 客户端应区分普通文本生成温度与工具调用温度。"""
    recorded_calls: list[dict] = []

    class _FakeCompletions:
        def create(self, **kwargs):
            recorded_calls.append(kwargs)
            if kwargs.get("tools"):
                message = types.SimpleNamespace(
                    tool_calls=[
                        types.SimpleNamespace(
                            function=types.SimpleNamespace(name="route", arguments='{"kind":"tool"}')
                        )
                    ],
                    content=None,
                )
            else:
                message = types.SimpleNamespace(content="普通回答")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    class _FakeOpenAI:
        def __init__(self, **_kwargs) -> None:
            self.chat = types.SimpleNamespace(completions=_FakeCompletions())

    openai_module = types.ModuleType("openai")
    openai_module.OpenAI = _FakeOpenAI
    langsmith_module = types.ModuleType("langsmith")
    wrappers_module = types.ModuleType("langsmith.wrappers")
    wrappers_module.wrap_openai = lambda client: client

    monkeypatch.setitem(sys.modules, "openai", openai_module)
    monkeypatch.setitem(sys.modules, "langsmith", langsmith_module)
    monkeypatch.setitem(sys.modules, "langsmith.wrappers", wrappers_module)

    client = LLMClient(
        api_key="local-dev-key",
        base_url="http://127.0.0.1:2222/v1",
        model="Qwen/Qwen3.5-4B",
        default_temperature=0.3,
        tool_temperature=0.0,
    )

    text = client.chat([LLMMessage(role="user", content="你好")])
    name, payload = client.tool_call(
        [LLMMessage(role="user", content="请选择工具")],
        tools=[{"type": "function", "function": {"name": "route", "parameters": {"type": "object"}}}],
    )

    assert text == "普通回答"
    assert name == "route"
    assert payload == {"kind": "tool"}
    assert recorded_calls[0]["temperature"] == pytest.approx(0.3)
    assert recorded_calls[1]["temperature"] == pytest.approx(0.0)
