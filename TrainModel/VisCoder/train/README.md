# Training VisCoder

本目录现在同时提供两套训练路径：

1. 原始论文复现脚本：`ms-swift + 全参微调`
2. 新增工程化脚本：`PyTorch + Transformers + PEFT`，用于在当前机器上对 `Qwen/Qwen3.5-4B` 做 `LoRA/QLoRA` 微调

如果你的目标是在当前仓库环境中快速验证 `Qwen3.5 + LoRA`，优先使用下面新增的 PyTorch 脚本。

## 1. 数据准备

当前仓库已经放置数据文件：

```bash
TrainModel/VisCode-200K/VisCode-200K-uuid.jsonl
```

数据格式为标准聊天监督样本，每条记录包含 `messages` 字段，可直接套用 chat template 做 SFT。

## 2. PyTorch LoRA / QLoRA 训练

### 2.1 安装依赖

优先尝试安装到项目根目录 `.venv`：

```bash
.venv/bin/pip install -U peft bitsandbytes wandb
```

说明：

- 当前机器为 `RTX 2080 Ti 11GB`，推荐默认使用 `4bit QLoRA`
- 2080Ti 不适合 `bf16 + flash-attn` 这类依赖较强的全参路径
- 若关闭 4bit，`Qwen3.5-4B` 在 11GB 单卡上通常难以稳定训练
- 如果训练依赖和仓库现有依赖发生冲突，建议单独创建 `TrainModel/VisCoder/.venv-lora-uv` 作为训练环境

独立环境示例：

```bash
bash TrainModel/VisCoder/train/setup_uv_lora_env.sh
```

如果你想手动执行，最小依赖集合如下：

```bash
uv venv --python 3.10 TrainModel/VisCoder/.venv-lora-uv
uv pip install --python TrainModel/VisCoder/.venv-lora-uv/bin/python -U \
  pip setuptools wheel \
  "torch==2.10.0" \
  "transformers==5.5.0" \
  datasets accelerate peft bitsandbytes wandb
```

### 2.2 最小验证

先在空闲 GPU 上跑 1 个 optimizer step，验证脚本、数据、LoRA 注入和反向传播都能成功：

```bash
CUDA_VISIBLE_DEVICES=1 TrainModel/VisCoder/.venv-lora-uv/bin/python TrainModel/VisCoder/train/qwen35_lora_sft.py \
  --dataset_path TrainModel/VisCode-200K/VisCode-200K-uuid.jsonl \
  --output_dir TrainModel/VisCoder/train/output/qwen35_lora_smoke \
  --sample_size 8 \
  --max_seq_len 512 \
  --per_device_train_batch_size 1 \
  --gradient_accumulation_steps 1 \
  --max_steps 1 \
  --logging_steps 1 \
  --save_steps 1 \
  --run_name qwen35-lora-smoke \
  --wandb_project fusionprocessing-qwen35-lora
```

### 2.3 单卡推荐起配

下面这组参数更接近可持续训练配置，适合 `2080Ti 11GB`：

```bash
CUDA_VISIBLE_DEVICES=1 TrainModel/VisCoder/.venv-lora-uv/bin/python TrainModel/VisCoder/train/qwen35_lora_sft.py \
  --dataset_path TrainModel/VisCode-200K/VisCode-200K-uuid.jsonl \
  --output_dir TrainModel/VisCoder/train/output/qwen35_lora_full \
  --max_seq_len 1024 \
  --per_device_train_batch_size 1 \
  --gradient_accumulation_steps 8 \
  --num_train_epochs 1 \
  --learning_rate 2e-4 \
  --logging_steps 10 \
  --save_steps 500 \
  --run_name qwen35-viscode-lora-single \
  --wandb_project fusionprocessing-qwen35-lora
```

默认行为：

- 基础模型：`Qwen/Qwen3.5-4B`
- 量化方式：`4bit nf4 + fp16 compute`
- LoRA 模块：`q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj`
- 默认只对 `assistant` 回答部分计算 loss；若 tokenizer 不直接返回 mask，会按 chat template 渲染后的文本和 offset mapping 构造所有 assistant 轮次的监督区间
- 默认通过 `wandb` 记录训练过程；如需关闭，可传 `--report_to none`
- 训练结束后默认会把 LoRA adapter 合并为完整模型，并输出到 `merged_model/` 子目录；如只想保留 adapter，可传 `--no-export_merged_model`

### 2.4 多卡训练

脚本 `launch_qwen35_lora_torchrun.sh` 提供了一个可直接执行的多卡入口，默认使用 2 张卡：

```bash
CUDA_VISIBLE_DEVICES=1,2 \
NPROC_PER_NODE=2 \
TORCHRUN_BIN=TrainModel/VisCoder/.venv-lora-uv/bin/torchrun \
RUN_NAME=qwen35-viscode-lora-2gpu \
WANDB_PROJECT=fusionprocessing-qwen35-lora \
bash TrainModel/VisCoder/train/launch_qwen35_lora_torchrun.sh
```

如果要用 3 张或 4 张卡，只需要同步修改 `CUDA_VISIBLE_DEVICES` 与 `NPROC_PER_NODE`。

### 2.5 资源估算

脚本 `estimate_qwen35_lora_resources.py` 会采样数据集、套用目标 tokenizer，并估算 token 长度、总 token 数和训练步数：

