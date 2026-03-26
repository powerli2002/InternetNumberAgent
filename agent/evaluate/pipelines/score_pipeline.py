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
from agent.evaluate.core.config import (
    DIMENSION_WEIGHTS,
    EVAL_TOOL_DEFINITIONS,
    TOOL_SUBSCORE_WEIGHTS,
)
from agent.evaluate.core.grader_prompts import (
    LAST_MESSAGE_QUALITY_TEMPLATE,
    OUTCOME_CONSISTENCY_TEMPLATE,
)
from agent.evaluate.integrations.langsmith_bridge import (
    run_langsmith_experiment,
    write_local_scores_to_langsmith_experiment,
)
from agent.evaluate.core.schemas import (
    AnswerSample,
    GraderScore01Callback,
    ScoredSample,
    load_answer_samples,
    write_jsonl,
)
from agent.evaluate.core.trace_extract import rebuild_trace_artifacts


DIMENSIONS: Tuple[str, ...] = tuple(DIMENSION_WEIGHTS.keys())
TOOL_SUBSCORE_KEYS: Tuple[str, ...] = tuple(TOOL_SUBSCORE_WEIGHTS.keys())


class ToolSelectionAccuracyGrader:
    """基于期望工具与实际工具集合，计算工具选择准确率。"""

    name = "tool_selection_accuracy"

    def copy(self) -> "ToolSelectionAccuracyGrader":
        """与 OpenJudge grader 接口保持一致，供 GradingRunner 复制实例。"""
        return ToolSelectionAccuracyGrader()

    @staticmethod
    def _tool_name_set(tool_calls: List[Dict[str, Any]]) -> set[str]:
        names = set()
        for item in tool_calls:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("tool") or "").strip().lower()
            if name and name != "none":
                names.add(name)
        return names

    async def aevaluate(
        self,
        tool_calls: List[Dict[str, Any]],
        reference_tool_calls: List[Dict[str, Any]],
        expected_tools: List[str] | None = None,
        executor: Any | None = None,
    ):
        """按工具集合 F1 计算选择质量。"""
        from openjudge.graders.schema import GraderScore

        actual = self._tool_name_set(tool_calls if isinstance(tool_calls, list) else [])
        expected = self._tool_name_set(
            reference_tool_calls if isinstance(reference_tool_calls, list) else []
        )
        if not expected:
            expected = {
                str(item).strip().lower()
                for item in (expected_tools or [])
                if str(item).strip()
            }

        if not expected and not actual:
            score = 1.0
            reason = "题目无需工具，实际也未调用工具。"
        elif not expected:
            score = 0.0
            reason = f"题目未要求工具，但实际调用了 {sorted(actual)}。"
        else:
            matched = actual & expected
            precision = len(matched) / len(actual) if actual else 0.0
            recall = len(matched) / len(expected) if expected else 1.0
            if precision + recall <= 0:
                score = 0.0
            else:
                score = 2 * precision * recall / (precision + recall)
            reason = (
                f"expected={sorted(expected)} actual={sorted(actual)} matched={sorted(matched)} "
                f"precision={precision:.3f} recall={recall:.3f} f1={score:.3f}"
            )

        return GraderScore(name=self.name, score=_clamp_01(score), reason=reason)


def _clamp_01(value: float) -> float:
    """把分数裁剪到 0~1。"""
    return max(0.0, min(1.0, float(value)))


def compute_tool_use_accuracy(scores_raw: Dict[str, float]) -> float:
    """把三个工具子评分聚合为 tool_use_accuracy。"""
    if all(key in scores_raw for key in TOOL_SUBSCORE_KEYS):
        return _clamp_01(
            sum(
                TOOL_SUBSCORE_WEIGHTS[key] * _clamp_01(float(scores_raw.get(key, 0.0)))
                for key in TOOL_SUBSCORE_KEYS
            )
        )
    return _clamp_01(float(scores_raw.get("tool_use_accuracy", 0.0)))


