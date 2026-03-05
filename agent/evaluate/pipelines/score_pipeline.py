"""阶段 D：执行多维评分并输出结果。"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Tuple

from agent.core.config import AgentConfig
from agent.evaluate.pipelines.build_graders import build_openjudge_model
from agent.evaluate.core.config import DIMENSION_WEIGHTS
from agent.evaluate.core.grader_prompts import LAST_MESSAGE_QUALITY_TEMPLATE, OUTCOME_CONSISTENCY_TEMPLATE
from agent.evaluate.integrations.langsmith_bridge import run_langsmith_experiment
from agent.evaluate.core.schemas import AnswerSample, ScoredSample, load_answer_samples, write_jsonl


DIMENSIONS: Tuple[str, ...] = tuple(DIMENSION_WEIGHTS.keys())


def _clamp_01(value: float) -> float:
    """把分数裁剪到 0~1。"""
    return max(0.0, min(1.0, float(value)))


def _extract_score_and_reason(result: Any) -> Tuple[float, str]:
    """从 OpenJudge 结果对象提取分数与原因。"""
    if result is None:
        return 0.0, "result is None"
    score = getattr(result, "score", None)
    if score is None:
        return 0.0, f"unsupported result type: {type(result)}"
    reason = str(getattr(result, "reason", "") or "")
    return float(score), reason


def compute_dimension_scores(scores_raw: Dict[str, float]) -> Tuple[Dict[str, float], float]:
    """按约定公式计算四维分与总分。"""
    scores_dim = {dim: _clamp_01(float(scores_raw.get(dim, 0.0))) for dim in DIMENSIONS}

    overall = sum(DIMENSION_WEIGHTS[dim] * scores_dim[dim] for dim in DIMENSIONS)
    return scores_dim, _clamp_01(overall)


def _load_rubrics(path: Path) -> Dict[str, Any]:
    """读取 rubrics.json。"""
    if not path.exists():
        raise FileNotFoundError(f"rubrics 文件不存在: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("rubrics.json 必须是对象")
    return payload


def _build_grader_configs(rubrics_payload: Dict[str, Any], model_name: str = ""):
    """构建 OpenJudge grader 配置。"""
    from openjudge.graders.agent.plan.plan_feasibility import PlanFeasibilityGrader
    from openjudge.graders.agent.tool.tool_call_precision_recall_match import ToolCallPrecisionRecallMatchGrader
    from openjudge.graders.llm_grader import LLMGrader
    from openjudge.graders.schema import GraderMode
    from openjudge.models.schema.prompt_template import LanguageEnum

    cfg = AgentConfig.load()
    model = build_openjudge_model(cfg, model_name=model_name)

    rubrics_text = str(rubrics_payload.get("last_message_rubrics") or "").strip()
    if not rubrics_text:
        raise RuntimeError("rubrics.json 缺少 last_message_rubrics")

    grader_configs = {
        # 推理规划：直接评估计划可行性，避免与轨迹维度重复计分。
        "reasoning_planning": (
            PlanFeasibilityGrader(model=model, language=LanguageEnum.ZH),
            {
                "plan": "plan_text",
                "observation": "observation_text",
                "memory": "memory_text",
            },
        ),
        # 工具使用：基于参考工具调用计算 recall，衡量关键工具是否被覆盖执行。
        "tool_use_accuracy": (
            ToolCallPrecisionRecallMatchGrader(metric_type="recall", match_arguments=False),
            {
                "tool_calls": "tool_calls",
                "reference_tool_calls": "expected_tool_calls",
            },
        ),
        "final_response_quality": (
            LLMGrader(
                name="final_response_quality",
                mode=GraderMode.POINTWISE,
                model=model,
                template=LAST_MESSAGE_QUALITY_TEMPLATE,
                language=LanguageEnum.ZH,
                rubrics_text=rubrics_text,
            ),
            {
                "query": "query",
                "response": "answer",
                "evidence_summary": "evidence_summary",
            },
        ),
        "evidence_groundedness": (
            LLMGrader(
                name="evidence_groundedness",
                mode=GraderMode.POINTWISE,
                model=model,
                template=OUTCOME_CONSISTENCY_TEMPLATE,
                language=LanguageEnum.ZH,
            ),
            {
                "query": "query",
                "response": "answer",
                "reference_response": "reference_answer",
                "evidence_summary": "evidence_summary",
            },
        ),
    }
    return grader_configs


def _to_dataset_row(sample: AnswerSample) -> Dict[str, Any]:
    """把 AnswerSample 转换为 GradingRunner 输入。"""
    return {
        "id": sample.id,
        "query": sample.query,
        "answer": sample.answer,
        "status": sample.status,
        "error": sample.error,
        "plan_text": sample.plan_text,
        "observation_text": sample.observation_text,
        "memory_text": sample.memory_text,
        "evidence_items": sample.evidence_items,
        "trajectory_messages": sample.trajectory_messages,
        "tool_calls": sample.tool_calls,
        "expected_tool_calls": sample.expected_tool_calls,
        "expected_tools": sample.expected_tools,
        "reference_answer": sample.reference_answer,
        "evidence_summary": sample.evidence_summary,
    }


def _write_manual_review_csv(path: Path, scored_samples: List[ScoredSample], source_map: Dict[str, AnswerSample]) -> None:
    """输出人工复核模板。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fw:
        writer = csv.writer(fw)
        writer.writerow(
            [
                "id",
                "status",
                "overall_score",
                *DIMENSIONS,
                "query",
                "answer",
                "reference_answer",
                "human_score",
                "human_comment",
            ]
        )
        for sample in scored_samples:
            source = source_map[sample.id]
            writer.writerow(
                [
                    sample.id,
                    sample.status,
                    f"{sample.overall_score:.6f}",
                    *[f"{sample.scores_dim.get(dim, 0.0):.6f}" for dim in DIMENSIONS],
                    source.query,
                    source.answer,
                    source.reference_answer,
                    "",
                    "",
                ]
            )


