#!/usr/bin/env python3
"""使用 PyTorch + Transformers + PEFT 对 Qwen3.5 做 LoRA/QLoRA 监督微调。"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

import torch
from datasets import Dataset, load_dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    Trainer,
    TrainingArguments,
    set_seed,
)


DEFAULT_TARGET_MODULES = (
    "q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Qwen3.5 LoRA/QLoRA SFT 训练脚本")
    parser.add_argument(
        "--model_name_or_path",
        type=str,
        default="Qwen/Qwen3.5-4B",
        help="基础模型路径或 HuggingFace 模型名。",
    )
    parser.add_argument(
        "--dataset_path",
        type=str,
        default=str(Path(__file__).resolve().parents[1] / ".." / "VisCode-200K" / "VisCode-200K-uuid.jsonl"),
        help="VisCode-200K 数据集 jsonl 路径。",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default=str(Path(__file__).resolve().parent / "output" / "qwen35_viscode_lora"),
        help="LoRA 权重输出目录。",
    )
    parser.add_argument("--max_seq_len", type=int, default=1024, help="最大序列长度。")
    parser.add_argument(
        "--sample_size",
        type=int,
        default=0,
        help="仅取前 N 条样本做调试；0 表示使用全量数据。",
    )
    parser.add_argument("--num_train_epochs", type=float, default=1.0, help="训练 epoch 数。")
    parser.add_argument("--max_steps", type=int, default=-1, help="最大训练步数，-1 表示按 epoch 训练。")
    parser.add_argument("--per_device_train_batch_size", type=int, default=1, help="单卡 batch size。")
    parser.add_argument("--gradient_accumulation_steps", type=int, default=8, help="梯度累积步数。")
    parser.add_argument("--learning_rate", type=float, default=2e-4, help="学习率。")
    parser.add_argument("--weight_decay", type=float, default=0.01, help="权重衰减。")
    parser.add_argument("--warmup_ratio", type=float, default=0.03, help="warmup 比例。")
    parser.add_argument("--logging_steps", type=int, default=5, help="日志步数。")
    parser.add_argument("--save_steps", type=int, default=200, help="保存步数。")
    parser.add_argument("--save_total_limit", type=int, default=2, help="最多保留 checkpoint 数。")
    parser.add_argument("--seed", type=int, default=42, help="随机种子。")
    parser.add_argument("--lora_r", type=int, default=16, help="LoRA rank。")
    parser.add_argument("--lora_alpha", type=int, default=32, help="LoRA alpha。")
    parser.add_argument("--lora_dropout", type=float, default=0.05, help="LoRA dropout。")
    parser.add_argument(
        "--target_modules",
        type=str,
        default=DEFAULT_TARGET_MODULES,
        help="LoRA 作用模块，逗号分隔。",
    )
    parser.add_argument(
        "--preprocessing_num_workers",
        type=int,
        default=1,
        help="数据预处理并行度。默认 1 以保证兼容性。",
    )
    parser.add_argument(
        "--disable_4bit",
        action="store_true",
        help="关闭 4bit 量化，改为常规 LoRA。11GB 显存机器通常不建议关闭。",
    )
    parser.add_argument(
        "--train_on_prompt",
        action="store_true",
        help="若 tokenizer 不支持 assistant mask，则默认仅训练回答部分；显式开启后会连 prompt 一起训练。",
    )
    parser.add_argument(
        "--resume_from_checkpoint",
        type=str,
        default=None,
        help="断点继续训练的 checkpoint 路径。",
    )
    parser.add_argument(
        "--trust_remote_code",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="允许加载 Qwen3.5 的远程模型定义。",
    )
    parser.add_argument(
        "--report_to",
        type=str,
        default="wandb",
        help="训练日志上报后端，多个值用逗号分隔；none 表示关闭。",
    )
    parser.add_argument(
        "--run_name",
        type=str,
        default="qwen35_viscode_lora",
        help="训练运行名，同时作为 wandb run 名称。",
    )
    parser.add_argument(
        "--wandb_project",
        type=str,
        default="fusionprocessing-qwen35-lora",
        help="WandB 项目名。",
    )
    parser.add_argument(
        "--wandb_entity",
        type=str,
        default="",
        help="WandB 组织名；为空则不设置。",
    )
    parser.add_argument(
        "--wandb_api_key",
        type=str,
        default="",
        help="显式传入 WandB API Key，避免依赖环境变量。",
    )
    parser.add_argument(
        "--wandb_expected_email",
        type=str,
        default="",
        help="期望登录的 WandB 邮箱；若不匹配则直接报错。",
    )
    return parser.parse_args()


def load_json_dataset(dataset_path: str) -> Dataset:
    dataset = load_dataset("json", data_files=dataset_path, split="train")
    if "messages" not in dataset.column_names:
        raise ValueError("数据集缺少 messages 字段，无法按对话格式训练。")
    return dataset


def normalize_messages(messages: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for item in messages:
        role = str(item.get("role", "")).strip()
        content = item.get("content", "")
        if not role or content is None:
            continue
        normalized.append({"role": role, "content": str(content)})
    if len(normalized) < 2:
        raise ValueError("单条样本有效消息少于 2 条，无法构造监督信号。")
    return normalized


def build_tokenize_fn(
    tokenizer: AutoTokenizer,
    max_seq_len: int,
    train_on_prompt: bool,
):
    def tokenize_example(example: Dict[str, Any]) -> Dict[str, Any]:
        messages = normalize_messages(example["messages"])
        try:
            rendered = tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=False,
                return_dict=True,
                return_assistant_tokens_mask=True,
                truncation=True,
                max_length=max_seq_len,
            )
            input_ids = list(rendered["input_ids"])
            attention_mask = list(rendered["attention_mask"])
            assistant_mask = list(rendered.get("assistant_tokens_mask", []))
        except TypeError:
            input_ids = list(
                tokenizer.apply_chat_template(
                    messages,
                    tokenize=True,
                    add_generation_prompt=False,
                    truncation=True,
                    max_length=max_seq_len,
                )
            )
            attention_mask = [1] * len(input_ids)
            assistant_mask = []

        labels = list(input_ids)
        if assistant_mask and any(assistant_mask):
            labels = [token if keep else -100 for token, keep in zip(input_ids, assistant_mask)]
        elif not train_on_prompt:
            # 某些 tokenizer 尚不支持 assistant token mask。
            # 为避免把整段 prompt 都当成监督目标，这里仅保留最后一轮 assistant 的内容。
            last_assistant_idx = max(
                (idx for idx, item in enumerate(messages) if item["role"] == "assistant"),
                default=-1,
            )
            rendered_text = tokenizer.apply_chat_template(
                messages[: last_assistant_idx + 1],
                tokenize=False,
                add_generation_prompt=False,
            )
            prefix_text = tokenizer.apply_chat_template(
                messages[:last_assistant_idx],
                tokenize=False,
                add_generation_prompt=False,
            )
            total_ids = tokenizer(
                rendered_text,
                add_special_tokens=False,
                truncation=True,
                max_length=max_seq_len,
            )["input_ids"]
            prefix_ids = tokenizer(
                prefix_text,
                add_special_tokens=False,
                truncation=True,
                max_length=max_seq_len,
            )["input_ids"]
            supervised_from = min(len(prefix_ids), len(total_ids))
            labels = [-100] * len(input_ids)
            span = len(input_ids) - max(0, len(total_ids) - supervised_from)
            for idx in range(max(0, span), len(input_ids)):
                labels[idx] = input_ids[idx]

        return {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "labels": labels,
        }

    return tokenize_example


@dataclass
class SupervisedDataCollator:
    tokenizer: AutoTokenizer

    def __call__(self, features: List[Dict[str, List[int]]]) -> Dict[str, torch.Tensor]:
        pad_token_id = self.tokenizer.pad_token_id
        max_length = max(len(feature["input_ids"]) for feature in features)
        batch_input_ids: List[List[int]] = []
        batch_attention_mask: List[List[int]] = []
        batch_labels: List[List[int]] = []

        for feature in features:
            pad_length = max_length - len(feature["input_ids"])
            batch_input_ids.append(feature["input_ids"] + [pad_token_id] * pad_length)
            batch_attention_mask.append(feature["attention_mask"] + [0] * pad_length)
            batch_labels.append(feature["labels"] + [-100] * pad_length)

        return {
            "input_ids": torch.tensor(batch_input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(batch_attention_mask, dtype=torch.long),
            "labels": torch.tensor(batch_labels, dtype=torch.long),
        }


def count_trainable_parameters(model: torch.nn.Module) -> Dict[str, int]:
    trainable = 0
    total = 0
    for param in model.parameters():
        total += param.numel()
        if param.requires_grad:
            trainable += param.numel()
    return {"trainable": trainable, "total": total}


def get_model_and_tokenizer(args: argparse.Namespace):
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    is_distributed = world_size > 1

    if torch.cuda.is_available():
        torch.cuda.set_device(local_rank)

    tokenizer = AutoTokenizer.from_pretrained(args.model_name_or_path, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    quantization_config = None
    torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    if not args.disable_4bit:
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.float16,
        )

    if torch.cuda.is_available():
        device_map = {"": local_rank} if is_distributed else "auto"
    else:
        device_map = None

    model = AutoModelForCausalLM.from_pretrained(
        args.model_name_or_path,
        trust_remote_code=args.trust_remote_code,
        dtype=torch_dtype,
        quantization_config=quantization_config,
        device_map=device_map,
    )
    model.config.use_cache = False

    if not args.disable_4bit:
        model = prepare_model_for_kbit_training(
            model,
            use_gradient_checkpointing=True,
        )
    else:
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()

    target_modules = [item.strip() for item in args.target_modules.split(",") if item.strip()]
    lora_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        target_modules=target_modules,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    return model, tokenizer


def setup_wandb(args: argparse.Namespace) -> None:
    report_to = [item.strip() for item in args.report_to.split(",") if item.strip()]
    if "wandb" not in report_to:
        return

    import wandb

    login_kwargs = {
        "anonymous": "never",
        "relogin": True,
        "verify": True,
    }
    if args.wandb_api_key.strip():
        login_kwargs["key"] = args.wandb_api_key.strip()

    wandb.login(**login_kwargs)
    viewer = wandb.Api().viewer
    actual_email = str(getattr(viewer, "email", "") or "").strip().lower()
    expected_email = args.wandb_expected_email.strip().lower()
    if expected_email and actual_email != expected_email:
        raise RuntimeError(
            f"WandB 登录账号不匹配，当前为 {actual_email or 'UNKNOWN'}，期望为 {expected_email}。"
        )


def main() -> None:
    args = parse_args()
    set_seed(args.seed)
    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    is_main_process = local_rank == 0

    if args.report_to.strip().lower() != "none":
        setup_wandb(args)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    model, tokenizer = get_model_and_tokenizer(args)
    dataset = load_json_dataset(args.dataset_path)

    if args.sample_size > 0:
        dataset = dataset.select(range(min(args.sample_size, len(dataset))))

    tokenize_fn = build_tokenize_fn(
        tokenizer=tokenizer,
        max_seq_len=args.max_seq_len,
        train_on_prompt=args.train_on_prompt,
    )
    tokenized = dataset.map(
        tokenize_fn,
        remove_columns=dataset.column_names,
        num_proc=args.preprocessing_num_workers,
        desc="对话模板渲染与分词",
    )
    tokenized = tokenized.filter(
        lambda sample: any(label != -100 for label in sample["labels"]),
        desc="过滤无监督信号样本",
    )
    if len(tokenized) == 0:
        raise RuntimeError("预处理后没有可训练样本，请检查数据或 chat template。")

    params = count_trainable_parameters(model)
    effective_batch = args.per_device_train_batch_size * args.gradient_accumulation_steps
    if args.max_steps > 0:
        total_steps = args.max_steps
    else:
        total_steps = math.ceil(len(tokenized) / effective_batch) * args.num_train_epochs

    run_summary = {
        "model_name_or_path": args.model_name_or_path,
        "dataset_path": args.dataset_path,
        "dataset_size": len(tokenized),
        "max_seq_len": args.max_seq_len,
        "effective_batch_size": effective_batch,
        "estimated_total_steps": total_steps,
        "trainable_params": params["trainable"],
        "total_params": params["total"],
        "trainable_ratio": round(params["trainable"] / params["total"], 6),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
        "world_size": world_size,
        "local_rank": local_rank,
    }
    if is_main_process:
        print(json.dumps(run_summary, indent=2, ensure_ascii=False))
        (output_dir / "run_config.json").write_text(
            json.dumps({**vars(args), **run_summary}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    report_to = [item.strip() for item in args.report_to.split(",") if item.strip()]
    if not report_to or report_to == ["none"]:
        report_to = []

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        do_train=True,
        num_train_epochs=args.num_train_epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.per_device_train_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        weight_decay=args.weight_decay,
        warmup_ratio=args.warmup_ratio,
        lr_scheduler_type="cosine",
        logging_steps=args.logging_steps,
        save_steps=args.save_steps,
        save_total_limit=args.save_total_limit,
        fp16=torch.cuda.is_available(),
        bf16=False,
        report_to=report_to,
        remove_unused_columns=False,
        dataloader_num_workers=0,
        gradient_checkpointing=True,
        optim="paged_adamw_8bit" if not args.disable_4bit else "adamw_torch",
        ddp_find_unused_parameters=False if world_size > 1 else None,
        run_name=args.run_name,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized,
        data_collator=SupervisedDataCollator(tokenizer=tokenizer),
    )

    train_result = trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    trainer.save_model()
    tokenizer.save_pretrained(output_dir)
    trainer.log_metrics("train", train_result.metrics)
    trainer.save_metrics("train", train_result.metrics)
    trainer.save_state()


if __name__ == "__main__":
    main()