def _build_tool_use_accuracy_reason(scores_raw: Dict[str, float]) -> str:
    """输出 tool_use_accuracy 的聚合说明。"""
    parts = [
        f"{key}={_clamp_01(float(scores_raw.get(key, 0.0))):.3f}*{TOOL_SUBSCORE_WEIGHTS[key]:.2f}"
        for key in TOOL_SUBSCORE_KEYS
    ]
    return (
        f"聚合得分={' + '.join(parts)} => {compute_tool_use_accuracy(scores_raw):.3f}"
    )


def _extract_score_and_reason(result: Any) -> Tuple[float, str]:
    """从 OpenJudge 结果对象提取分数与原因。"""
    if result is None:
        return 0.0, "result is None"
    score = getattr(result, "score", None)
    if score is None:
        return 0.0, f"unsupported result type: {type(result)}"
    raw_score = float(score)
    bounded_score = _clamp_01(raw_score)
    reason = str(getattr(result, "reason", "") or "")
    if abs(raw_score - bounded_score) > 1e-9:
        clamp_note = (
            f"原始分={raw_score:.6f} 超出 0~1 范围，已裁剪为 {bounded_score:.6f}。"
        )
        reason = f"{reason} {clamp_note}".strip() if reason else clamp_note
    return bounded_score, reason


