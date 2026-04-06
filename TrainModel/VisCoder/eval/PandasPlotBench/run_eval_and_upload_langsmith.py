import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
from uuid import NAMESPACE_DNS, uuid4, uuid5

import pandas as pd
from dotenv import load_dotenv
from langsmith import Client
from omegaconf import OmegaConf

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


def _as_chat_completions_url(base_url: str) -> str:
    base = str(base_url or "").strip()
    if not base:
        return ""
    if base.endswith("/chat/completions"):
        return base
    return f"{base.rstrip('/')}/chat/completions"


def _load_env_files() -> None:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parents[3]
    candidates = [
        script_dir / ".env",
        script_dir.parent / ".env",
        repo_root / "conf" / ".env",
    ]

    loaded: set[Path] = set()
    for candidate in candidates:
        if candidate in loaded or not candidate.exists():
            continue
        # 不覆盖已经在 shell 中显式设置的环境变量，保证 CLI/外部导出优先级更高。
        load_dotenv(candidate, override=False)
        loaded.add(candidate)


def _default_openai_base_url() -> str:
    return (
        os.getenv("OPENAI_BASE_URL")
        or _as_chat_completions_url(os.getenv("LOCAL_LLM_BASE_URL", ""))
        or "http://127.0.0.1:2222/v1/chat/completions"
    )


def _default_openai_key() -> str:
    return os.getenv("OPENAI_KEY") or os.getenv("LOCAL_LLM_API_KEY") or "local-dev-key"