def run_scoring(
    answer_samples: List[AnswerSample],
    rubrics_path: Path,
    scored_out_path: Path,
    summary_out_path: Path,
    manual_review_csv_path: Path,
    push_langsmith: bool = False,
    dataset_name: str = "fusion-openjudge-eval",
    experiment_prefix: str = "fusion-openjudge",
    model_name: str = "",
) -> Dict[str, Any]:
    """执行评分主流程。

    - 从 AnswerSample 列表出发，调用 OpenJudge 执行多维自动评分
    - 将打分结果写入 JSONL，并生成整体统计与人工复核 CSV 模板
    """
    from openjudge.runner.grading_runner import GradingRunner

    if not answer_samples:
        raise RuntimeError("answer_samples 为空")

    # 读取评分准则 rubrics，并构建各个维度的 grader 配置（模型、模板与字段映射）
    rubrics_payload = _load_rubrics(rubrics_path)
    grader_configs = _build_grader_configs(rubrics_payload=rubrics_payload, model_name=model_name)

    # 只对 status=="ok" 的样本进行自动评分，失败样本单独按 0 分处理
    ok_samples = [sample for sample in answer_samples if sample.status == "ok"]
    # 将样本转成 GradingRunner 所需的字典结构
    ok_rows = [_to_dataset_row(sample) for sample in ok_samples]

    # 预先为每个 grader 准备结果列表占位，保持键空间一致
    grader_results: Dict[str, List[Any]] = {name: [] for name in grader_configs}
    if ok_rows:
        # 使用 OpenJudge 的 GradingRunner 并发执行评分
        runner = GradingRunner(grader_configs=grader_configs, max_concurrency=8)
        grader_results = asyncio.run(runner.arun(ok_rows))

    # 汇总后的打分样本列表
    scored_samples: List[ScoredSample] = []
    # 为了从 grader_results 中按 id 找到对应结果，先建立 ok 样本的索引映射
    ok_index = {sample.id: idx for idx, sample in enumerate(ok_samples)}

    for sample in answer_samples:
        if sample.status != "ok":
            # 对于错误样本，所有维度赋 0 分，并记录错误原因，便于后续人工排查
            zero_scores = {dim: 0.0 for dim in DIMENSIONS}
            dims, overall = compute_dimension_scores(zero_scores)
            scored_samples.append(
                ScoredSample(
                    id=sample.id,
                    query=sample.query,
                    answer=sample.answer,
                    status="error",
                    error=sample.error,
                    scores_raw=zero_scores,
                    scores_dim=dims,
                    overall_score=overall,
                    score_reasons={"pipeline": f"sample status=error: {sample.error}"},
                )
            )
            continue

        # 定位该样本在 ok_rows 中的下标，用于从每个 grader 的结果列表中取出对应结果
        idx = ok_index[sample.id]
        scores_raw: Dict[str, float] = {}
        score_reasons: Dict[str, str] = {}
        for grader_name, result_list in grader_results.items():
            # 某些 grader 可能没有返回完整结果，这里做边界保护
            result_obj = result_list[idx] if idx < len(result_list) else None
            score, reason = _extract_score_and_reason(result_obj)
            # 每个 grader 输出一个 0~1 的原始分和对应的解释/理由
            scores_raw[grader_name] = score
            score_reasons[grader_name] = reason

        # 将原始多维分数转换为 DIMENSIONS 维度分及加权总分
        dims, overall = compute_dimension_scores(scores_raw)
        scored_samples.append(
            ScoredSample(
                id=sample.id,
                query=sample.query,
                answer=sample.answer,
                status="ok",
                scores_raw=scores_raw,
                scores_dim=dims,
                overall_score=overall,
                score_reasons=score_reasons,
            )
        )

    # 写出逐样本的详细打分结果，供后续分析或追踪
    write_jsonl(scored_out_path, [sample.to_dict() for sample in scored_samples])

    # 汇总统计：样本数、通过数、平均总分与各维度平均分
    total = len(scored_samples)
    ok_count = sum(1 for item in scored_samples if item.status == "ok")
    avg_overall = mean([item.overall_score for item in scored_samples]) if scored_samples else 0.0
    dim_avg = {
        key: (mean([item.scores_dim.get(key, 0.0) for item in scored_samples]) if scored_samples else 0.0)
        for key in DIMENSIONS
    }

    summary_payload: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": total,
        "ok_count": ok_count,
        "error_count": total - ok_count,
        "avg_overall": avg_overall,
        "avg_dim": dim_avg,
        "weights": DIMENSION_WEIGHTS,
        "rubrics_path": str(rubrics_path),
        # 这里不直接展开 rubrics 内容，避免 summary 体积过大，只保留路径和打分权重
    }

    if push_langsmith:
        # 可选：将本次评测结果推送到 LangSmith，便于可视化与历史对比
        langsmith_info = run_langsmith_experiment(
            samples=answer_samples,
            grader_configs=list(grader_configs.values()),
            dataset_name=dataset_name,
            experiment_prefix=experiment_prefix,
            description="FusionAgent OpenJudge 评测实验",
        )
        summary_payload["langsmith"] = langsmith_info

    # 写出汇总 JSON（包含统计信息与可选的 LangSmith 元数据）
    summary_out_path.parent.mkdir(parents=True, exist_ok=True)
    summary_out_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 生成人工复核 CSV，方便标注者对关键样本进行人工打分与评论
    source_map = {sample.id: sample for sample in answer_samples}
    _write_manual_review_csv(manual_review_csv_path, scored_samples, source_map)

    return summary_payload