```bash
TrainModel/VisCoder/.venv-lora-uv/bin/python TrainModel/VisCoder/train/estimate_qwen35_lora_resources.py \
  --dataset_path TrainModel/VisCode-200K/VisCode-200K-uuid.jsonl \
  --max_seq_len 1024 \
  --per_device_train_batch_size 1 \
  --gradient_accumulation_steps 8 \
  --num_train_epochs 1
```

如果你已经测得单个 optimizer step 的耗时，例如 `36` 秒，可以把它带进去估算总时间：

```bash
TrainModel/VisCoder/.venv-lora-uv/bin/python TrainModel/VisCoder/train/estimate_qwen35_lora_resources.py \
  --dataset_path TrainModel/VisCode-200K/VisCode-200K-uuid.jsonl \
  --max_seq_len 1024 \
  --per_device_train_batch_size 1 \
  --gradient_accumulation_steps 8 \
  --num_train_epochs 1 \
  --observed_step_seconds 36
```

### 2.6 WandB 说明

推荐直接通过代码参数显式登录，而不是依赖环境变量：

```bash
TrainModel/VisCoder/.venv-lora-uv/bin/python TrainModel/VisCoder/train/qwen35_lora_sft.py \
  ... \
  --run_name qwen35-viscode-lora \
  --wandb_project fusionprocessing-qwen35-lora \
  --wandb_api_key YOUR_WANDB_API_KEY \
  --wandb_expected_email 845160705@qq.com
```

说明：

- `--wandb_api_key`：显式指定登录凭据
- `--wandb_expected_email`：脚本启动时会校验当前登录邮箱；若不是指定邮箱会直接报错
- `--wandb_entity`：可选，用于上传到指定团队

### 2.7 极简启动命令（常用参数已内置默认值）

脚本已固定常用默认参数（模型、数据路径、输出目录、LoRA 配置、QLoRA、WandB 项目和期望邮箱）。
因此常规启动只需要提供必要参数：

```bash
CUDA_VISIBLE_DEVICES=1 TrainModel/VisCoder/.venv-lora-uv/bin/python \
  TrainModel/VisCoder/train/qwen35_lora_sft.py \
  --sample_size 100 \
  --run_name qwen35-lora-100 \
  --wandb_api_key YOUR_WANDB_API_KEY
```

断点续训（其余参数继续使用默认值）：

```bash
LATEST_CKPT=$(ls -dt TrainModel/VisCoder/train/output/qwen35_lora_run/checkpoint-* | head -n 1)
CUDA_VISIBLE_DEVICES=1 TrainModel/VisCoder/.venv-lora-uv/bin/python \
  TrainModel/VisCoder/train/qwen35_lora_sft.py \
  --resume_from_checkpoint "$LATEST_CKPT" \
  --run_name qwen35-lora-resume \
  --wandb_api_key YOUR_WANDB_API_KEY
```

### 2.8 合并已有 LoRA adapter 为可直接推理的完整模型

如果你已经有历史训练产物，或者想单独把某个 adapter 导出成完整模型，可以直接运行合并脚本：

```bash
TrainModel/VisCoder/.venv-lora-uv/bin/python \
  TrainModel/VisCoder/train/merge_qwen35_lora.py \
  --adapter_dir TrainModel/VisCoder/train/output/qwen35_lora_run \
  --output_dir TrainModel/VisCoder/train/output/qwen35_lora_run/merged_model
```

如果需要显式指定基础模型，也可以加上：

```bash
TrainModel/VisCoder/.venv-lora-uv/bin/python \
  TrainModel/VisCoder/train/merge_qwen35_lora.py \
  --base_model_name_or_path Qwen/Qwen3.5-4B \
  --adapter_dir TrainModel/VisCoder/train/output/qwen35_lora_run \
  --output_dir TrainModel/VisCoder/train/output/qwen35_lora_run/merged_model
```

合并后的目录可直接用于推理加载：

```python
from transformers import AutoModelForCausalLM, AutoTokenizer

model_dir = "TrainModel/VisCoder/train/output/qwen35_lora_run/merged_model"
tokenizer = AutoTokenizer.from_pretrained(model_dir, use_fast=True)
model = AutoModelForCausalLM.from_pretrained(model_dir, trust_remote_code=True)
```

## 3. 原始 ms-swift 复现路径

如果你仍然想按论文原始方式复现 `VisCoder-3B / 7B` 的全参训练，可继续使用原始脚本。

### 3.1 Setup ms-swift

```bash
conda create -n swift python=3.10 -y
conda activate swift

git clone https://github.com/modelscope/ms-swift.git
cd ms-swift

pip install -e .
sh requirements/install_all.sh
pip install flash-attn -U --no-build-isolation

# 可选：日志上报
pip install wandb
```

### 3.2 Run Training Scripts

```bash
bash train_viscoder_3b.sh
bash train_viscoder_7b.sh
```

这两份脚本仍然是 `Qwen2.5-Coder` 的全参微调入口，不是本次新增的 `Qwen3.5 LoRA` 路径。

## 4. Notes

若使用 `ms-swift` 且启动很慢，可按原项目建议移除默认数据集配置：

```bash
rm ms-swift/swift/llm/dataset/data/dataset_info.json
echo "[]" > ms-swift/swift/llm/dataset/data/dataset_info.json
```

更多参数说明可参考 [ms-swift CLI documentation](https://swift.readthedocs.io/en/latest/Instruction/Command-line-parameters.html)。
