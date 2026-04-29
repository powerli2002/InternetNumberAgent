#!/usr/bin/env python3
"""将 Qwen3.5 LoRA adapter 合并为可直接推理的完整模型。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="合并 Qwen3.5 LoRA adapter 为完整模型")
    parser.add_argument(
        "--adapter_dir",
        type=str,
        default=str(Path(__file__).resolve().parent / "output" / "qwen35_lora_run"),
        help="LoRA adapter 所在目录，目录中需要包含 adapter_config.json。",
    )
    parser.add_argument(
        "--base_model_name_or_path",
        type=str,
        default="",
        help="基础模型路径或 HuggingFace 模型名；留空时从 adapter_config.json 读取。",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="",
        help="合并后的完整模型输出目录；留空时默认写入 adapter_dir/merged_model。",
    )
    parser.add_argument(
        "--trust_remote_code",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="允许加载 Qwen3.5 的远程模型定义。",
    )
    parser.add_argument(
        "--torch_dtype",
        type=str,
        default="auto",
        choices=("auto", "float16", "bfloat16", "float32"),
        help="合并时使用的模型精度。",
    )
    return parser.parse_args()


def resolve_base_model_name(adapter_dir: Path, explicit_base_model: str) -> str:
    """优先使用显式参数；若未提供，则从 adapter 配置中读取基础模型名。"""

    if explicit_base_model.strip():
        return explicit_base_model.strip()

    adapter_config_path = adapter_dir / "adapter_config.json"
    if not adapter_config_path.exists():
        raise FileNotFoundError(f"未找到 {adapter_config_path}，无法推断基础模型。")

    adapter_config = json.loads(adapter_config_path.read_text(encoding="utf-8"))
    base_model_name = str(adapter_config.get("base_model_name_or_path", "")).strip()
    if not base_model_name:
        raise ValueError("adapter_config.json 中缺少 base_model_name_or_path，请显式传入 --base_model_name_or_path。")
    return base_model_name


def resolve_dtype(dtype_name: str) -> Optional[torch.dtype]:
    """把命令行字符串映射为 torch.dtype。"""

    if dtype_name == "auto":
        return torch.float16 if torch.cuda.is_available() else torch.float32
    if dtype_name == "float16":
        return torch.float16
    if dtype_name == "bfloat16":
        return torch.bfloat16
    if dtype_name == "float32":
        return torch.float32
    raise ValueError(f"不支持的 torch_dtype: {dtype_name}")


def merge_lora_adapter(
    adapter_dir: str,
    output_dir: str,
    base_model_name_or_path: str = "",
    trust_remote_code: bool = True,
    torch_dtype: str = "auto",
) -> None:
    """加载基础模型和 LoRA adapter，合并后导出完整模型。"""

    adapter_path = Path(adapter_dir).resolve()
    output_path = Path(output_dir).resolve()
    base_model_name = resolve_base_model_name(adapter_path, base_model_name_or_path)
    model_dtype = resolve_dtype(torch_dtype)

    tokenizer = AutoTokenizer.from_pretrained(
        adapter_path,
        use_fast=True,
        trust_remote_code=trust_remote_code,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    base_model = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        trust_remote_code=trust_remote_code,
        dtype=model_dtype,
        low_cpu_mem_usage=True,
        device_map="cpu",
    )
    peft_model = PeftModel.from_pretrained(base_model, adapter_path, is_trainable=False)
    merged_model = peft_model.merge_and_unload()

    output_path.mkdir(parents=True, exist_ok=True)
    merged_model.save_pretrained(output_path, safe_serialization=True)
    tokenizer.save_pretrained(output_path)

    merge_summary = {
        "adapter_dir": str(adapter_path),
        "base_model_name_or_path": base_model_name,
        "output_dir": str(output_path),
        "trust_remote_code": trust_remote_code,
        "torch_dtype": torch_dtype,
    }
    (output_path / "merge_config.json").write_text(
        json.dumps(merge_summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(merge_summary, indent=2, ensure_ascii=False))


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.strip() or str(Path(args.adapter_dir).resolve() / "merged_model")
    merge_lora_adapter(
        adapter_dir=args.adapter_dir,
        output_dir=output_dir,
        base_model_name_or_path=args.base_model_name_or_path,
        trust_remote_code=args.trust_remote_code,
        torch_dtype=args.torch_dtype,
    )


if __name__ == "__main__":
    main()
