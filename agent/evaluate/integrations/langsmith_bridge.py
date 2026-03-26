"""LangSmith Dataset 与 Experiment 桥接。"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Tuple

from langsmith import Client
from langsmith.evaluation import evaluate

from agent.evaluate.core.config import EVAL_TOOL_DEFINITIONS
from agent.evaluate.core.schemas import AnswerSample, ScoredSample


def _clamp_01(value: Any) -> float:
    """把反馈分数裁剪到 0~1，避免异常 grader 输出污染展示层。"""
    return max(0.0, min(1.0, float(value)))


def _clamp_score_map(scores: Dict[str, Any] | None) -> Dict[str, float]:
    """按评分契约统一裁剪 score map。"""
    return {str(key): _clamp_01(value) for key, value in dict(scores or {}).items()}


def _stable_example_id(sample_id: str) -> str:
    """为样本生成稳定 UUID，便于 upsert。"""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"fusion-eval:{sample_id}"))


def _stable_run_id(experiment_name: str, sample_id: str) -> str:
    """为实验内单样本 run 生成稳定 UUID。"""
    return str(
        uuid.uuid5(uuid.NAMESPACE_DNS, f"fusion-eval-run:{experiment_name}:{sample_id}")
    )


def _stable_feedback_id(project_id: str, run_id: str, key: str) -> str:
    """为单条 feedback 生成稳定 UUID。"""
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_DNS, f"fusion-eval-feedback:{project_id}:{run_id}:{key}"
        )
    )


def _build_compare_url(project: Any, dataset_id: str) -> str:
    """构造 LangSmith compare URL，便于 CLI 直接输出点击链接。"""
    project_url = str(getattr(project, "url", "") or "").strip()
    project_id = str(getattr(project, "id", "") or "").strip()
    if not project_url or not dataset_id or not project_id:
        return ""
    base_url = project_url.split("/projects/p/")[0]
    return f"{base_url}/datasets/{dataset_id}/compare?selectedSessions={project_id}"


def _build_run_outputs(
    sample: AnswerSample, scored_sample: ScoredSample
) -> Dict[str, Any]:
    """构造 LangSmith run outputs，直接展示本地评测分数与证据。"""
    scores_raw = _clamp_score_map(scored_sample.scores_raw)
    scores_dim = _clamp_score_map(scored_sample.scores_dim)
    return {
        "id": sample.id,
        "query": sample.query,
        "answer": sample.answer,
        "status": sample.status,
        "error": sample.error,
        "tool_execution_records": sample.tool_execution_records,
        "tool_calls": sample.tool_calls,
        "trajectory_messages": sample.trajectory_messages,
        "plan_text": sample.plan_text,
        "observation_text": sample.observation_text,
        "memory_text": sample.memory_text,
        "evidence_items": sample.evidence_items,
        "evidence_summary": sample.evidence_summary,
        "scores_raw": scores_raw,
        "scores_dim": scores_dim,
        "overall_score": _clamp_01(scored_sample.overall_score),
        "score_reasons": scored_sample.score_reasons,
    }


def _build_feedback_payloads(scored_sample: ScoredSample) -> List[Dict[str, Any]]:
    """把本地打分结果展开为 LangSmith feedback 条目。"""
    scores_dim = _clamp_score_map(scored_sample.scores_dim)
    scores_raw = _clamp_score_map(scored_sample.scores_raw)
    feedbacks: List[Dict[str, Any]] = [
        {
            "key": "overall_score",
            "score": _clamp_01(scored_sample.overall_score),
            "comment": json.dumps(scores_dim, ensure_ascii=False, sort_keys=True),
        }
    ]
    for key, value in sorted(scores_dim.items()):
        feedbacks.append(
            {
                "key": key,
                "score": _clamp_01(value),
                "comment": str((scored_sample.score_reasons or {}).get(key, "") or ""),
            }
        )
    for key, value in sorted(scores_raw.items()):
        if key in scores_dim:
            continue
        feedbacks.append(
            {
                "key": key,
                "score": _clamp_01(value),
                "comment": str((scored_sample.score_reasons or {}).get(key, "") or ""),
            }
        )
    return feedbacks


def ensure_dataset(client: Client, dataset_name: str, description: str = "") -> Any:
    """读取或创建 Dataset。"""
    try:
        return client.read_dataset(dataset_name=dataset_name)
    except Exception:
        return client.create_dataset(
            dataset_name=dataset_name, description=description or None
        )


def upsert_examples(
    client: Client,
    dataset_name: str,
    samples: Iterable[AnswerSample],
    description: str = "",
) -> Any:
    """按稳定 id 写入/更新样本到 Dataset。"""
    dataset = ensure_dataset(
        client=client, dataset_name=dataset_name, description=description
    )
    examples: List[Dict[str, Any]] = []
    for sample in samples:
        examples.append(
            {
                "id": _stable_example_id(sample.id),
                "inputs": {
                    "id": sample.id,
                    "query": sample.query,
                },
                "outputs": {
                    "reference_answer": sample.reference_answer,
                    "expected_tool_calls": sample.expected_tool_calls,
                    "expected_tools": sample.expected_tools,
                },
                "metadata": {
                    "sample_id": sample.id,
                    "status": sample.status,
                },
            }
        )
    if not examples:
        return dataset

    # 说明：
    # 1. 评测脚本要求可重复执行；
    # 2. LangSmith 的 create_examples 在 example_id 已存在时会直接返回 409；
    # 3. 因此这里先按稳定 id 查询已存在样本，再拆分为 create / update 两批，保证重复运行幂等。
    example_ids = [example["id"] for example in examples]
    existing_examples = list(
        client.list_examples(dataset_id=dataset.id, example_ids=example_ids)
    )
    existing_ids = {str(example.id) for example in existing_examples}

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
    return dataset


def build_cached_application(
    samples: Iterable[AnswerSample],
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """构建缓存应用，避免 evaluate 时重复调用 Agent。"""
    sample_map: Dict[str, AnswerSample] = {sample.id: sample for sample in samples}

    def _application(inputs: Dict[str, Any]) -> Dict[str, Any]:
        sample_id = str(inputs.get("id") or "").strip()
        if not sample_id:
            raise RuntimeError("LangSmith inputs.id 缺失")
        sample = sample_map.get(sample_id)
        if sample is None:
            raise RuntimeError(f"缓存中不存在样本 id={sample_id}")

        return {
            "id": sample.id,
            "query": sample.query,
            "answer": sample.answer,
            "status": sample.status,
            "error": sample.error,
            "tool_execution_records": sample.tool_execution_records,
            "tool_calls": sample.tool_calls,
            "trajectory_messages": sample.trajectory_messages,
            "plan_text": sample.plan_text,
            "observation_text": sample.observation_text,
            "memory_text": sample.memory_text,
            "evidence_items": sample.evidence_items,
            "evidence_summary": sample.evidence_summary,
            "expected_tools": sample.expected_tools,
            "expected_tool_calls": sample.expected_tool_calls,
            "reference_answer": sample.reference_answer,
            "tool_definitions": EVAL_TOOL_DEFINITIONS,
        }

    return _application


def create_langsmith_evaluator(
    grader: Any, mapper: Dict[str, str] | None = None
) -> Callable[[dict, dict, dict], dict]:
    """把 OpenJudge grader 包装成 LangSmith evaluator。"""
    from openjudge.graders.schema import (
        GraderError,
        GraderRank,
        GraderResult,
        GraderScore,
    )
    from openjudge.utils.mapping import parse_data_with_mapper

    def _evaluator(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
        if str((outputs or {}).get("status") or "").lower() == "error":
            return {
                "key": grader.name,
                "score": 0.0,
                "comment": "skip: sample status=error",
            }

        merged_payload: Dict[str, Any] = {}
        if isinstance(inputs, dict):
            merged_payload.update(inputs)
        if isinstance(reference_outputs, dict):
            merged_payload.update(reference_outputs)
        if isinstance(outputs, dict):
            merged_payload.update(outputs)

        data = {
            "inputs": inputs,
            "outputs": outputs,
            "reference_outputs": reference_outputs,
            **merged_payload,
        }
        mapped = parse_data_with_mapper(data, mapper)
        try:
            result: GraderResult = asyncio.run(grader.aevaluate(**mapped))
            if isinstance(result, GraderScore):
                return {
                    "key": grader.name,
                    "score": _clamp_01(result.score),
                    "comment": str(result.reason or ""),
                }
            if isinstance(result, GraderRank):
                rank_value = result.rank[0] if result.rank else 0
                return {
                    "key": grader.name,
                    "score": float(rank_value),
                    "comment": str(result.reason or ""),
                }
            if isinstance(result, GraderError):
                return {
                    "key": grader.name,
                    "score": 0.0,
                    "comment": f"error: {result.error}",
                }
            return {
                "key": grader.name,
                "score": 0.0,
                "comment": f"unsupported result type: {type(result)}",
            }
        except Exception as exc:
            return {
                "key": grader.name,
                "score": 0.0,
                "comment": f"evaluation failed: {exc}",
            }

    return _evaluator


def run_langsmith_experiment(
    samples: Iterable[AnswerSample],
    grader_configs: List[Tuple[Any, Dict[str, str] | None]],
    dataset_name: str,
    experiment_prefix: str,
    description: str,
    max_concurrency: int = 4,
) -> Dict[str, Any]:
    """写入 Dataset 并执行 LangSmith evaluate。"""
    samples_list = list(samples)
    if not samples_list:
        raise RuntimeError("samples 为空，无法推送 LangSmith")

    client = Client()
    dataset = upsert_examples(
        client=client,
        dataset_name=dataset_name,
        samples=samples_list,
        description=description,
    )

    evaluators = [
        create_langsmith_evaluator(grader=grader, mapper=mapper)
        for grader, mapper in grader_configs
    ]
    cached_app = build_cached_application(samples_list)

    experiment_results = evaluate(
        cached_app,
        data=dataset.name,
        evaluators=evaluators,
        experiment_prefix=experiment_prefix,
        description=description,
        max_concurrency=max(1, int(max_concurrency)),
    )
    experiment_results.wait()

    return {
        "dataset_name": dataset.name,
        "dataset_id": str(dataset.id),
        "experiment": str(getattr(experiment_results, "experiment_name", "")),
        "experiment_url": str(getattr(experiment_results, "url", "")),
        "mode": "evaluate",
    }


def write_local_scores_to_langsmith_experiment(
    samples: Iterable[AnswerSample],
    scored_samples: Iterable[ScoredSample],
    dataset_name: str,
    experiment_prefix: str,
    description: str,
) -> Dict[str, Any]:
    """把本地已算好的分数直接写回 LangSmith，避免重复调用 grader。"""
    sample_list = list(samples)
    scored_list = list(scored_samples)
    if not sample_list:
        raise RuntimeError("samples 为空，无法推送 LangSmith")
    scored_map = {sample.id: sample for sample in scored_list}
    missing_ids = [sample.id for sample in sample_list if sample.id not in scored_map]
    if missing_ids:
        raise RuntimeError(
            f"部分样本缺少 scored 结果，无法写回 LangSmith: {missing_ids[:5]}"
        )

    client = Client()
    dataset = upsert_examples(
        client=client,
        dataset_name=dataset_name,
        samples=sample_list,
        description=description,
    )

    experiment_name = f"{experiment_prefix}-{uuid.uuid4().hex[:8]}"
    project = client.create_project(
        project_name=experiment_name,
        description=description,
        metadata={
            "__ls_runner": "fusion_local_score_writeback",
            "source": "local_scores",
            "sample_count": len(sample_list),
        },
        reference_dataset_id=dataset.id,
    )

    now = datetime.now(timezone.utc)
    for index, sample in enumerate(sample_list):
        scored_sample = scored_map[sample.id]
        run_id = _stable_run_id(experiment_name, sample.id)
        start_time = now + timedelta(milliseconds=index)
        end_time = start_time + timedelta(milliseconds=1)
        client.create_run(
            id=run_id,
            project_name=experiment_name,
            name="fusion_cached_evaluation",
            run_type="chain",
            reference_example_id=_stable_example_id(sample.id),
            inputs={"id": sample.id, "query": sample.query},
            outputs=_build_run_outputs(sample, scored_sample),
            start_time=start_time,
            end_time=end_time,
            error=sample.error or None,
            extra={
                "metadata": {
                    "sample_id": sample.id,
                    "langsmith_mode": "writeback",
                    "status": sample.status,
                }
            },
        )
        for feedback in _build_feedback_payloads(scored_sample):
            client.create_feedback(
                run_id=run_id,
                key=str(feedback.get("key") or ""),
                score=float(feedback.get("score") or 0.0),
                comment=str(feedback.get("comment") or ""),
                feedback_id=_stable_feedback_id(
                    str(project.id), run_id, str(feedback.get("key") or "")
                ),
                project_id=project.id,
                session_id=project.id,
                source_info={
                    "mode": "local_score_writeback",
                    "sample_id": sample.id,
                },
            )

    return {
        "dataset_name": dataset.name,
        "dataset_id": str(dataset.id),
        "experiment": str(getattr(project, "name", experiment_name)),
        "experiment_url": _build_compare_url(project, str(dataset.id)),
        "mode": "writeback",
    }