def compute_dimension_scores(
    scores_raw: Dict[str, float],
) -> Tuple[Dict[str, float], float]:
    """按约定公式计算四维分与总分。"""
    scores_dim: Dict[str, float] = {}
    for dim in DIMENSIONS:
        if dim == "tool_use_accuracy":
            scores_dim[dim] = compute_tool_use_accuracy(scores_raw)
            continue
        scores_dim[dim] = _clamp_01(float(scores_raw.get(dim, 0.0)))

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
    from openjudge.graders.agent.tool.tool_parameter_check import (
        ToolParameterCheckGrader,
    )
    from openjudge.graders.agent.trajectory.trajectory_comprehensive import (
        TrajectoryComprehensiveGrader,
    )
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
        # 工具选择：按期望工具集合与实际工具集合的 F1 计算，避免把重复调用次数误记为选择错误。
        "tool_selection_accuracy": (
            ToolSelectionAccuracyGrader(),
            {
                "tool_calls": "tool_calls",
                "reference_tool_calls": "expected_tool_calls",
                "expected_tools": "expected_tools",
            },
        ),
        # 工具参数：基于 query + tool_definitions + tool_calls 做参数完整性与正确性检查。
        "tool_argument_quality": (
            ToolParameterCheckGrader(model=model, language=LanguageEnum.ZH),
            {
                "query": "query",
                "tool_definitions": "tool_definitions",
                "tool_calls": "tool_calls",
            },
        ),
        # 工具结果有效性：让评测器从完整轨迹判断每一步工具调用是否真正推动了解题。
        "tool_outcome_effectiveness": (
            TrajectoryComprehensiveGrader(
                model=model,
                language=LanguageEnum.ZH,
                resolution_threshold=0.8,
            ),
            {
                "messages": "trajectory_messages",
                "query": "query",
                "response": "answer",
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
                structured_model=GraderScore01Callback,
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
                structured_model=GraderScore01Callback,
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
        "tool_execution_records": sample.tool_execution_records,
        "tool_calls": sample.tool_calls,
        "tool_definitions": EVAL_TOOL_DEFINITIONS,
        "expected_tool_calls": sample.expected_tool_calls,
        "expected_tools": sample.expected_tools,
        "reference_answer": sample.reference_answer,
        "evidence_summary": sample.evidence_summary,
    }


def rebuild_answer_samples_for_posthoc_tool_rescore(
    answer_samples: List[AnswerSample],
) -> List[AnswerSample]:
    """基于已保存 trace 字段重建工具评分输入，供后补重评分复用。"""
    rebuilt_samples: List[AnswerSample] = []
    for sample in answer_samples:
        if sample.status != "ok":
            rebuilt_samples.append(sample)
            continue

        rebuilt_artifacts = rebuild_trace_artifacts(
            query=sample.query,
            answer=sample.answer,
            node_records=sample.node_records,
            final_state_output=sample.final_state_output,
            main_flow_trace=sample.main_flow_trace,
        )
        payload = sample.to_dict()
        payload.update(rebuilt_artifacts)
        rebuilt_samples.append(AnswerSample.from_dict(payload))
    return rebuilt_samples


def _write_manual_review_csv(
    path: Path, scored_samples: List[ScoredSample], source_map: Dict[str, AnswerSample]
) -> None:
    """输出人工复核模板。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fw:
        writer = csv.writer(fw)
        writer.writerow(
            [
                "id",
                "status",
                "overall_score",
                *TOOL_SUBSCORE_KEYS,
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
                    *[
                        f"{_clamp_01(float(sample.scores_raw.get(dim, 0.0))):.6f}"
                        for dim in TOOL_SUBSCORE_KEYS
                    ],
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
    posthoc_tool_rescore: bool = False,
    posthoc_answers_out_path: Path | None = None,
    langsmith_mode: str = "writeback",
) -> Dict[str, Any]:
    """执行评分主流程。

    - 从 AnswerSample 列表出发，调用 OpenJudge 执行多维自动评分
    - 将打分结果写入 JSONL，并生成整体统计与人工复核 CSV 模板
    """
    from openjudge.runner.grading_runner import GradingRunner

    if not answer_samples:
        raise RuntimeError("answer_samples 为空")

    scoring_samples = list(answer_samples)
    if posthoc_tool_rescore:
        scoring_samples = rebuild_answer_samples_for_posthoc_tool_rescore(
            scoring_samples
        )
        if posthoc_answers_out_path is not None:
            posthoc_answers_out_path.parent.mkdir(parents=True, exist_ok=True)
            write_jsonl(
                posthoc_answers_out_path,
                [sample.to_dict() for sample in scoring_samples],
            )

    # 读取评分准则 rubrics，并构建各个维度的 grader 配置（模型、模板与字段映射）
    rubrics_payload = _load_rubrics(rubrics_path)
    grader_configs = _build_grader_configs(
        rubrics_payload=rubrics_payload, model_name=model_name
    )

    # 只对 status=="ok" 的样本进行自动评分，失败样本单独按 0 分处理
    ok_samples = [sample for sample in scoring_samples if sample.status == "ok"]
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

    for sample in scoring_samples:
        if sample.status != "ok":
            # 对于错误样本，所有维度赋 0 分，并记录错误原因，便于后续人工排查
            zero_scores = {
                **{dim: 0.0 for dim in DIMENSIONS},
                **{dim: 0.0 for dim in TOOL_SUBSCORE_KEYS},
            }
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
        score_reasons["tool_use_accuracy"] = _build_tool_use_accuracy_reason(scores_raw)
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
    avg_overall = (
        mean([item.overall_score for item in scored_samples]) if scored_samples else 0.0
    )
    dim_avg = {
        key: (
            mean([item.scores_dim.get(key, 0.0) for item in scored_samples])
            if scored_samples
            else 0.0
        )
        for key in DIMENSIONS
    }
    tool_subscore_avg = {
        key: (
            mean(
                [
                    _clamp_01(float(item.scores_raw.get(key, 0.0)))
                    for item in scored_samples
                ]
            )
            if scored_samples
            else 0.0
        )
        for key in TOOL_SUBSCORE_KEYS
    }

    summary_payload: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": total,
        "ok_count": ok_count,
        "error_count": total - ok_count,
        "avg_overall": avg_overall,
        "avg_dim": dim_avg,
        "avg_tool_subscores": tool_subscore_avg,
        "weights": DIMENSION_WEIGHTS,
        "tool_subscore_weights": TOOL_SUBSCORE_WEIGHTS,
        "rubrics_path": str(rubrics_path),
        # 这里不直接展开 rubrics 内容，避免 summary 体积过大，只保留路径和打分权重
    }
    summary_payload["langsmith_mode"] = str(langsmith_mode)
    summary_payload["posthoc_tool_rescore"] = bool(posthoc_tool_rescore)
    if posthoc_answers_out_path is not None:
        summary_payload["posthoc_answers_out_path"] = str(posthoc_answers_out_path)

    if push_langsmith:
        # 可选：将本次评测结果推送到 LangSmith，支持远端 evaluator 或本地分数直写两种模式。
        if langsmith_mode == "evaluate":
            langsmith_info = run_langsmith_experiment(
                samples=scoring_samples,
                grader_configs=list(grader_configs.values()),
                dataset_name=dataset_name,
                experiment_prefix=experiment_prefix,
                description="FusionAgent OpenJudge 评测实验",
            )
        elif langsmith_mode == "writeback":
            langsmith_info = write_local_scores_to_langsmith_experiment(
                samples=scoring_samples,
                scored_samples=scored_samples,
                dataset_name=dataset_name,
                experiment_prefix=experiment_prefix,
                description="FusionAgent OpenJudge 本地评分写回实验",
            )
        else:
            raise RuntimeError(f"未知 langsmith_mode: {langsmith_mode}")
        summary_payload["langsmith"] = langsmith_info

    # 写出汇总 JSON（包含统计信息与可选的 LangSmith 元数据）
    summary_out_path.parent.mkdir(parents=True, exist_ok=True)
    summary_out_path.write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 生成人工复核 CSV，方便标注者对关键样本进行人工打分与评论
    source_map = {sample.id: sample for sample in scoring_samples}
    _write_manual_review_csv(manual_review_csv_path, scored_samples, source_map)

    return summary_payload


def build_arg_parser() -> argparse.ArgumentParser:
    """构建命令行参数。"""
    parser = argparse.ArgumentParser(description="执行 OpenJudge 多维评分")
    parser.add_argument(
        "--in", dest="in_path", required=True, help="answers.jsonl 输入路径"
    )
    parser.add_argument("--rubrics", required=True, help="rubrics.json 路径")
    parser.add_argument(
        "--out", dest="out_path", required=True, help="scored.jsonl 输出路径"
    )
    parser.add_argument(
        "--summary-out", required=True, help="score_summary.json 输出路径"
    )
    parser.add_argument(
        "--manual-review-out", required=True, help="manual_review.csv 输出路径"
    )
    parser.add_argument(
        "--push-langsmith", action="store_true", help="是否推送 LangSmith experiment"
    )
    parser.add_argument(
        "--langsmith-mode",
        default="writeback",
        choices=["writeback", "evaluate"],
        help="LangSmith 推送模式：writeback=直写本地分数，evaluate=在 LangSmith 中再次执行 grader",
    )
    parser.add_argument(
        "--dataset-name", default="fusion-openjudge-eval", help="LangSmith dataset 名称"
    )
    parser.add_argument(
        "--experiment-prefix",
        default="fusion-openjudge",
        help="LangSmith experiment 前缀",
    )
    parser.add_argument("--model", default="", help="可选覆盖评分模型名")
    parser.add_argument(
        "--posthoc-tool-rescore",
        action="store_true",
        help="基于已保存 trace 重建 tool 评分输入后再重新评分",
    )
    parser.add_argument(
        "--posthoc-answers-out",
        default="",
        help="可选：输出重建后的 answers.jsonl，便于后补落盘",
    )
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
        posthoc_tool_rescore=bool(args.posthoc_tool_rescore),
        posthoc_answers_out_path=(
            Path(args.posthoc_answers_out).resolve()
            if args.posthoc_answers_out
            else None
        ),
        langsmith_mode=str(args.langsmith_mode),
    )
    print(
        f"[score_pipeline] 完成: total={summary['total']} avg_overall={summary['avg_overall']:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
