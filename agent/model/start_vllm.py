"""
使用 Python 子进程启动 vLLM OpenAI 兼容服务。

默认参数已配置为可直接执行：
    nohup python start_vllm.py
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
from typing import List

# ps aux | grep start_vllm
# nohup python start_vllm.py
# curl http://127.0.0.1:2222/v1/models
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动本机 vLLM OpenAI 兼容服务")
    parser.add_argument("--model", default="Qwen/Qwen3-4B", help="vLLM 模型 ID")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=2222, help="监听端口，默认 2222")
    parser.add_argument("--api-key", default="local-dev-key", help="OpenAI 兼容接口 API Key")
    parser.add_argument("--max-model-len", type=int, default=4096, help="最大上下文长度（2080Ti 建议 2048）")
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
        default=True,
        help="允许加载模型仓库自定义代码（新架构模型常需开启）",
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
    if args.trust_remote_code:
        command.append("--trust-remote-code")
    else:
        command.append("--no-trust-remote-code")
    if args.enforce_eager:
        command.append("--enforce-eager")
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
