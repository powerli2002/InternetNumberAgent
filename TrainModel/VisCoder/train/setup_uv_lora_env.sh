#!/usr/bin/env bash
set -euo pipefail

# 使用 uv 创建独立 LoRA 训练环境，避免污染仓库根 .venv。

ENV_DIR="${ENV_DIR:-TrainModel/VisCoder/.venv-lora-uv}"
PYTHON_VERSION="${PYTHON_VERSION:-3.10}"

uv venv --python "${PYTHON_VERSION}" "${ENV_DIR}"

uv pip install --python "${ENV_DIR}/bin/python" -U \
  pip \
  setuptools \
  wheel \
  "torch==2.10.0" \
  "transformers==5.5.0" \
  datasets \
  accelerate \
  peft \
  bitsandbytes \
  wandb