def build_arg_parser() -> argparse.ArgumentParser:
    """构建命令行参数。"""
    parser = argparse.ArgumentParser(description="执行 OpenJudge 多维评分")
    parser.add_argument("--in", dest="in_path", required=True, help="answers.jsonl 输入路径")
    parser.add_argument("--rubrics", required=True, help="rubrics.json 路径")
    parser.add_argument("--out", dest="out_path", required=True, help="scored.jsonl 输出路径")
    parser.add_argument("--summary-out", required=True, help="score_summary.json 输出路径")
    parser.add_argument("--manual-review-out", required=True, help="manual_review.csv 输出路径")
    parser.add_argument("--push-langsmith", action="store_true", help="是否推送 LangSmith experiment")
    parser.add_argument("--dataset-name", default="fusion-openjudge-eval", help="LangSmith dataset 名称")
    parser.add_argument("--experiment-prefix", default="fusion-openjudge", help="LangSmith experiment 前缀")
    parser.add_argument("--model", default="", help="可选覆盖评分模型名")
    return parser


def main() -> int:
    """脚本入口。"""
    args = build_arg_parser().parse_args()

    samples = load_answer_samples(Path(args.in_path).resolve())
    summary = run_scoring(
        answer_samples=samples,
        rubrics_path=Path(args.rubrics).resolve(),
        scored_out_path=Path(args.out_path).resolve(),
        summary_out_path=Path(args.summary_out).resolve(),
        manual_review_csv_path=Path(args.manual_review_out).resolve(),
        push_langsmith=bool(args.push_langsmith),
        dataset_name=str(args.dataset_name),
        experiment_prefix=str(args.experiment_prefix),
        model_name=str(args.model or "").strip(),
    )
    print(f"[score_pipeline] 完成: total={summary['total']} avg_overall={summary['avg_overall']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
