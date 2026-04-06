#!/usr/bin/env python3
"""采样估算 Qwen3.5 LoRA/QLoRA 在 VisCode-200K 上的训练规模与时间。"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any, Dict, Iterable, List

from datasets import load_dataset
from transformers import AutoTokenizer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="估算 Qwen3.5 LoRA 训练资源")
    parser.add_argument(
        "--model_name_or_path",
        type=str,
        default="Qwen/Qwen3.5-4B",
        help="用于估算 token 长度的 tokenizer。",
    )
    parser.add_argument(
        "--dataset_path",
        type=str,
        default=str(Path(__file__).resolve().parents[1] / ".." / "VisCode-200K" / "VisCode-200K-uuid.jsonl"),
        help="VisCode-200K 数据集 jsonl 路径。",
    )
    parser.add_argument("--sample_size", type=int, default=1024, help="采样条数。")
    parser.add_argument("--max_seq_len", type=int, default=1024, help="训练最大长度。")
    parser.add_argument("--per_device_train_batch_size", type=int, default=1, help="单卡 batch size。")
    parser.add_argument("--gradient_accumulation_steps", type=int, default=8, help="梯度累积步数。")
    parser.add_argument("--num_train_epochs", type=float, default=1.0, help="训练轮数。")
    parser.add_argument(
        "--observed_step_seconds",
        type=float,
        default=0.0,
        help="若已经跑过 1 个 optimizer step，可填入实测秒数以估算总时长。",
    )
    return parser.parse_args()


def normalize_messages(messages: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    for item in messages:
        role = str(item.get("role", "")).strip()
        content = item.get("content", "")
        if role and content is not None:
            result.append({"role": role, "content": str(content)})
    return result


def main() -> None:
    args = parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model_name_or_path, use_fast=True)
    dataset = load_dataset("json", data_files=args.dataset_path, split="train")
    total_examples = len(dataset)
    sample_size = min(args.sample_size, total_examples)
    dataset = dataset.select(range(sample_size))

    token_lengths: List[int] = []
    for row in dataset:
        messages = normalize_messages(row["messages"])
        rendered = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=False,
            truncation=True,
            max_length=args.max_seq_len,
        )
        if hasattr(rendered, "encodings") and rendered.encodings:
            token_ids = rendered.encodings[0].ids
        elif isinstance(rendered, dict):
            token_ids = rendered.get("input_ids", [])
        else:
            token_ids = rendered
        token_lengths.append(len(token_ids))

    effective_batch_size = args.per_device_train_batch_size * args.gradient_accumulation_steps
    avg_tokens = statistics.mean(token_lengths)
    total_tokens = avg_tokens * total_examples * args.num_train_epochs
    optimizer_steps = math.ceil(total_examples / effective_batch_size) * args.num_train_epochs

    result = {
        "model_name_or_path": args.model_name_or_path,
        "dataset_path": args.dataset_path,
        "total_examples": total_examples,
        "sample_size": sample_size,
        "max_seq_len": args.max_seq_len,
        "token_length_mean": round(avg_tokens, 2),
        "token_length_median": int(statistics.median(token_lengths)),
        "token_length_p95": sorted(token_lengths)[int(len(token_lengths) * 0.95) - 1],
        "token_length_max": max(token_lengths),
        "effective_batch_size": effective_batch_size,
        "estimated_total_tokens": int(total_tokens),
        "estimated_optimizer_steps": int(optimizer_steps),
    }
    if args.observed_step_seconds > 0:
        total_seconds = optimizer_steps * args.observed_step_seconds
        result["estimated_total_hours"] = round(total_seconds / 3600, 2)
        result["estimated_total_days"] = round(total_seconds / 86400, 2)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
