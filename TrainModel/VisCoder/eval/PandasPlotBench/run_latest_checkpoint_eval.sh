#!/usr/bin/env bash
set -euo pipefail

# 一键完成以下流程：
# 1. 选取最新 LoRA checkpoint；
# 2. 合并为可部署的完整模型；
# 3. 在指定 GPU 上启动独立 vLLM 服务；
# 4. 调用 PandasPlotBench 评测并上传 LangSmith。

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VISCODER_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
REPO_ROOT="$(cd -- "${VISCODER_ROOT}/../.." && pwd)"
TRAIN_ROOT="${VISCODER_ROOT}/train/output/qwen35_lora_run"
LORA_PYTHON="${VISCODER_ROOT}/.venv-lora-uv/bin/python"
PROJECT_PYTHON="${REPO_ROOT}/.venv/bin/python"
MERGE_SCRIPT="${VISCODER_ROOT}/train/merge_qwen35_lora.py"
VLLM_SCRIPT="${REPO_ROOT}/agent/model/start_vllm.py"
EVAL_ROOT="${SCRIPT_DIR}"
EVAL_SCRIPT="${EVAL_ROOT}/run_eval_and_upload_langsmith.py"

SERVE_CUDA="${SERVE_CUDA:-2}"
EVAL_CUDA="${EVAL_CUDA:-3}"
VLLM_PORT="${VLLM_PORT:-3333}"
OPENAI_KEY="${OPENAI_KEY_OVERRIDE:-local-dev-key}"
BASE_MODEL="${BASE_MODEL:-Qwen/Qwen3.5-4B}"
DATASET_NAME="${DATASET_NAME:-qwen3.5-plot-baseline}"
CONFIG_PATH="${CONFIG_PATH:-configs/config_normal_baseline.yaml}"
RUN_MODE="${RUN_MODE:-generate}"
# 11GB 单卡上优先给首个推理请求留运行态显存，避免 Qwen3.5 Triton autotune 在首轮 OOM。
# 如确实需要更长上下文，可由外部环境变量显式覆盖。
MAX_MODEL_LEN="${MAX_MODEL_LEN:-2048}"
# max_model_len 降低后，把 cache 预留比例回落到 0.85，给首个请求和 Triton kernel workspace 留余量。
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.85}"
MAX_NUM_BATCHED_TOKENS="${MAX_NUM_BATCHED_TOKENS:-256}"
# 评测请求侧默认输出上限；在 2048 context 下避免固定 3000 token 被 vLLM 直接拒绝。
PLOT_BENCH_MAX_TOKENS="${PLOT_BENCH_MAX_TOKENS:-1024}"
KEEP_VLLM="${KEEP_VLLM:-0}"
LIMIT=""
FULL_MODE=1
SKIP_EVAL=0
EXPERIMENT_NAME=""
CODEBERT_DEVICE="${PLOT_BENCH_CODEBERT_DEVICE:-}"
EVAL_PID=""
VLLM_PID=""

usage() {
  cat <<'EOF'
用法：
  bash run_latest_checkpoint_eval.sh [--full] [--limit N] [--skip-eval]
                                      [--serve-cuda N] [--eval-cuda N]
                                      [--port PORT] [--experiment-name NAME]

说明：
  --full                全量评测（默认）
  --limit N             只评测前 N 条，用于烟测
  --skip-eval           跳过生成，只上传最新结果文件
  --serve-cuda N        vLLM 部署 GPU，默认 2
  --eval-cuda N         评测与 CodeBERT 使用 GPU，默认 3
  --port PORT           vLLM 端口，默认 3333
  --experiment-name     LangSmith Experiment 名称；默认自动使用 checkpoint 名

常用环境变量：
  PLOT_BENCH_CODEBERT_DEVICE  CodeBERT 设备，默认跟随 --eval-cuda
  DATASET_NAME                LangSmith Dataset 名称
  KEEP_VLLM=1                 评测结束后保留 vLLM 进程
EOF
}

resolve_hf_local_snapshot() {
  local repo_id="$1"
  local cache_root="${HF_HOME:-/root/.cache/huggingface}"
  local hub_root="${HUGGINGFACE_HUB_CACHE:-${cache_root}/hub}"
  local repo_dir_name
  local repo_dir
  local snapshot_dir

  repo_dir_name="models--${repo_id//\//--}"
  repo_dir="${hub_root}/${repo_dir_name}"
  if [[ ! -d "${repo_dir}/snapshots" ]]; then
    return 1
  fi

  snapshot_dir="$(ls -dt "${repo_dir}"/snapshots/* 2>/dev/null | head -n 1 || true)"
  if [[ -z "${snapshot_dir}" || ! -d "${snapshot_dir}" ]]; then
    return 1
  fi

  printf '%s\n' "${snapshot_dir}"
}

