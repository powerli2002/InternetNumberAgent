#!/usr/bin/env bash
set -euo pipefail

# 一键框架：
# 1. 选择最新 LoRA checkpoint；
# 2. 合并为完整模型；
# 3. 为 AWQ 量化准备固定目录与环境变量；
# 4. 调用外部量化命令导出 AWQ 模型。
#
# 说明：当前仓库默认使用 llmcompressor 执行真正的 4bit AWQ 导出；
# 若需替换为自定义实现，仍可通过 AWQ_EXPORT_CMD 覆盖默认命令。

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VISCODER_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd -- "${VISCODER_ROOT}/../.." && pwd)"
TRAIN_ROOT="${VISCODER_ROOT}/train/output/qwen35_lora_run"
LORA_PYTHON="${VISCODER_ROOT}/.venv-lora-uv/bin/python"
MERGE_SCRIPT="${SCRIPT_DIR}/merge_qwen35_lora.py"
EXPORT_AWQ_SCRIPT="${SCRIPT_DIR}/export_awq.py"

BASE_MODEL="${BASE_MODEL:-Qwen/Qwen3.5-4B}"
AWQ_OUTPUT_NAME="${AWQ_OUTPUT_NAME:-merged_model_awq}"
AWQ_BACKEND="${AWQ_BACKEND:-llmcompressor}"
AWQ_W_BIT="${AWQ_W_BIT:-4}"
AWQ_GROUP_SIZE="${AWQ_GROUP_SIZE:-128}"
AWQ_ZERO_POINT="${AWQ_ZERO_POINT:-1}"
AWQ_VERSION="${AWQ_VERSION:-gemm}"
AWQ_CALIB_DATA="${AWQ_CALIB_DATA:-ultrachat-200k}"
AWQ_CALIB_SIZE="${AWQ_CALIB_SIZE:-128}"
AWQ_CALIB_SPLIT="${AWQ_CALIB_SPLIT:-train}"
TRUST_REMOTE_CODE="${TRUST_REMOTE_CODE:-1}"

FORCE_MERGE=0
FORCE_AWQ=0
MERGE_ONLY=0
SELECTED_CKPT=""

usage() {
  cat <<'EOF'
用法：
  bash TrainModel/VisCoder/train/export_latest_checkpoint_awq.sh [--checkpoint DIR|NAME]
                                                      [--merge-only]
                                                      [--force-merge]
                                                      [--force-awq]

默认行为：
  1. 自动选择 train/output/qwen35_lora_run 下最新 checkpoint-*
  2. 复用或生成 merged_model_eval/
  3. 复用或生成 merged_model_awq/
  4. 默认调用 export_awq.py + llmcompressor 完成 AWQ 导出

关键环境变量：
  BASE_MODEL         基础模型，默认 Qwen/Qwen3.5-4B
  AWQ_OUTPUT_NAME    AWQ 输出目录名，默认 merged_model_awq
  AWQ_BACKEND        默认 llmcompressor，仅用于记录导出后端标签
  AWQ_EXPORT_CMD     可选覆盖默认量化命令；留空时自动调用 export_awq.py

量化命令可读取的环境变量：
  AWQ_MODEL_DIR      merge 后完整模型目录
  AWQ_OUTPUT_DIR     AWQ 输出目录
  AWQ_BASE_MODEL     基础模型名或本地路径
  AWQ_W_BIT          默认 4
  AWQ_GROUP_SIZE     默认 128
  AWQ_ZERO_POINT     默认 1
  AWQ_VERSION        默认 gemm
  AWQ_CALIB_DATA     默认 ultrachat-200k
  AWQ_CALIB_SIZE     默认 128
  AWQ_CALIB_SPLIT    默认 train

示例：
  bash TrainModel/VisCoder/train/export_latest_checkpoint_awq.sh

  AWQ_EXPORT_CMD='python tools/export_awq.py --model "$AWQ_MODEL_DIR" --output "$AWQ_OUTPUT_DIR"' \
    bash TrainModel/VisCoder/train/export_latest_checkpoint_awq.sh

  bash TrainModel/VisCoder/train/export_latest_checkpoint_awq.sh --checkpoint checkpoint-21400 --merge-only
EOF
}

