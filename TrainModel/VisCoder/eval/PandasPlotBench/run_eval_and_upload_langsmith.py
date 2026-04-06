import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
from uuid import NAMESPACE_DNS, uuid4, uuid5

import pandas as pd
from langsmith import Client
from omegaconf import OmegaConf

from plotting_benchmark.code_bert_scorer import calc_code_bert_score
from plotting_benchmark.generation_engines.get_model import get_model_by_name
from plotting_benchmark.vis_judge import VisJudge


@dataclass
class EvalMetrics:
    total: int
    exec_ok: int
    plot_ok: int
    both_ok: int

    @property
    def exec_pass_rate(self) -> float:
        if self.total <= 0:
            return 0.0
        return self.exec_ok / self.total

    @property
    def plot_success_rate(self) -> float:
        if self.total <= 0:
            return 0.0
        return self.plot_ok / self.total


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行 PandasPlotBench 评测并上传 LangSmith Experiment。"
    )
    parser.add_argument(
        "--model",
        default="openai/QuantTrio/Qwen3.5-4B-AWQ",
        help="评测模型名（默认走 OpenAI 兼容本地服务）。",
    )
    parser.add_argument(
        "--config",
        default="configs/config_normal_baseline.yaml",
        help="评测配置文件路径。",
    )
    parser.add_argument(
        "--cuda",
        type=int,
        default=1,
        help="用于评测进程的 CUDA_VISIBLE_DEVICES。",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="评测样本数；与 --full 互斥。",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="全量评测（175 条），忽略 --limit。",
    )
    parser.add_argument(
        "--openai-base-url",
        default="http://127.0.0.1:2222/v1/chat/completions",
        help="OpenAI 兼容接口地址（本地 qwen3.5 服务）。",
    )
    parser.add_argument(
        "--openai-key",
        default="local-dev-key",
        help="OpenAI 兼容接口 key（本地服务可用占位值）。",
    )
    parser.add_argument(
        "--result-dir",
        default="eval_results/baseline/matplotlib",
        help="结果目录（用于自动定位最新结果文件）。",
    )
    parser.add_argument(
        "--dataset-name",
        default="qwen3.5-plot-baseline",
        help="LangSmith Dataset 名称。",
    )
    parser.add_argument(
        "--experiment-name",
        default="qwen3.5-plot",
        help="LangSmith Experiment 名称（默认 qwen3.5-plot）。",
    )
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="跳过评测，只解析并上传最新结果文件。",
    )
    parser.add_argument(
        "--result-file",
        default="",
        help="指定结果文件路径；为空时自动选择 result_dir 下最新文件。",
    )
    parser.add_argument(
        "--mode",
        default="all",
        choices=["all", "generate", "visual"],
        help="all=生成+执行+codebert+上传，generate=仅生成执行，visual=仅视觉评测+上传。",
    )
    parser.add_argument(
        "--enable-codebert",
        action="store_true",
        default=True,
        help="是否启用 codebert 代码相似度评估（默认开启）。",
    )
    parser.add_argument(
        "--visual-limit",
        type=int,
        default=0,
        help="视觉评测仅评前 N 条；0 表示全部。",
    )
    parser.add_argument(
        "--bench-types",
        default="vis,task",
        help="视觉评测类型，逗号分隔，可选 vis/task/codebert。",
    )
    parser.add_argument(
        "--judge-model",
        default="openai/qwen-image-2.0-pro",
        help="视觉评测模型（OpenAI 兼容前缀）。",
    )
    parser.add_argument(
        "--judge-openai-base-url",
        default="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        help="视觉评测 OpenAI 兼容接口地址。",
    )
    parser.add_argument(
        "--judge-openai-key",
        default="",
        help="视觉评测 API Key；为空时回退到环境变量 OPENAI_KEY。",
    )
    parser.add_argument(
        "--visual-out-file",
        default="",
        help="视觉评测输出结果文件；为空则自动生成。",
    )
    return parser.parse_args()


def _run_eval(args: argparse.Namespace) -> None:
    env = os.environ.copy()
    env["OPENAI_KEY"] = args.openai_key
    env["OPENAI_BASE_URL"] = args.openai_base_url
    env["CUDA_VISIBLE_DEVICES"] = str(args.cuda)

    cmd: List[str] = [
        sys.executable,
        "batch_eval_run.py",
        f"--cuda={args.cuda}",
        f"--model={args.model}",
        f"--config={args.config}",
    ]
    if not args.full:
        cmd.append(f"--limit={int(args.limit)}")

    print(f"[eval] command: {' '.join(cmd)}")
    subprocess.run(cmd, env=env, check=True)