normalize_qwen35_merged_model() {
  local model_dir="$1"
  local base_model_dir="$2"

  "${PROJECT_PYTHON}" - <<'PY' "${model_dir}" "${base_model_dir}"
import json
import shutil
import sys
from pathlib import Path

model_dir = Path(sys.argv[1]).resolve()
base_model_dir = Path(sys.argv[2]).resolve()
config_path = model_dir / "config.json"
backup_path = model_dir / "config.text_only.backup.json"

if not config_path.exists():
    raise FileNotFoundError(f"未找到 merged config: {config_path}")

current_cfg = json.loads(config_path.read_text(encoding="utf-8"))
if str(current_cfg.get("model_type", "")).strip() == "qwen3_5":
    print(f"[info] merged config already normalized: {config_path}")
else:
    if not backup_path.exists():
        backup_path.write_text(
            json.dumps(current_cfg, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    text_cfg = json.loads(backup_path.read_text(encoding="utf-8"))
    base_cfg = json.loads((base_model_dir / "config.json").read_text(encoding="utf-8"))
    patched = dict(base_cfg)
    patched["architectures"] = ["Qwen3_5ForCausalLM"]
    patched["text_config"] = text_cfg
    patched["tie_word_embeddings"] = text_cfg.get("tie_word_embeddings", True)
    patched["transformers_version"] = text_cfg.get(
        "transformers_version", base_cfg.get("transformers_version")
    )
    config_path.write_text(json.dumps(patched, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] normalized merged config: {config_path}")

for name in ("preprocessor_config.json", "video_preprocessor_config.json"):
    src = base_model_dir / name
    dst = model_dir / name
    if src.exists() and not dst.exists():
        shutil.copy2(src, dst)
        print(f"[info] copied {name} -> {dst}")
PY
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --full)
      FULL_MODE=1
      LIMIT=""
      shift
      ;;
    --limit)
      LIMIT="${2:-}"
      FULL_MODE=0
      shift 2
      ;;
    --skip-eval)
      SKIP_EVAL=1
      shift
      ;;
    --serve-cuda)
      SERVE_CUDA="${2:-}"
      shift 2
      ;;
    --eval-cuda)
      EVAL_CUDA="${2:-}"
      shift 2
      ;;
    --port)
      VLLM_PORT="${2:-}"
      shift 2
      ;;
    --experiment-name)
      EXPERIMENT_NAME="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数：$1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${CODEBERT_DEVICE}" ]]; then
  CODEBERT_DEVICE="cuda:${EVAL_CUDA}"
fi

if [[ "${BASE_MODEL}" == "Qwen/Qwen3.5-4B" ]]; then
  LOCAL_BASE_MODEL="$(resolve_hf_local_snapshot "${BASE_MODEL}" || true)"
  if [[ -n "${LOCAL_BASE_MODEL}" ]]; then
    BASE_MODEL="${LOCAL_BASE_MODEL}"
    echo "[info] use cached base model: ${BASE_MODEL}"
  fi
fi

LATEST_CKPT="$(ls -dt "${TRAIN_ROOT}"/checkpoint-* 2>/dev/null | head -n 1 || true)"
if [[ -z "${LATEST_CKPT}" ]]; then
  echo "未找到 checkpoint：${TRAIN_ROOT}/checkpoint-*" >&2
  exit 1
fi

CKPT_NAME="$(basename "${LATEST_CKPT}")"
if [[ -z "${EXPERIMENT_NAME}" ]]; then
  EXPERIMENT_NAME="qwen35-lora-${CKPT_NAME}"
fi

MERGED_DIR="${LATEST_CKPT}/merged_model_eval"
LOG_DIR="${EVAL_ROOT}/eval_results/latest_checkpoint_logs"
VLLM_LOG="${LOG_DIR}/${CKPT_NAME}.vllm.log"
mkdir -p "${LOG_DIR}"

if ss -tln "( sport = :${VLLM_PORT} )" | tail -n +2 | grep -q .; then
  echo "端口 ${VLLM_PORT} 已被占用，请更换 VLLM_PORT 或先释放端口。" >&2
  exit 1
fi

echo "[info] latest checkpoint: ${LATEST_CKPT}"
echo "[info] merged model dir: ${MERGED_DIR}"
echo "[info] serve cuda: ${SERVE_CUDA}"
echo "[info] eval cuda: ${EVAL_CUDA}"
echo "[info] codebert device: ${CODEBERT_DEVICE}"
echo "[info] plot bench max tokens: ${PLOT_BENCH_MAX_TOKENS}"
echo "[info] experiment name: ${EXPERIMENT_NAME}"

# 仅在合并产物缺失时重新合并，避免重复耗时。
if [[ ! -f "${MERGED_DIR}/config.json" || ! -f "${MERGED_DIR}/merge_config.json" ]]; then
  "${LORA_PYTHON}" "${MERGE_SCRIPT}" \
    --adapter_dir "${LATEST_CKPT}" \
    --output_dir "${MERGED_DIR}" \
    --base_model_name_or_path "${BASE_MODEL}" \
    --torch_dtype float16
