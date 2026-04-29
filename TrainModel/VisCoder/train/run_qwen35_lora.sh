#!/usr/bin/env bash
set -euo pipefail

# Qwen3.5-4B LoRA/QLoRA 统一启动入口。
# 常用参数提供默认值，其余参数会原样透传给 Python 训练脚本。

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VISCODER_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd -- "${VISCODER_ROOT}/../.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-${VISCODER_ROOT}/.venv-lora-uv/bin/python}"
TRAIN_SCRIPT="${TRAIN_SCRIPT:-${SCRIPT_DIR}/qwen35_lora_sft.py}"
MODEL_PATH="${MODEL_PATH:-Qwen/Qwen3.5-4B}"
DATASET_PATH="${DATASET_PATH:-${REPO_ROOT}/TrainModel/VisCode-200K/VisCode-200K-uuid.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-${SCRIPT_DIR}/output/qwen35_lora_run}"
RUN_NAME="${RUN_NAME:-qwen35-lora}"
WANDB_PROJECT="${WANDB_PROJECT:-fusionprocessing-qwen35-lora}"
WANDB_MODE="${WANDB_MODE:-offline}"

exec "${PYTHON_BIN}" "${TRAIN_SCRIPT}" \
  --model_name_or_path "${MODEL_PATH}" \
  --dataset_path "${DATASET_PATH}" \
  --output_dir "${OUTPUT_DIR}" \
  --run_name "${RUN_NAME}" \
  --wandb_project "${WANDB_PROJECT}" \
  --wandb_mode "${WANDB_MODE}" \
  "$@"
