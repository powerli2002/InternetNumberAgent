import os

import code_bert_score
import pandas as pd
import torch


# %%
def _remap_visible_cuda_device(raw_device: str) -> str:
    """把用户传入的物理 GPU 编号映射为当前进程可见的逻辑编号。

    典型场景：外层脚本用 `CUDA_VISIBLE_DEVICES=3` 启动评测进程，
    同时又把 `PLOT_BENCH_CODEBERT_DEVICE` 设成 `cuda:3`。此时在
    进程内部，物理 GPU 3 会变成逻辑 `cuda:0`；若继续直接使用
    `cuda:3`，会触发 invalid device ordinal。
    """
    value = str(raw_device or "").strip()
    if not value.startswith("cuda:"):
        return value

    try:
        physical_index = int(value.split(":", 1)[1])
    except (IndexError, ValueError):
        return value

    visible_devices = str(os.getenv("CUDA_VISIBLE_DEVICES", "") or "").strip()
    if not visible_devices:
        return value

    visible_list = [item.strip() for item in visible_devices.split(",") if item.strip()]
    if not visible_list:
        return value

    try:
        logical_index = visible_list.index(str(physical_index))
    except ValueError:
        return value

    remapped = f"cuda:{logical_index}"
    print(
        "[codebert] remap device "
        f"{value} -> {remapped} under CUDA_VISIBLE_DEVICES={visible_devices}"
    )
    return remapped


def _resolve_codebert_device() -> torch.device:
    """解析 codebert 评分设备。

    优先级：
    1. 环境变量 `PLOT_BENCH_CODEBERT_DEVICE`
    2. 若 CUDA 可用，则默认 `cuda`
    3. 否则回退 `cpu`
    """
    raw_device = str(os.getenv("PLOT_BENCH_CODEBERT_DEVICE", "") or "").strip()
    if raw_device:
        remapped_device = _remap_visible_cuda_device(raw_device)
        return torch.device(remapped_device)
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def calc_code_bert_score(dataset: pd.DataFrame) -> pd.DataFrame:
    print("Scoring on the code-bert-score.")
    device = _resolve_codebert_device()
    print(f"[codebert] device: {device}")

    bert_score = code_bert_score.score(
        cands=list(dataset["code_plot"]),
        refs=list(dataset["code"]),
        lang="python",
        device=device,
        verbose=True,
        batch_size=200,
    )
    bert_score_f1 = bert_score[2].tolist()

    dataset["score_codebert"] = bert_score_f1

    return dataset