else
  echo "[info] reuse merged model: ${MERGED_DIR}"
fi

normalize_qwen35_merged_model "${MERGED_DIR}" "${BASE_MODEL}"

kill_process_tree() {
  local pid="$1"
  local label="$2"
  if [[ -z "${pid}" ]] || ! kill -0 "${pid}" 2>/dev/null; then
    return
  fi

  echo "[cleanup] stopping ${label} pid=${pid}"
  # 先停止直接子进程，再停止父进程，避免 Python 包装器退出后遗留真正占 GPU 的子进程。
  pkill -TERM -P "${pid}" 2>/dev/null || true
  kill -TERM "${pid}" 2>/dev/null || true
  sleep 2

  pkill -KILL -P "${pid}" 2>/dev/null || true
  kill -KILL "${pid}" 2>/dev/null || true
  wait "${pid}" 2>/dev/null || true
}

cleanup() {
  local exit_code=$?

  # 评测失败或被中断时，优先回收 bench 相关进程，释放 cuda:3。
  if [[ -n "${EVAL_PID}" ]]; then
    kill_process_tree "${EVAL_PID}" "bench-eval"
  fi

  # 默认回收 vLLM，释放 cuda:2；仅在显式 KEEP_VLLM=1 时保留。
  if [[ "${KEEP_VLLM}" != "1" && -n "${VLLM_PID}" ]]; then
    kill_process_tree "${VLLM_PID}" "vllm"
  fi

  exit "${exit_code}"
}

trap cleanup EXIT

echo "[info] starting vLLM on cuda:${SERVE_CUDA}, log -> ${VLLM_LOG}"
CUDA_VISIBLE_DEVICES="${SERVE_CUDA}" \
  "${PROJECT_PYTHON}" "${VLLM_SCRIPT}" \
  --model "${MERGED_DIR}" \
  --port "${VLLM_PORT}" \
  --host 0.0.0.0 \
  --api-key "${OPENAI_KEY}" \
  --served-model-name "${CKPT_NAME}" \
  --cuda-visible-devices "${SERVE_CUDA}" \
  --max-model-len "${MAX_MODEL_LEN}" \
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
  --max-num-batched-tokens "${MAX_NUM_BATCHED_TOKENS}" \
  --quantization "" \
  --dtype half \
  --attention-backend TRITON_ATTN \
  --mm-encoder-attn-backend TRITON_ATTN \
  --language-model-only \
  --skip-mm-profiling \
  --default-chat-template-kwargs '{"enable_thinking": false}' \
  >"${VLLM_LOG}" 2>&1 &
VLLM_PID=$!

READY=0
for _ in $(seq 1 90); do
  if curl -fsS --max-time 3 -H "Authorization: Bearer ${OPENAI_KEY}" \
    "http://127.0.0.1:${VLLM_PORT}/v1/models" >/dev/null 2>&1; then
    READY=1
    break
  fi
  if ! kill -0 "${VLLM_PID}" 2>/dev/null; then
    echo "vLLM 启动失败，日志见：${VLLM_LOG}" >&2
    exit 1
  fi
  sleep 2
done

if [[ "${READY}" != "1" ]]; then
  echo "等待 vLLM 就绪超时，日志见：${VLLM_LOG}" >&2
  exit 1
fi

echo "[info] vLLM is ready: http://127.0.0.1:${VLLM_PORT}/v1/chat/completions"

cd "${EVAL_ROOT}"
CMD=(
  "${PROJECT_PYTHON}" "${EVAL_SCRIPT}"
  "--cuda=${EVAL_CUDA}"
  "--mode=${RUN_MODE}"
  "--openai-base-url=http://127.0.0.1:${VLLM_PORT}/v1/chat/completions"
  "--openai-key=${OPENAI_KEY}"
  "--dataset-name=${DATASET_NAME}"
  "--experiment-name=${EXPERIMENT_NAME}"
  "--config=${CONFIG_PATH}"
  "--model=openai/${CKPT_NAME}"
)

if [[ "${FULL_MODE}" == "1" ]]; then
  CMD+=("--full")
elif [[ -n "${LIMIT}" ]]; then
  CMD+=("--limit=${LIMIT}")
fi

if [[ "${SKIP_EVAL}" == "1" ]]; then
  CMD+=("--skip-eval")
fi

echo "[info] eval command: ${CMD[*]}"
PLOT_BENCH_CODEBERT_DEVICE="${CODEBERT_DEVICE}" \
PLOT_BENCH_MAX_TOKENS="${PLOT_BENCH_MAX_TOKENS}" "${CMD[@]}" &
EVAL_PID=$!
wait "${EVAL_PID}"
EVAL_PID=""
