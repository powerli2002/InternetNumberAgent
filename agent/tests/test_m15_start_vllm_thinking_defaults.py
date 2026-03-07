from __future__ import annotations

from argparse import Namespace

from agent.model.start_vllm import _build_command


def _make_args(model: str, default_chat_template_kwargs: str = "") -> Namespace:
    return Namespace(
        model=model,
        host="127.0.0.1",
        port=2222,
        api_key="local-dev-key",
        max_model_len=16384,
        gpu_memory_utilization=0.8,
        max_num_batched_tokens=512,
        tensor_parallel_size=4,
        pipeline_parallel_size=1,
        trust_remote_code=None,
        disable_custom_all_reduce=None,
        attention_backend="",
        mm_encoder_attn_backend="",
        language_model_only=None,
        skip_mm_profiling=None,
        use_modelscope=False,
        enforce_eager=True,
        tool_call_parser="hermes",
        default_chat_template_kwargs=default_chat_template_kwargs,
    )


def test_start_vllm_defaults_disable_thinking_for_qwen35() -> None:
    args = _make_args("Qwen/Qwen3.5-4B")

    command = _build_command(args)

    assert "--default-chat-template-kwargs" in command
    flag_index = command.index("--default-chat-template-kwargs")
    assert command[flag_index + 1] == '{"enable_thinking": false}'


def test_start_vllm_does_not_inject_thinking_flag_for_other_models() -> None:
    args = _make_args("Qwen/Qwen3-4B")

    command = _build_command(args)

    assert "--default-chat-template-kwargs" not in command
