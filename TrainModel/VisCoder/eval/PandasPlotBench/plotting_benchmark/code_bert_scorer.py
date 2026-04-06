import os

import code_bert_score
import pandas as pd
import torch


# %%
def _resolve_codebert_device() -> torch.device:
    """解析 codebert 评分设备。

    优先级：
    1. 环境变量 `PLOT_BENCH_CODEBERT_DEVICE`
    2. 若 CUDA 可用，则默认 `cuda`
    3. 否则回退 `cpu`
    """
    raw_device = str(os.getenv("PLOT_BENCH_CODEBERT_DEVICE", "") or "").strip()
    if raw_device:
        return torch.device(raw_device)
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