def _pick_latest_result_file(result_dir: Path) -> Path:
    files = sorted(
        [item for item in result_dir.glob("results_*.json") if item.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError(f"未找到结果文件: {result_dir}")
    return files[0]


def _parse_bench_types(raw: str) -> List[str]:
    items = [item.strip() for item in str(raw or "").split(",")]
    items = [item for item in items if item]
    if not items:
        return ["vis", "task"]
    return items


def _run_visual_eval(
    args: argparse.Namespace,
    input_result_file: Path,
    output_result_file: Path,
) -> Path:
    """解耦视觉评测：基于已有生成结果单独评分，可控前 N 条。"""
    cfg = OmegaConf.load(args.config)
    bench_types = _parse_bench_types(args.bench_types)
    cfg.benchmark_types = bench_types

    # 读取评测提示模板
    instructs_file = cfg.paths.get("instructs_file")
    if not instructs_file:
        instructs_file = (
            Path(__file__).resolve().parent
            / "plotting_benchmark"
            / "resources"
            / "instructs.json"
        )
    instructs_payload = json.loads(Path(instructs_file).read_text(encoding="utf-8"))

    # 为视觉评测单独配置 judge，不影响生成模型服务。
    if args.judge_openai_key:
        os.environ["OPENAI_KEY"] = args.judge_openai_key
    os.environ["OPENAI_BASE_URL"] = args.judge_openai_base_url
    judge_model = get_model_by_name(
        args.judge_model,
        dict((cfg.model_judge or {}).get("parameters", {"temperature": 0.0})),
        instructs_payload.get("system_prompt", "You are helpful assistant"),
    )
    judge = VisJudge(
        vis_judge_model=judge_model,
        instructs=instructs_payload,
        benchmark_types=bench_types,
        plot_lib=str(cfg.plotting_lib),
    )

    dataset_df = pd.read_json(input_result_file)
    if int(args.visual_limit) > 0:
        dataset_df = dataset_df.head(int(args.visual_limit)).copy()
    scored_df = judge.score(dataset_df)
    output_result_file.parent.mkdir(parents=True, exist_ok=True)
    scored_df.to_json(output_result_file)

    # 写一份简明统计，便于快速看效果。
    stats = judge.calculate_stats(scored_df)
    stats_path = output_result_file.with_suffix(".stats.json")
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[visual] stats saved: {stats_path}")
    return output_result_file


def _run_codebert_eval(input_result_file: Path, output_result_file: Path) -> Path:
    """基于已有生成结果单独计算 codebert，相当于非视觉质量评测。"""
    dataset_df = pd.read_json(input_result_file)
    scored_df = calc_code_bert_score(dataset_df)
    output_result_file.parent.mkdir(parents=True, exist_ok=True)
    scored_df.to_json(output_result_file)
    stats = {
        "metric": "codebert",
        "count": int(len(scored_df)),
        "mean_score_codebert": float(scored_df["score_codebert"].fillna(0).mean())
        if "score_codebert" in scored_df.columns
        else 0.0,
    }
    stats_path = output_result_file.with_suffix(".stats.json")
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[codebert] stats saved: {stats_path}")
    return output_result_file


def _to_rows(payload: Any) -> List[Dict[str, Any]]:
    # 兼容两种结构：
    # 1) list[dict] 每行一条样本；
    # 2) dict[str, dict[index->value]] 的列式结构（Pandas to_json 默认产物）。
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    if not payload:
        return []
    first_val = next(iter(payload.values()))
    if not isinstance(first_val, dict):
        return []

    index_keys = sorted(first_val.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x))
    rows: List[Dict[str, Any]] = []
    for idx in index_keys:
        row: Dict[str, Any] = {}
        for col, col_values in payload.items():
            if isinstance(col_values, dict):
                row[col] = col_values.get(idx)
        rows.append(row)
    return rows


def _calc_metrics(rows: Iterable[Dict[str, Any]]) -> EvalMetrics:
    total = 0
    exec_ok = 0
    plot_ok = 0
    both_ok = 0
    for row in rows:
        total += 1
        err = str((row or {}).get("error") or "").strip()
        has_plot = bool((row or {}).get("has_plot", False))
        ok_exec = err == ""
        if ok_exec:
            exec_ok += 1
        if has_plot:
            plot_ok += 1
        if ok_exec and has_plot:
            both_ok += 1
    return EvalMetrics(total=total, exec_ok=exec_ok, plot_ok=plot_ok, both_ok=both_ok)


def _ensure_dataset(client: Client, dataset_name: str) -> Any:
    try:
        return client.read_dataset(dataset_name=dataset_name)
    except Exception:
        return client.create_dataset(
            dataset_name=dataset_name,
            description="PandasPlotBench baseline metrics for qwen3.5 plotting.",
        )


def _create_project_with_fallback_name(
    client: Client, experiment_name: str, description: str, dataset_id: str
) -> Tuple[Any, str]:
    try_names = [experiment_name]
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    try_names.append(f"{experiment_name}-{suffix}")
    try_names.append(f"{experiment_name}-{uuid4().hex[:8]}")

    last_exc: Exception | None = None
    for name in try_names:
        try:
            project = client.create_project(
                project_name=name,
                description=description,
                metadata={
                    "source": "pandasplotbench",
                    "script": "run_eval_and_upload_langsmith.py",
                },
                reference_dataset_id=dataset_id,
            )
            return project, name
        except Exception as exc:
            last_exc = exc
            continue
    raise RuntimeError(f"创建 LangSmith project 失败: {last_exc}")


def _upload_to_langsmith(
    args: argparse.Namespace, result_file: Path, metrics: EvalMetrics, rows: List[Dict[str, Any]]
) -> Dict[str, Any]:
    client = Client()
    dataset = _ensure_dataset(client, args.dataset_name)
    desc = (
        "Qwen3.5 plotting baseline before LoRA fine-tuning. "
        f"model={args.model}, file={result_file.name}"
    )
    project, actual_name = _create_project_with_fallback_name(
        client=client,
        experiment_name=args.experiment_name,
        description=desc,
        dataset_id=str(dataset.id),
    )
    # 创建单独的上传 Trace 根节点：该 trace 只承载本次评测上传结果。
    trace_root_run_id = str(uuid4())
    now = datetime.now(timezone.utc)
    client.create_run(
        id=trace_root_run_id,
        project_name=actual_name,
        name="pandasplotbench_upload_trace",
        run_type="chain",
        inputs={
            "model": args.model,
            "result_file": str(result_file),
            "total": metrics.total,
            "full": bool(args.full),
            "limit": None if args.full else int(args.limit),
        },
        outputs={
            "exec_pass_rate": metrics.exec_pass_rate,
            "plot_success_rate": metrics.plot_success_rate,
            "both_ok_rate": (metrics.both_ok / metrics.total) if metrics.total else 0.0,
            "exec_ok": metrics.exec_ok,
            "plot_ok": metrics.plot_ok,
            "both_ok": metrics.both_ok,
            "total": metrics.total,
        },
        start_time=now,
        end_time=now,
        extra={
            "metadata": {
                "stage": "pre-lora-baseline",
                "name": args.experiment_name,
                "trace_type": "summary_root",
            }
        },
    )
    client.create_feedback(
        run_id=trace_root_run_id,
        key="exec_pass_rate",
        score=float(metrics.exec_pass_rate),
        comment=f"exec_ok={metrics.exec_ok}, total={metrics.total}",
    )
    client.create_feedback(
        run_id=trace_root_run_id,
        key="plot_success_rate",
        score=float(metrics.plot_success_rate),
        comment=f"plot_ok={metrics.plot_ok}, total={metrics.total}",
    )
    codebert_scores = []
    vis_scores = []
    task_scores = []
    for row in rows:
        score_codebert = (row or {}).get("score_codebert")
        score_vis = (row or {}).get("score_vis")
        score_task = (row or {}).get("score_task")
        if isinstance(score_codebert, (int, float)):
            codebert_scores.append(float(score_codebert))
        if isinstance(score_vis, (int, float)):
            vis_scores.append(float(score_vis))
        if isinstance(score_task, (int, float)):
            task_scores.append(float(score_task))
    if codebert_scores:
        client.create_feedback(
            run_id=trace_root_run_id,
            key="mean_score_codebert",
            score=float(sum(codebert_scores) / len(codebert_scores)),
            comment=f"count={len(codebert_scores)}",
        )
    if vis_scores:
        client.create_feedback(
            run_id=trace_root_run_id,
            key="mean_score_vis",
            score=float(sum(vis_scores) / len(vis_scores)),
            comment=f"count={len(vis_scores)}",
        )
    if task_scores:
        client.create_feedback(
            run_id=trace_root_run_id,
            key="mean_score_task",
            score=float(sum(task_scores) / len(task_scores)),
            comment=f"count={len(task_scores)}",
        )

    # 逐样本上传：每个 case 一个子 run，并写入 case 指标 feedback。
    for idx, row in enumerate(rows):
        sid = str((row or {}).get("id", "")).strip()
        if not sid:
            sid = f"row-{idx}"
        err = str((row or {}).get("error", "") or "").strip()
        has_plot = bool((row or {}).get("has_plot", False))
        exec_ok = 1.0 if err == "" else 0.0
        plot_ok = 1.0 if has_plot else 0.0
        both_ok = 1.0 if (exec_ok > 0 and plot_ok > 0) else 0.0
        sample_run_id = str(uuid5(NAMESPACE_DNS, f"viscoder-sample-run:{actual_name}:{sid}"))
        client.create_run(
            id=sample_run_id,
            project_name=actual_name,
            name=f"case-{sid}",
            run_type="chain",
            parent_run_id=trace_root_run_id,
            inputs={
                "sample_id": sid,
                "task_plot_description": (row or {}).get("task__plot_description", ""),
                "task_plot_style": (row or {}).get("task__plot_style", ""),
            },
            outputs={
                "error": err,
                "has_plot": has_plot,
                "exec_ok": bool(exec_ok),
                "plot_ok": bool(plot_ok),
                "both_ok": bool(both_ok),
                "generated_code": (row or {}).get("code", ""),
            },
            start_time=now,
            end_time=now,
            error=err or None,
            extra={"metadata": {"sample_id": sid, "trace_type": "case_run"}},
        )
        client.create_feedback(
            run_id=sample_run_id,
            key="exec_ok",
            score=exec_ok,
            comment=f"error={err}" if err else "execution passed",
        )
        client.create_feedback(
            run_id=sample_run_id,
            key="plot_ok",
            score=plot_ok,
            comment=f"has_plot={has_plot}",
        )
        client.create_feedback(
            run_id=sample_run_id,
            key="both_ok",
            score=both_ok,
            comment=f"exec_ok={bool(exec_ok)} has_plot={has_plot}",
        )
        score_codebert = (row or {}).get("score_codebert")
        if isinstance(score_codebert, (int, float)):
            client.create_feedback(
                run_id=sample_run_id,
                key="score_codebert",
                score=float(score_codebert),
                comment="code similarity score",
            )
        score_vis = (row or {}).get("score_vis")
        if isinstance(score_vis, (int, float)):
            client.create_feedback(
                run_id=sample_run_id,
                key="score_vis",
                score=float(score_vis),
                comment="visual similarity score",
            )
        score_task = (row or {}).get("score_task")
        if isinstance(score_task, (int, float)):
            client.create_feedback(
                run_id=sample_run_id,
                key="score_task",
                score=float(score_task),
                comment="task alignment score",
            )

    return {
        "dataset_name": dataset.name,
        "dataset_id": str(dataset.id),
        "experiment_name": actual_name,
        "project_url": str(getattr(project, "url", "") or ""),
        "trace_root_run_id": trace_root_run_id,
        "case_run_count": len(rows),
    }


def main() -> int:
    args = _parse_args()

    mode = str(args.mode)
    run_generation = mode in {"all", "generate"} and (not args.skip_eval)
    run_visual = mode == "visual"
    run_codebert = bool(args.enable_codebert) and mode == "all"

    if run_generation:
        _run_eval(args)

    if args.result_file:
        result_file = Path(args.result_file).resolve()
    else:
        result_file = _pick_latest_result_file(Path(args.result_dir).resolve())
    if not result_file.exists():
        raise FileNotFoundError(f"结果文件不存在: {result_file}")

    if run_visual:
        if args.visual_out_file:
            visual_out = Path(args.visual_out_file).resolve()
        else:
            suffix = (
                f".visual_n{args.visual_limit}.json"
                if int(args.visual_limit) > 0
                else ".visual_all.json"
            )
            visual_out = result_file.with_name(result_file.stem + suffix)
        result_file = _run_visual_eval(
            args=args,
            input_result_file=result_file,
            output_result_file=visual_out,
        )
    elif run_codebert:
        codebert_out = result_file.with_name(result_file.stem + ".codebert.json")
        result_file = _run_codebert_eval(
            input_result_file=result_file,
            output_result_file=codebert_out,
        )

    payload = json.loads(result_file.read_text(encoding="utf-8"))
    rows = _to_rows(payload)
    metrics = _calc_metrics(rows)

    print(
        "[metrics] "
        f"total={metrics.total} "
        f"exec_ok={metrics.exec_ok} exec_pass_rate={metrics.exec_pass_rate:.4f} "
        f"plot_ok={metrics.plot_ok} plot_success_rate={metrics.plot_success_rate:.4f} "
        f"both_ok={metrics.both_ok}"
    )

    upload_info = _upload_to_langsmith(
        args=args, result_file=result_file, metrics=metrics, rows=rows
    )
    print("[langsmith] uploaded:", json.dumps(upload_info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
