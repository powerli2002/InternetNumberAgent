"""
使用 Python 子进程启动 vLLM OpenAI 兼容服务。

默认参数已配置为可直接执行：
    nohup python start_vllm.py
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path
from typing import List
from urllib.parse import urlparse

from dotenv import load_dotenv

# ps aux | grep start_vllm
# nohup python start_vllm.py
# curl http://127.0.0.1:2222/v1/models
def _load_project_env() -> None:
    """启动脚本默认读取项目 conf/.env，保证命令行默认值与主项目配置保持一致。"""
    env_path = Path(__file__).resolve().parents[2] / "conf" / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


def _read_int_env(name: str, default: int, *, minimum: int | None = None) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"环境变量 {name} 必须是整数，当前值为：{raw_value}") from exc
    if minimum is not None and value < minimum:
        raise RuntimeError(f"环境变量 {name} 必须 >= {minimum}，当前值为：{value}")
    return value


def _read_default_host_port() -> tuple[str, int]:
    base_url = os.environ.get("LOCAL_LLM_BASE_URL", "").strip()
    if not base_url:
        return "127.0.0.1", 2222
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.hostname:
        raise RuntimeError(f"LOCAL_LLM_BASE_URL 格式非法，当前值为：{base_url}")
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return parsed.hostname, port


def _parse_args() -> argparse.Namespace:
    _load_project_env()
    default_host, default_port = _read_default_host_port()
    parser = argparse.ArgumentParser(description="启动本机 vLLM OpenAI 兼容服务")
    parser.add_argument("--model", default=os.environ.get("LOCAL_LLM_MODEL", "Qwen/Qwen3.5-4B"), help="vLLM 模型 ID")
    parser.add_argument("--host", default=default_host, help="监听地址，默认读取 LOCAL_LLM_BASE_URL")
    parser.add_argument("--port", type=int, default=default_port, help="监听端口，默认读取 LOCAL_LLM_BASE_URL")
    parser.add_argument("--api-key", default=os.environ.get("LOCAL_LLM_API_KEY", "local-dev-key"), help="OpenAI 兼容接口 API Key")
    parser.add_argument(
        "--max-model-len",
        type=int,
        default=_read_int_env("LOCAL_VLLM_MAX_MODEL_LEN", 4096, minimum=256),
        help="最大上下文长度，默认读取 conf/.env 中的 LOCAL_VLLM_MAX_MODEL_LEN",
    )
    parser.add_argument(
        "--gpu-memory-utilization",
        type=float,
        default=0.8,
        help="GPU 显存占用比例（0~1）",
    )
    parser.add_argument(
        "--max-num-batched-tokens",
        type=int,
        default=512,
        help="单批次最大 token 数（降低峰值显存）",
    )
    parser.add_argument(
        "--tensor-parallel-size",
        type=int,
        default=4,
        help="张量并行卡数（多卡推理常用参数）",
    )
    parser.add_argument(
        "--pipeline-parallel-size",
        type=int,
        default=1,
        help="流水线并行分段数（按需启用）",
    )
    parser.add_argument(
        "--trust-remote-code",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否显式透传 trust_remote_code；默认不透传，避免对已内置架构模型产生无效告警",
    )
    parser.add_argument(
        "--disable-custom-all-reduce",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否显式禁用 custom all-reduce；默认在 TP>2 时自动禁用，避免 PCIe 多卡环境反复告警",
    )
    parser.add_argument(
        "--attention-backend",
        default="",
        help="可选覆盖全局注意力后端，例如 TRITON_ATTN；留空则由 vLLM 自动选择",
    )
    parser.add_argument(
        "--mm-encoder-attn-backend",
        default="",
        help="可选覆盖多模态编码器注意力后端，例如 TRITON_ATTN；留空则由 vLLM 自动选择",
    )
    parser.add_argument(
        "--language-model-only",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否只保留语言模型路径；默认对 Qwen3.5 自动开启，绕过当前项目不需要的多模态初始化",
    )
    parser.add_argument(
        "--skip-mm-profiling",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否跳过多模态内存 profiling；默认对 Qwen3.5 自动开启，缩短纯文本场景冷启动",
    )
    parser.add_argument(
        "--use-modelscope",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="是否启用 ModelScope 下载（默认关闭，避免 qwen3.5 在 ModelScope 404）",
    )
    parser.add_argument(
        "--enforce-eager",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否强制 eager 执行（关闭 CUDA Graph 以降低显存峰值）",
    )
    parser.add_argument(
        "--tool-call-parser",
        default="hermes",
        help="工具调用解析器，指定模型的 function calling 格式（如 hermes、mistral、llama3_json、pythonic 等）",
    )
    parser.add_argument(
        "--default-chat-template-kwargs",
        default=os.environ.get("LOCAL_VLLM_DEFAULT_CHAT_TEMPLATE_KWARGS", ""),
        help="默认透传给 chat template 的 JSON 参数；留空时对 Qwen3.5 自动关闭 thinking",
    )
    return parser.parse_args()


def _build_command(args: argparse.Namespace) -> List[str]:
    # 使用当前 Python 解释器调用 vLLM CLI，避免 PATH 中找不到 vllm 可执行文件。
    command = [
        sys.executable,
        "-m",
        "vllm.entrypoints.cli.main",
        "serve",
        args.model,
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--api-key",
        args.api_key,
        "--max-model-len",
        str(args.max_model_len),
        "--gpu-memory-utilization",
        str(args.gpu_memory_utilization),
        "--max-num-batched-tokens",
        str(args.max_num_batched_tokens),
        "--tensor-parallel-size",
        str(args.tensor_parallel_size),
    ]
    if args.pipeline_parallel_size > 1:
        command.extend(["--pipeline-parallel-size", str(args.pipeline_parallel_size)])

    # 默认不显式透传 trust_remote_code，避免对 Qwen3/Qwen3.5 这类已内置架构模型打印“无效参数”告警。
    if args.trust_remote_code is True:
        command.append("--trust-remote-code")
    elif args.trust_remote_code is False:
        command.append("--no-trust-remote-code")

    # 4 张 2080Ti 这类 PCIe-only 多卡环境会自动禁用 custom all-reduce；
    # 这里直接显式关闭，减少启动期重复告警。
    disable_custom_all_reduce = args.disable_custom_all_reduce
    if disable_custom_all_reduce is None:
        disable_custom_all_reduce = args.tensor_parallel_size > 2
    if disable_custom_all_reduce:
        command.append("--disable-custom-all-reduce")
    elif args.disable_custom_all_reduce is False:
        command.append("--no-disable-custom-all-reduce")

    if args.enforce_eager:
        command.append("--enforce-eager")
    # Qwen3.5 在当前 2080Ti + vLLM 组合上默认会把 decoder 注意力后端选成 FLASHINFER。
    # 该组合已观测到生成阶段长时间无返回，因此这里对 Qwen3.5 显式固定为 TRITON_ATTN。
    attention_backend = (args.attention_backend or "").strip()
    if not attention_backend and "Qwen3.5" in args.model:
        attention_backend = "TRITON_ATTN"
    if attention_backend:
        command.extend(["--attention-backend", attention_backend])

    # Qwen3.5 在 2080Ti 这类 pre-Ampere 卡上会先探测 FA2 再回退到 TRITON_ATTN，
    # 显式固定后端可减少启动期的误导性 ERROR 日志。
    mm_encoder_attn_backend = (args.mm_encoder_attn_backend or "").strip()
    if not mm_encoder_attn_backend and "Qwen3.5" in args.model:
        mm_encoder_attn_backend = "TRITON_ATTN"
    if mm_encoder_attn_backend:
        command.extend(["--mm-encoder-attn-backend", mm_encoder_attn_backend])

    # 当前 agent 仅处理文本问答，不依赖图像/视频输入。
    # Qwen3.5 在 vLLM 中会走多模态 profiling 路径，2080Ti 场景下容易把启动时间放大。
    language_model_only = args.language_model_only
    if language_model_only is None:
        language_model_only = "Qwen3.5" in args.model
    if language_model_only:
        command.append("--language-model-only")
    elif args.language_model_only is False:
        command.append("--no-language-model-only")

    skip_mm_profiling = args.skip_mm_profiling
    if skip_mm_profiling is None:
        skip_mm_profiling = "Qwen3.5" in args.model
    if skip_mm_profiling:
        command.append("--skip-mm-profiling")
    elif args.skip_mm_profiling is False:
        command.append("--no-skip-mm-profiling")

    # Qwen3.5 的 chat template 默认会打开 <think> 推理块。
    # 当前项目本机部署主要承担 Agent 工具编排与问答，不需要服务端默认输出思维链，
    # 因此在 vLLM 启动阶段直接注入默认 chat_template_kwargs，避免每次请求单独透传。
    default_chat_template_kwargs = (args.default_chat_template_kwargs or "").strip()
    if not default_chat_template_kwargs and "Qwen3.5" in args.model:
        default_chat_template_kwargs = json.dumps({"enable_thinking": False}, ensure_ascii=False)
    if default_chat_template_kwargs:
        try:
            parsed_kwargs = json.loads(default_chat_template_kwargs)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "--default-chat-template-kwargs 必须是合法 JSON，例如 '{\"enable_thinking\": false}'。"
            ) from exc
        if not isinstance(parsed_kwargs, dict):
            raise RuntimeError("--default-chat-template-kwargs 必须是 JSON 对象。")
        command.extend(
            [
                "--default-chat-template-kwargs",
                json.dumps(parsed_kwargs, ensure_ascii=False),
            ]
        )

    if args.tool_call_parser:
        command.extend(["--enable-auto-tool-choice", "--tool-call-parser", args.tool_call_parser])
    return command



def _check_port_free(host: str, port: int) -> None:
    """检测端口是否已被占用，被占用说明旧进程仍在运行，需先手动终止。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        result = s.connect_ex((host, port))
    if result == 0:
        raise RuntimeError(
            f"端口 {host}:{port} 已被占用，旧 vLLM 进程可能仍在运行并占用 GPU 显存。\n"
            f"请先执行：kill $(lsof -ti tcp:{port})  或  pkill -f 'vllm.*serve'"
        )


def main() -> int:
    args = _parse_args()
    if args.tensor_parallel_size < 1:
        raise RuntimeError("--tensor-parallel-size 必须 >= 1。")
    if args.pipeline_parallel_size < 1:
        raise RuntimeError("--pipeline-parallel-size 必须 >= 1。")
    if args.max_num_batched_tokens < 1:
        raise RuntimeError("--max-num-batched-tokens 必须 >= 1。")
    if not (0.0 < args.gpu_memory_utilization <= 1.0):
        raise RuntimeError("--gpu-memory-utilization 必须在 (0, 1] 范围内。")

    _check_port_free(args.host, args.port)

    command = _build_command(args)
    child_env = os.environ.copy()
    child_env["VLLM_USE_MODELSCOPE"] = "True" if args.use_modelscope else "False"
    process = subprocess.Popen(command, env=child_env)

    def _shutdown(signum: int, _frame) -> None:
        if process.poll() is None:
            process.send_signal(signum)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        return process.wait()
    except KeyboardInterrupt:
        _shutdown(signal.SIGINT, None)
        return process.wait()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"[start_vllm] 启动失败: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
