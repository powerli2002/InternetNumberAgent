#!/usr/bin/env bash
set -euo pipefail

# 多卡 QLoRA 启动脚本。
# 默认使用 2 张卡；如需更多卡，可改 CUDA_VISIBLE_DEVICES 与 --nproc_per_node。

CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-1,2}"
NPROC_PER_NODE="${NPROC_PER_NODE:-2}"
MODEL_PATH="${MODEL_PATH:-Qwen/Qwen3.5-4B}"
DATASET_PATH="${DATASET_PATH:-TrainModel/VisCode-200K/VisCode-200K-uuid.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-TrainModel/VisCoder/train/output/qwen35_lora_multigpu}"
RUN_NAME="${RUN_NAME:-qwen35-viscode-lora}"
WANDB_PROJECT="${WANDB_PROJECT:-fusionprocessing-qwen35-lora}"
WANDB_ENTITY="${WANDB_ENTITY:-}"
TORCHRUN_BIN="${TORCHRUN_BIN:-TrainModel/VisCoder/.venv-lora-uv/bin/torchrun}"

export CUDA_VISIBLE_DEVICES

"${TORCHRUN_BIN}" \
  --nproc_per_node="${NPROC_PER_NODE}" \
  TrainModel/VisCoder/train/qwen35_lora_sft.py \
  --model_name_or_path "${MODEL_PATH}" \
  --dataset_path "${DATASET_PATH}" \
  --output_dir "${OUTPUT_DIR}" \
  --max_seq_len 1024 \
  --per_device_train_batch_size 1 \
  --gradient_accumulation_steps 8 \
  --num_train_epochs 1 \
  --learning_rate 2e-4 \
  --logging_steps 10 \
  --save_steps 500 \
  --run_name "${RUN_NAME}" \
  --wandb_project "${WANDB_PROJECT}" \
  --wandb_entity "${WANDB_ENTITY}"
