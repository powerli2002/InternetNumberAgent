#!/usr/bin/env python3
"""使用 llmcompressor 的 AWQModifier 导出 Qwen3.5 AWQ 模型。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用 llmcompressor 导出 AWQ 量化模型")
    parser.add_argument("--model", required=True, help="merge 后完整模型目录")
    parser.add_argument("--output", required=True, help="量化输出目录")
    parser.add_argument(
        "--trust-remote-code",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否允许加载远程模型定义",
    )
    parser.add_argument("--w-bit", type=int, default=4, help="权重量化 bit 数")
    parser.add_argument("--group-size", type=int, default=128, help="分组大小")
    parser.add_argument(
        "--zero-point",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否使用非对称量化",
    )
    parser.add_argument(
        "--version",
        default="gemm",
        help="保留兼容字段；llmcompressor 路径当前不使用该参数",
    )
    parser.add_argument(
        "--calib-data",
        default="ultrachat-200k",
        help="校准数据集名，默认 ultrachat-200k",
    )
    parser.add_argument(
        "--calib-split",
        default="train",
        help="校准数据集 split，默认 train",
    )
    parser.add_argument(
        "--text-column",
        default="text",
        help="校准文本列名，默认 text",
    )
    parser.add_argument(
        "--calib-samples",
        type=int,
        default=128,
        help="校准样本数，默认 128",
    )
    parser.add_argument(
        "--max-seq-length",
        type=int,
        default=1024,
        help="校准时最大序列长度，默认 1024",
    )
    parser.add_argument(
        "--dtype",
        default="auto",
        help="加载模型精度，默认 auto",
    )
    return parser.parse_args()


def _import_llmcompressor():
    try:
        from llmcompressor import oneshot
        from llmcompressor.modifiers.awq.base import AWQModifier
        from llmcompressor.modifiers.awq.mappings import AWQMapping
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "未安装或未正确配置 llmcompressor。请在当前环境中安装：\n"
            "  TrainModel/VisCoder/.venv-lora-uv/bin/pip install llmcompressor"
        ) from exc
    return oneshot, AWQModifier, AWQMapping


def build_qwen35_mappings(config, AWQMapping):
    """为 Qwen3.5 hybrid attention 结构构造 AWQ smoothing 映射。"""

    layer_types = list(getattr(config, "layer_types", []) or [])
    if not layer_types:
        raise ValueError("Qwen3.5 config 缺少 layer_types，无法构造 AWQ 映射。")

    mappings = []
    for index, layer_type in enumerate(layer_types):
        layer_prefix = f"re:.*layers\\.{index}\\."
        if layer_type == "full_attention":
            mappings.append(
                AWQMapping(
                    f"{layer_prefix}input_layernorm$",
                    [
                        f"{layer_prefix}self_attn.q_proj$",
                        f"{layer_prefix}self_attn.k_proj$",
                        f"{layer_prefix}self_attn.v_proj$",
                    ],
                )
            )
            mappings.append(
                AWQMapping(
                    f"{layer_prefix}self_attn.v_proj$",
                    [f"{layer_prefix}self_attn.o_proj$"],
                )
            )
        elif layer_type == "linear_attention":
            mappings.append(
                AWQMapping(
                    f"{layer_prefix}input_layernorm$",
                    [
                        f"{layer_prefix}linear_attn.in_proj_qkv$",
                        f"{layer_prefix}linear_attn.in_proj_z$",
                        f"{layer_prefix}linear_attn.in_proj_b$",
                        f"{layer_prefix}linear_attn.in_proj_a$",
                    ],
                )
            )
        else:
            raise ValueError(f"未知 layer_type: {layer_type}")

        mappings.append(
            AWQMapping(
                f"{layer_prefix}post_attention_layernorm$",
                [
                    f"{layer_prefix}mlp.gate_proj$",
                    f"{layer_prefix}mlp.up_proj$",
                ],
            )
        )
        mappings.append(
            AWQMapping(
                f"{layer_prefix}mlp.up_proj$",
                [f"{layer_prefix}mlp.down_proj$"],
            )
        )

    return mappings


def export_awq(args: argparse.Namespace) -> None:
    oneshot, AWQModifier, AWQMapping = _import_llmcompressor()

    model_dir = Path(args.model).resolve()
    output_dir = Path(args.output).resolve()
    if not model_dir.exists():
        raise FileNotFoundError(f"未找到模型目录：{model_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[info] load config: {model_dir}")
    config = AutoConfig.from_pretrained(
        model_dir, trust_remote_code=args.trust_remote_code
    )
    mappings = build_qwen35_mappings(config, AWQMapping)

    print(f"[info] load tokenizer: {model_dir}")
    tokenizer = AutoTokenizer.from_pretrained(
        model_dir,
        trust_remote_code=args.trust_remote_code,
        use_fast=True,
    )

    print(f"[info] load model: {model_dir}")
    model = AutoModelForCausalLM.from_pretrained(
        model_dir,
        trust_remote_code=args.trust_remote_code,
        dtype=args.dtype,
        device_map="auto",
    )

    if args.w_bit != 4:
        raise ValueError("当前 llmcompressor AWQ 导出脚本只支持 4bit 权重。")
    if args.group_size != 128:
        raise ValueError("当前 llmcompressor AWQ 预置方案只支持 group_size=128。")

    scheme_name = "W4A16_ASYM" if args.zero_point else "W4A16"
    recipe = [
        AWQModifier(
            targets=["Linear"],
            ignore=["lm_head"],
            scheme=scheme_name,
            mappings=mappings,
        )
    ]

    print(
        json.dumps(
            {
                "model_dir": str(model_dir),
                "output_dir": str(output_dir),
                "scheme": scheme_name,
                "group_size": args.group_size,
                "calib_data": args.calib_data,
                "calib_split": args.calib_split,
                "calib_samples": args.calib_samples,
                "max_seq_length": args.max_seq_length,
                "mapping_count": len(mappings),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    oneshot(
        model=model,
        tokenizer=tokenizer,
        recipe=recipe,
        dataset=args.calib_data,
        splits=args.calib_split,
        num_calibration_samples=args.calib_samples,
        max_seq_length=args.max_seq_length,
        text_column=args.text_column,
    )

    print(f"[info] save compressed model: {output_dir}")
    model.save_pretrained(output_dir, save_compressed=True)
    tokenizer.save_pretrained(output_dir)

    summary = {
        "model_dir": str(model_dir),
        "output_dir": str(output_dir),
        "scheme": scheme_name,
        "group_size": args.group_size,
        "zero_point": args.zero_point,
        "calib_data": args.calib_data,
        "calib_split": args.calib_split,
        "text_column": args.text_column,
        "calib_samples": args.calib_samples,
        "max_seq_length": args.max_seq_length,
        "mapping_count": len(mappings),
    }
    (output_dir / "awq_export_config.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    export_awq(parse_args())


if __name__ == "__main__":
    main()
