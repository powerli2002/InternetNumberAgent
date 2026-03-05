"""LangSmith Dataset 与 Experiment 桥接。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable, Dict, Iterable, List, Tuple

from langsmith import Client
from langsmith.evaluation import evaluate

from agent.evaluate.core.config import EVAL_TOOL_DEFINITIONS
from agent.evaluate.core.schemas import AnswerSample


def _stable_example_id(sample_id: str) -> str:
    """为样本生成稳定 UUID，便于 upsert。"""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"fusion-eval:{sample_id}"))


def ensure_dataset(client: Client, dataset_name: str, description: str = "") -> Any:
    """读取或创建 Dataset。"""
    try:
        return client.read_dataset(dataset_name=dataset_name)
    except Exception:
        return client.create_dataset(dataset_name=dataset_name, description=description or None)


def upsert_examples(client: Client, dataset_name: str, samples: Iterable[AnswerSample], description: str = "") -> Any:
    """按稳定 id 写入/更新样本到 Dataset。"""
    dataset = ensure_dataset(client=client, dataset_name=dataset_name, description=description)
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
    client.create_examples(dataset_id=dataset.id, examples=examples)
    return dataset


def build_cached_application(samples: Iterable[AnswerSample]) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
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


def create_langsmith_evaluator(grader: Any, mapper: Dict[str, str] | None = None) -> Callable[[dict, dict, dict], dict]:
    """把 OpenJudge grader 包装成 LangSmith evaluator。"""
    from openjudge.graders.schema import GraderError, GraderRank, GraderResult, GraderScore
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
                    "score": float(result.score),
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

    evaluators = [create_langsmith_evaluator(grader=grader, mapper=mapper) for grader, mapper in grader_configs]
    cached_app = build_cached_application(samples_list)

    experiment_results = evaluate(
        cached_app,
        data=dataset.name,
        evaluators=evaluators,
        experiment_prefix=experiment_prefix,
        description=description,
        max_concurrency=max(1, int(max_concurrency)),
    )

    return {
        "dataset_name": dataset.name,
        "dataset_id": str(dataset.id),
        "experiment": str(getattr(experiment_results, "experiment_name", "")),
        "experiment_url": str(getattr(experiment_results, "url", "")),
    }