resolve_hf_local_snapshot() {
  local repo_id="$1"
  local cache_root="${HF_HOME:-/root/.cache/huggingface}"
  local hub_root="${HUGGINGFACE_HUB_CACHE:-${cache_root}/hub}"
  local repo_dir_name="models--${repo_id//\//--}"
  local repo_dir="${hub_root}/${repo_dir_name}"
  local snapshot_dir

  if [[ ! -d "${repo_dir}/snapshots" ]]; then
    return 1
  fi

  snapshot_dir="$(ls -dt "${repo_dir}"/snapshots/* 2>/dev/null | head -n 1 || true)"
  if [[ -z "${snapshot_dir}" || ! -d "${snapshot_dir}" ]]; then
    return 1
  fi

  printf '%s\n' "${snapshot_dir}"
}

write_export_plan() {
  local plan_path="$1"
  mkdir -p "$(dirname -- "${plan_path}")"
  PLAN_PATH="${plan_path}" \
  CKPT_PATH="${LATEST_CKPT}" \
  MERGED_PATH="${MERGED_DIR}" \
  OUTPUT_PATH="${AWQ_OUTPUT_DIR}" \
  BASE_MODEL_VALUE="${BASE_MODEL}" \
  BACKEND_VALUE="${AWQ_BACKEND}" \
  W_BIT_VALUE="${AWQ_W_BIT}" \
  GROUP_SIZE_VALUE="${AWQ_GROUP_SIZE}" \
  ZERO_POINT_VALUE="${AWQ_ZERO_POINT}" \
  VERSION_VALUE="${AWQ_VERSION}" \
  CALIB_DATA_VALUE="${AWQ_CALIB_DATA}" \
  CALIB_SIZE_VALUE="${AWQ_CALIB_SIZE}" \
  CALIB_SPLIT_VALUE="${AWQ_CALIB_SPLIT}" \
  EXPORT_CMD_VALUE="${AWQ_EXPORT_CMD:-}" \
  "${LORA_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

plan = {
    "checkpoint_dir": os.environ["CKPT_PATH"],
    "merged_model_dir": os.environ["MERGED_PATH"],
    "awq_output_dir": os.environ["OUTPUT_PATH"],
    "base_model": os.environ["BASE_MODEL_VALUE"],
    "backend": os.environ["BACKEND_VALUE"],
    "w_bit": int(os.environ["W_BIT_VALUE"]),
    "group_size": int(os.environ["GROUP_SIZE_VALUE"]),
    "zero_point": os.environ["ZERO_POINT_VALUE"] == "1",
    "version": os.environ["VERSION_VALUE"],
    "calib_data": os.environ["CALIB_DATA_VALUE"],
    "calib_size": int(os.environ["CALIB_SIZE_VALUE"]),
    "calib_split": os.environ["CALIB_SPLIT_VALUE"],
    "export_command": os.environ["EXPORT_CMD_VALUE"],
}
Path(os.environ["PLAN_PATH"]).write_text(
    json.dumps(plan, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
PY
}

require_awq_export_cmd() {
  if [[ -n "${AWQ_EXPORT_CMD:-}" ]]; then
    return
  fi
  AWQ_EXPORT_CMD="\"${LORA_PYTHON}\" \"${EXPORT_AWQ_SCRIPT}\" --model \"\${AWQ_MODEL_DIR}\" --output \"\${AWQ_OUTPUT_DIR}\" --w-bit \"\${AWQ_W_BIT}\" --group-size \"\${AWQ_GROUP_SIZE}\" --version \"\${AWQ_VERSION}\" --calib-data \"\${AWQ_CALIB_DATA}\" --calib-split \"\${AWQ_CALIB_SPLIT}\" --calib-samples \"\${AWQ_CALIB_SIZE}\""
  if [[ "${AWQ_ZERO_POINT}" == "1" ]]; then
    AWQ_EXPORT_CMD+=" --zero-point"
  else
    AWQ_EXPORT_CMD+=" --no-zero-point"
  fi
  if [[ "${TRUST_REMOTE_CODE}" == "1" ]]; then
    AWQ_EXPORT_CMD+=" --trust-remote-code"
  else
    AWQ_EXPORT_CMD+=" --no-trust-remote-code"
  fi
}

run_awq_export() {
  require_awq_export_cmd

  export AWQ_MODEL_DIR="${MERGED_DIR}"
  export AWQ_OUTPUT_DIR="${AWQ_OUTPUT_DIR}"
  export AWQ_BASE_MODEL="${BASE_MODEL}"
  export AWQ_W_BIT="${AWQ_W_BIT}"
  export AWQ_GROUP_SIZE="${AWQ_GROUP_SIZE}"
  export AWQ_ZERO_POINT="${AWQ_ZERO_POINT}"
  export AWQ_VERSION="${AWQ_VERSION}"
  export AWQ_CALIB_DATA="${AWQ_CALIB_DATA}"
  export AWQ_CALIB_SIZE="${AWQ_CALIB_SIZE}"
  export AWQ_CALIB_SPLIT="${AWQ_CALIB_SPLIT}"
  export AWQ_BACKEND="${AWQ_BACKEND}"
  export AWQ_TRUST_REMOTE_CODE="${TRUST_REMOTE_CODE}"

  echo "[info] AWQ backend: ${AWQ_BACKEND}"
  echo "[info] AWQ output dir: ${AWQ_OUTPUT_DIR}"
  echo "[info] AWQ export command: ${AWQ_EXPORT_CMD}"
  bash -lc "${AWQ_EXPORT_CMD}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --checkpoint)
      SELECTED_CKPT="${2:-}"
      shift 2
      ;;
    --merge-only)
      MERGE_ONLY=1
      shift
      ;;
    --force-merge)
      FORCE_MERGE=1
      shift
      ;;
    --force-awq)
      FORCE_AWQ=1
      shift
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

