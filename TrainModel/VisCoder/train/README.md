# VisCoder Training

本目录现在分成两类入口：

1. 当前主路径：`Qwen3.5-4B + LoRA/QLoRA`

如果你现在用的是 `Qwen3.5-4B`，只看下面这几份文件即可：

- `run_qwen35_lora.sh`：最简训练入口，推荐直接用它
- `qwen35_lora_sft.py`：实际训练脚本
- `launch_qwen35_lora_torchrun.sh`：多卡启动脚本
- `merge_qwen35_lora.py`：把 LoRA adapter 合并成完整模型
- `export_latest_checkpoint_awq.sh`：一键选择最新 checkpoint，完成 merge 并触发 AWQ 导出

## 当前主路径：Qwen3.5-4B LoRA

### 数据

默认数据集路径：

```bash
TrainModel/VisCode-200K/VisCode-200K-uuid.jsonl
```

数据格式要求每条样本包含 `messages` 字段。

### 最简启动

```bash
CUDA_VISIBLE_DEVICES=1 \
RUN_NAME=qwen35-lora-smoke \
bash TrainModel/VisCoder/train/run_qwen35_lora.sh \
  --sample_size 8 \
  --max_steps 1 \
  --max_seq_len 512 \
  --gradient_accumulation_steps 1 \
  --logging_steps 1 \
  --save_steps 1
```

### 单卡推荐配置

```bash
CUDA_VISIBLE_DEVICES=1 \
RUN_NAME=qwen35-viscode-lora-single \
OUTPUT_DIR=TrainModel/VisCoder/train/output/qwen35_lora_full \
bash TrainModel/VisCoder/train/run_qwen35_lora.sh \
  --max_seq_len 1024 \
  --gradient_accumulation_steps 8 \
  --num_train_epochs 1 \
  --learning_rate 2e-4 \
  --logging_steps 10 \
  --save_steps 500
```

### 多卡训练

```bash
CUDA_VISIBLE_DEVICES=1,2 \
NPROC_PER_NODE=2 \
TORCHRUN_BIN=TrainModel/VisCoder/.venv-lora-uv/bin/torchrun \
RUN_NAME=qwen35-viscode-lora-2gpu \
bash TrainModel/VisCoder/train/launch_qwen35_lora_torchrun.sh
```

### 合并 LoRA adapter

```bash
TrainModel/VisCoder/.venv-lora-uv/bin/python \
  TrainModel/VisCoder/train/merge_qwen35_lora.py \
  --adapter_dir TrainModel/VisCoder/train/output/qwen35_lora_run \
  --output_dir TrainModel/VisCoder/train/output/qwen35_lora_run/merged_model
```

### 导出最新 checkpoint 为 AWQ 模型

当前仓库现在内置了基于 `llmcompressor` 的导出脚本：

- `export_latest_checkpoint_awq.sh`：自动选择最新 checkpoint、完成 merge，并调用 `export_awq.py`
- `export_awq.py`：真正执行 `llmcompressor + AWQModifier` 量化导出

```bash
bash TrainModel/VisCoder/train/export_latest_checkpoint_awq.sh
```

如果后续需要替换为自定义量化命令，仍可通过 `AWQ_EXPORT_CMD` 覆盖默认行为。

脚本默认会：

- 自动选择 `TrainModel/VisCoder/train/output/qwen35_lora_run/checkpoint-*` 中最新目录
- 复用或生成 `merged_model_eval/`
- 把 AWQ 输出固定到 `checkpoint-*/merged_model_awq/`
- 额外写出 `checkpoint-*/awq_export_plan.json`，记录本次导出参数

量化命令可直接读取以下环境变量：

- `AWQ_MODEL_DIR`
- `AWQ_OUTPUT_DIR`
- `AWQ_BASE_MODEL`
- `AWQ_W_BIT`
- `AWQ_GROUP_SIZE`
- `AWQ_ZERO_POINT`
- `AWQ_VERSION`
- `AWQ_CALIB_DATA`
- `AWQ_CALIB_SIZE`
- `AWQ_CALIB_SPLIT`

当前默认量化参数：

- `AWQ_W_BIT=4`
- `AWQ_GROUP_SIZE=128`
- `AWQ_ZERO_POINT=1`
- `AWQ_VERSION=gemm`
- `AWQ_CALIB_DATA=ultrachat-200k`
- `AWQ_CALIB_SIZE=128`
- `AWQ_CALIB_SPLIT=train`

如果环境中尚未安装 `llmcompressor`，脚本会直接报错并提示安装命令：

```bash
TrainModel/VisCoder/.venv-lora-uv/bin/pip install llmcompressor
```

### 默认行为

- 基础模型：`Qwen/Qwen3.5-4B`
- 默认使用 `4bit QLoRA`
- 默认只对 `assistant` 回复计算 loss
- 默认 `wandb offline`，可通过 `wandb sync` 后续上传
- 训练完成后默认自动导出 `merged_model/`

如果要完全关闭 WandB，追加 `--report_to none`。