def _default_judge_base_url() -> str:
    return (
        os.getenv("JUDGE_OPENAI_BASE_URL")
        or _as_chat_completions_url(os.getenv("DASHSCOPE_BASE_URL", ""))
        or "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )


def _default_judge_key() -> str:
    return os.getenv("JUDGE_OPENAI_KEY") or os.getenv("DASHSCOPE_API_KEY") or ""


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
        default=_default_openai_base_url(),
        help="OpenAI 兼容接口地址（本地 qwen3.5 服务）。",
    )
    parser.add_argument(
        "--openai-key",
        default=_default_openai_key(),
        help="OpenAI 兼容接口 key（本地服务可用占位值）。",
    )
    parser.add_argument(
        "--result-dir",
        default="eval_results/baseline/matplotlib",
        help="结果目录（用于自动定位最新结果文件）。",
    )
    parser.add_argument(
        "--dataset-name",
        default=os.getenv("PLOT_BENCH_DATASET_NAME", "qwen3.5-plot-baseline"),
        help="LangSmith Dataset 名称。",
    )
    parser.add_argument(
        "--experiment-name",
        default=os.getenv("PLOT_BENCH_EXPERIMENT_NAME", "qwen3.5-plot"),
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
        default="generate",
        choices=["all", "generate", "visual"],
        help="generate/all=生成+执行+codebert+上传，visual=仅视觉评测+上传。",
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
        default=_default_judge_base_url(),
        help="视觉评测 OpenAI 兼容接口地址。",
    )
    parser.add_argument(
        "--judge-openai-key",
        default=_default_judge_key(),
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
    def _is_primary_result_file(path: Path) -> bool:
        name = path.name
        if not path.is_file() or not name.startswith("results_") or not name.endswith(".json"):
            return False
        excluded_markers = (".visual_", ".visual_all", ".codebert", ".stats")
        return not any(marker in name for marker in excluded_markers)

    files = sorted(
        [item for item in result_dir.iterdir() if _is_primary_result_file(item)],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError(f"未找到主结果文件: {result_dir}")
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
    from plotting_benchmark.code_bert_scorer import calc_code_bert_score

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


def _stable_example_id(sample_id: str) -> str:
    return str(uuid5(NAMESPACE_DNS, f"viscoder-example:{sample_id}"))


def _stable_run_id(experiment_name: str, sample_id: str) -> str:
    return str(uuid5(NAMESPACE_DNS, f"viscoder-run:{experiment_name}:{sample_id}"))


def _stable_feedback_id(project_id: str, run_id: str, key: str) -> str:
    return str(uuid5(NAMESPACE_DNS, f"viscoder-feedback:{project_id}:{run_id}:{key}"))


def _build_compare_url(project: Any, dataset_id: str) -> str:
    project_url = str(getattr(project, "url", "") or "").strip()
    project_id = str(getattr(project, "id", "") or "").strip()
    if not project_url or not project_id or not dataset_id:
        return ""
    base_url = project_url.split("/projects/p/")[0]
    return f"{base_url}/datasets/{dataset_id}/compare?selectedSessions={project_id}"


def _ensure_dataset(client: Client, dataset_name: str, description: str) -> Any:
    try:
        return client.read_dataset(dataset_name=dataset_name)
    except Exception:
        return client.create_dataset(
            dataset_name=dataset_name,
            description=description,
        )


def _upsert_examples(client: Client, dataset: Any, rows: Iterable[Dict[str, Any]]) -> None:
    examples: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows):
        sid = str((row or {}).get("id", "")).strip() or f"row-{idx}"
        plots_gt = (row or {}).get("plots_gt") or []
        examples.append(
            {
                "id": _stable_example_id(sid),
                "inputs": {
                    "id": sid,
                    "task_plot_description": str(
                        (row or {}).get("task__plot_description", "") or ""
                    ),
                    "task_plot_style": str((row or {}).get("task__plot_style", "") or ""),
                    "task": str((row or {}).get("task", "") or ""),
                },
                "outputs": {
                    "reference_plot_count": len(plots_gt) if isinstance(plots_gt, list) else 0,
                    "data_descriptor": str((row or {}).get("data_descriptor", "") or ""),
                },
                "metadata": {
                    "sample_id": sid,
                    "has_ground_truth_plot": bool(plots_gt),
                },
            }
        )

    if not examples:
        return

    existing_ids: set[str] = set()
    for example in examples:
        try:
            found_examples = list(
                client.list_examples(dataset_id=dataset.id, example_ids=[example["id"]])
            )
        except Exception:
            found_examples = []
        if found_examples:
            existing_ids.add(str(found_examples[0].id))

    create_payloads = [
        example for example in examples if example["id"] not in existing_ids
    ]
    update_payloads = [
        {
            "id": example["id"],
            "inputs": example["inputs"],
            "outputs": example["outputs"],
            "metadata": example["metadata"],
        }
        for example in examples
        if example["id"] in existing_ids
    ]

    if create_payloads:
        client.create_examples(dataset_id=dataset.id, examples=create_payloads)
    if update_payloads:
        client.update_examples(dataset_id=dataset.id, updates=update_payloads)


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
    desc = (
        "Qwen3.5 plotting baseline before LoRA fine-tuning. "
        f"model={args.model}, file={result_file.name}"
    )
    dataset = _ensure_dataset(client, args.dataset_name, desc)
    _upsert_examples(client, dataset, rows)
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

    project_id = str(getattr(project, "id", "") or "")

    # 逐样本上传：每个 case 一个顶层 run，绑定到 dataset example。
    # 这样 LangSmith Experiments 页面才能按 case 展示 baseline。
    for idx, row in enumerate(rows):
        sid = str((row or {}).get("id", "")).strip()
        if not sid:
            sid = f"row-{idx}"
        err = str((row or {}).get("error", "") or "").strip()
        has_plot = bool((row or {}).get("has_plot", False))
        exec_ok = 1.0 if err == "" else 0.0
        plot_ok = 1.0 if has_plot else 0.0
        both_ok = 1.0 if (exec_ok > 0 and plot_ok > 0) else 0.0
        generated_code = str(
            (row or {}).get("code", "") or (row or {}).get("code_plot", "") or ""
        )
        start_time = now + timedelta(milliseconds=idx + 1)
        end_time = start_time + timedelta(milliseconds=1)
        sample_run_id = _stable_run_id(actual_name, sid)
        client.create_run(
            id=sample_run_id,
            project_name=actual_name,
            name=f"case-{sid}",
            run_type="chain",
            reference_example_id=_stable_example_id(sid),
            inputs={
                "id": sid,
                "sample_id": sid,
                "task_plot_description": str(
                    (row or {}).get("task__plot_description", "") or ""
                ),
                "task_plot_style": str((row or {}).get("task__plot_style", "") or ""),
                "task": str((row or {}).get("task", "") or ""),
            },
            outputs={
                "error": err,
                "has_plot": has_plot,
                "exec_ok": bool(exec_ok),
                "plot_ok": bool(plot_ok),
                "both_ok": bool(both_ok),
                "generated_code": generated_code,
                "raw_response": (row or {}).get("raw_response"),
                "time_used_gen": (row or {}).get("time_used_gen"),
            },
            start_time=start_time,
            end_time=end_time,
            error=err or None,
            extra={
                "metadata": {
                    "sample_id": sid,
                    "trace_type": "case_run",
                    "langsmith_mode": "writeback",
                }
            },
        )
        client.create_feedback(
            run_id=sample_run_id,
            key="exec_ok",
            score=exec_ok,
            comment=f"error={err}" if err else "execution passed",
            feedback_id=_stable_feedback_id(project_id, sample_run_id, "exec_ok"),
            source_info={"sample_id": sid, "mode": "local_score_writeback"},
        )
        client.create_feedback(
            run_id=sample_run_id,
            key="plot_ok",
            score=plot_ok,
            comment=f"has_plot={has_plot}",
            feedback_id=_stable_feedback_id(project_id, sample_run_id, "plot_ok"),
            source_info={"sample_id": sid, "mode": "local_score_writeback"},
        )
        client.create_feedback(
            run_id=sample_run_id,
            key="both_ok",
            score=both_ok,
            comment=f"exec_ok={bool(exec_ok)} has_plot={has_plot}",
            feedback_id=_stable_feedback_id(project_id, sample_run_id, "both_ok"),
            source_info={"sample_id": sid, "mode": "local_score_writeback"},
        )
        score_codebert = (row or {}).get("score_codebert")
        if isinstance(score_codebert, (int, float)):
            client.create_feedback(
                run_id=sample_run_id,
                key="score_codebert",
                score=float(score_codebert),
                comment="code similarity score",
                feedback_id=_stable_feedback_id(project_id, sample_run_id, "score_codebert"),
                source_info={"sample_id": sid, "mode": "local_score_writeback"},
            )
        score_vis = (row or {}).get("score_vis")
        if isinstance(score_vis, (int, float)):
            client.create_feedback(
                run_id=sample_run_id,
                key="score_vis",
                score=float(score_vis),
                comment="visual similarity score",
                feedback_id=_stable_feedback_id(project_id, sample_run_id, "score_vis"),
                source_info={"sample_id": sid, "mode": "local_score_writeback"},
            )
        score_task = (row or {}).get("score_task")
        if isinstance(score_task, (int, float)):
            client.create_feedback(
                run_id=sample_run_id,
                key="score_task",
                score=float(score_task),
                comment="task alignment score",
                feedback_id=_stable_feedback_id(project_id, sample_run_id, "score_task"),
                source_info={"sample_id": sid, "mode": "local_score_writeback"},
            )

    return {
        "dataset_name": dataset.name,
        "dataset_id": str(dataset.id),
        "experiment_name": actual_name,
        "experiment_url": _build_compare_url(project, str(dataset.id)),
        "project_url": str(getattr(project, "url", "") or ""),
        "trace_root_run_id": trace_root_run_id,
        "case_run_count": len(rows),
    }


def main() -> int:
    _load_env_files()
    args = _parse_args()

    mode = str(args.mode)
    run_generation = mode in {"all", "generate"} and (not args.skip_eval)
    run_visual = mode == "visual"
    # 默认评测应包含代码相似度；只有视觉相似度需要手工指定 visual 模式。
    run_codebert = bool(args.enable_codebert) and mode in {"all", "generate"}

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