if [[ "${BASE_MODEL}" == "Qwen/Qwen3.5-4B" ]]; then
  LOCAL_BASE_MODEL="$(resolve_hf_local_snapshot "${BASE_MODEL}" || true)"
  if [[ -n "${LOCAL_BASE_MODEL}" ]]; then
    BASE_MODEL="${LOCAL_BASE_MODEL}"
    echo "[info] use cached base model: ${BASE_MODEL}"
  fi
fi

if [[ -n "${SELECTED_CKPT}" ]]; then
  if [[ -d "${SELECTED_CKPT}" ]]; then
    LATEST_CKPT="$(realpath "${SELECTED_CKPT}")"
  else
    LATEST_CKPT="${TRAIN_ROOT}/${SELECTED_CKPT}"
  fi
else
  LATEST_CKPT="$(ls -dt "${TRAIN_ROOT}"/checkpoint-* 2>/dev/null | head -n 1 || true)"
fi

if [[ -z "${LATEST_CKPT}" || ! -d "${LATEST_CKPT}" ]]; then
  echo "未找到 checkpoint 目录：${SELECTED_CKPT:-${TRAIN_ROOT}/checkpoint-*}" >&2
  exit 1
fi

CKPT_NAME="$(basename "${LATEST_CKPT}")"
MERGED_DIR="${LATEST_CKPT}/merged_model_eval"
AWQ_OUTPUT_DIR="${LATEST_CKPT}/${AWQ_OUTPUT_NAME}"
EXPORT_PLAN_PATH="${LATEST_CKPT}/awq_export_plan.json"

echo "[info] latest checkpoint: ${LATEST_CKPT}"
echo "[info] merged model dir: ${MERGED_DIR}"
echo "[info] awq output dir: ${AWQ_OUTPUT_DIR}"

if [[ "${FORCE_MERGE}" == "1" || ! -f "${MERGED_DIR}/config.json" || ! -f "${MERGED_DIR}/merge_config.json" ]]; then
  "${LORA_PYTHON}" "${MERGE_SCRIPT}" \
    --adapter_dir "${LATEST_CKPT}" \
    --output_dir "${MERGED_DIR}" \
    --base_model_name_or_path "${BASE_MODEL}" \
    --torch_dtype float16
else
  echo "[info] reuse merged model: ${MERGED_DIR}"
fi

write_export_plan "${EXPORT_PLAN_PATH}"
echo "[info] export plan saved: ${EXPORT_PLAN_PATH}"

if [[ "${MERGE_ONLY}" == "1" ]]; then
  echo "[info] merge-only enabled, stop before AWQ export"
  exit 0
fi

if [[ "${FORCE_AWQ}" != "1" && -f "${AWQ_OUTPUT_DIR}/config.json" ]]; then
  echo "[info] reuse existing AWQ model: ${AWQ_OUTPUT_DIR}"
  exit 0
fi

mkdir -p "${AWQ_OUTPUT_DIR}"
run_awq_export

if [[ ! -f "${AWQ_OUTPUT_DIR}/config.json" ]]; then
  echo "AWQ 导出命令已执行，但未在 ${AWQ_OUTPUT_DIR} 发现 config.json，请检查量化脚本输出。" >&2
  exit 1
fi

echo "[done] AWQ export completed: ${AWQ_OUTPUT_DIR}"
