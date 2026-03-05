from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from agent.evaluate.integrations.langsmith_bridge import create_langsmith_evaluator
from agent.evaluate.pipelines.build_graders import _normalize_iterative_dataset
from agent.evaluate.core.schemas import (
    AnswerSample,
    QuerySample,
    ScoredSample,
    load_answer_samples,
    load_query_samples,
    load_scored_samples,
    write_jsonl,
)
from agent.evaluate.pipelines.score_pipeline import compute_dimension_scores
from agent.evaluate.core.trace_extract import extract_trace_artifacts


def test_eval_schema_jsonl_roundtrip(tmp_path: Path) -> None:
    """验证 Query/Answer/Scored 三类样本的 JSONL 序列化与反序列化。"""
    queries_path = tmp_path / "queries.jsonl"
    answers_path = tmp_path / "answers.jsonl"
    scored_path = tmp_path / "scored.jsonl"

    query = QuerySample(
        id="Q001",
        query="统计 AS 数量",
        category="nl2sql",
        difficulty="easy",
        expected_tools=["nl2sql"],
        expected_tool_calls=[{"name": "nl2sql"}],
        tags=["smoke"],
    )
    answer = AnswerSample(
        id="Q001",
        query=query.query,
        answer="共 100 条",
        status="ok",
        expected_tools=query.expected_tools,
        expected_tool_calls=query.expected_tool_calls,
    )
    scored = ScoredSample(
        id="Q001",
        query=query.query,
        answer=answer.answer,
        status="ok",
        scores_raw={"reasoning_planning": 1.0},
        scores_dim={"reasoning_planning": 1.0},
        overall_score=1.0,
    )

    write_jsonl(queries_path, [query.to_dict()])
    write_jsonl(answers_path, [answer.to_dict()])
    write_jsonl(scored_path, [scored.to_dict()])

    loaded_query = load_query_samples(queries_path)
    loaded_answer = load_answer_samples(answers_path)
    loaded_scored = load_scored_samples(scored_path)

    assert len(loaded_query) == 1
    assert loaded_query[0].id == "Q001"
    assert loaded_query[0].expected_tool_calls[0]["name"] == "nl2sql"

    assert len(loaded_answer) == 1
    assert loaded_answer[0].status == "ok"
    assert loaded_answer[0].answer == "共 100 条"

    assert len(loaded_scored) == 1
    assert loaded_scored[0].overall_score == 1.0


def test_extract_trace_artifacts_from_mock_run() -> None:
    """验证 trace 提取逻辑可从 mock root run 正确抽取关键字段。"""
    node_records = [
        {
            "node_name": "plan",
            "final_output": json.dumps(
                {
                    "plan_reason": "先查库再总结",
                    "plan_steps": [
                        {"tool": "nl2sql", "objective": "统计 AS 数量"},
                        {"tool": "rag", "objective": "补充解释"},
                    ],
                },
                ensure_ascii=False,
            ),
            "prompt_records": [],
        },
        {
            "node_name": "collect_memory_notes",
            "final_output": json.dumps({"memories": ["m1"], "notes": ["n1", "n2"]}, ensure_ascii=False),
            "prompt_records": [],
        },
        {
            "node_name": "execute_ready",
            "prompt_records": [
                {
                    "stage": "tool_dispatch_inputs",
                    "tools": [
                        {
                            "step_id": "step_1",
                            "tool": "nl2sql",
                            "arguments": {"question": "统计 AS 数量"},
                        }
                    ],
                },
                {
                    "stage": "tool_dispatch_outputs",
                    "results": [
                        {
                            "step_id": "step_1",
                            "result_preview": "rows=10",
                        }
                    ],
                },
            ],
        },
    ]

    class _MockRun:
        outputs = {
            "node_records": node_records,
            "final_state_output": {
                "completed_ids": ["step_1"],
                "pending_ids": [],
                "conflicts": [],
                "evidence_items": [
                    {
                        "title": "NL2SQL 结果",
                        "source": "nl2sql",
                        "content": "SQL: select count(*) from as_entity;",
                        "score": 1.0,
                        "metadata": {"step_id": "step_1"},
                    }
                ],
                "context_preview": "上下文摘要",
                "answer_preview": "答案摘要",
            },
            "main_flow_trace": {"stage": "done"},
        }

    artifacts = extract_trace_artifacts(
        query="统计 AS 数量",
        answer="共 100 条",
        root_run=_MockRun(),
    )

    assert len(artifacts["tool_calls"]) == 1
    assert artifacts["tool_calls"][0]["name"] == "nl2sql"
    assert "先查库再总结" in artifacts["plan_text"]
    assert "memories=1; notes=2" == artifacts["memory_text"]
    assert artifacts["trajectory_messages"][-1]["content"] == "共 100 条"
    assert len(artifacts["evidence_items"]) == 1
    assert artifacts["evidence_items"][0]["source"] == "nl2sql"
    assert "sources=nl2sql:1" in artifacts["evidence_summary"]


def test_compute_dimension_scores_formula() -> None:
    """验证维度分与总分公式符合约定。"""
    scores_raw = {
        "reasoning_planning": 0.75,
        "tool_use_accuracy": 0.8,
        "final_response_quality": 0.9,
        "evidence_groundedness": 0.7,
    }
    dims, overall = compute_dimension_scores(scores_raw)

    assert abs(dims["reasoning_planning"] - 0.75) < 1e-9
    assert abs(dims["tool_use_accuracy"] - 0.8) < 1e-9
    assert abs(dims["final_response_quality"] - 0.9) < 1e-9
    assert abs(dims["evidence_groundedness"] - 0.7) < 1e-9
    expected_overall = 0.15 * 0.75 + 0.15 * 0.8 + 0.35 * 0.9 + 0.35 * 0.7
    assert abs(overall - expected_overall) < 1e-9


def test_create_langsmith_evaluator_mapper_and_error_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 LangSmith evaluator 包装层的映射与 error 样本跳过行为。"""

    # 构造最小 openjudge 依赖桩，避免单测依赖真实 py-openjudge 安装。
    schema_module = types.ModuleType("openjudge.graders.schema")
    mapping_module = types.ModuleType("openjudge.utils.mapping")

    class _GraderScore:
        def __init__(self, score: float, reason: str):
            self.score = score
            self.reason = reason

    class _GraderRank:
        def __init__(self):
            self.rank = [1]
            self.reason = "rank"

    class _GraderError:
        def __init__(self, error: str):
            self.error = error

    def _parse_data_with_mapper(data: dict, mapper: dict | None = None) -> dict:
        if not mapper:
            return data
        return {dst: data.get(src) for dst, src in mapper.items()}

    schema_module.GraderScore = _GraderScore
    schema_module.GraderRank = _GraderRank
    schema_module.GraderError = _GraderError
    schema_module.GraderResult = object
    mapping_module.parse_data_with_mapper = _parse_data_with_mapper

    monkeypatch.setitem(sys.modules, "openjudge.graders.schema", schema_module)
    monkeypatch.setitem(sys.modules, "openjudge.utils.mapping", mapping_module)

    class _FakeGrader:
        name = "fake_grader"

        def __init__(self) -> None:
            self.calls = []

        async def aevaluate(self, **kwargs):
            self.calls.append(kwargs)
            return _GraderScore(score=0.75, reason="ok")

    grader = _FakeGrader()
    evaluator = create_langsmith_evaluator(grader=grader, mapper={"query": "query", "response": "answer"})

    ok_result = evaluator(
        inputs={"id": "Q001"},
        outputs={"status": "ok", "query": "问题", "answer": "回答"},
        reference_outputs={"reference_answer": ""},
    )
    assert ok_result["key"] == "fake_grader"
    assert ok_result["score"] == 0.75
    assert grader.calls and grader.calls[0]["query"] == "问题"
    assert grader.calls[0]["response"] == "回答"

    err_result = evaluator(
        inputs={"id": "Q002"},
        outputs={"status": "error", "query": "问题2", "answer": ""},
        reference_outputs={},
    )
    assert err_result["score"] == 0.0
    assert "skip" in err_result["comment"]
    # error 样本应短路，不触发二次评分调用。
    assert len(grader.calls) == 1


def test_normalize_iterative_dataset_from_gold_shape() -> None:
    """验证 gold 风格样本可规范化为 Iterative Rubric 所需格式。"""
    rows = [
        {
            "id": "Q001",
            "query": "解释自治系统",
            "reference_answer": "自治系统是由统一管理策略控制的路由域。",
            "scores_dim": {"final_response_quality": 0.4},
        },
        {
            "id": "Q002",
            "query": "统计 AS 数量",
            "answer": "共有 100 个。",
            "main_score": 0.9,
        },
    ]

    dataset, label_source_count, clipped_count = _normalize_iterative_dataset(rows)

    assert len(dataset) == 2
    assert dataset[0]["id"] == "Q001"
    assert dataset[0]["response"] == "自治系统是由统一管理策略控制的路由域。"
    assert dataset[0]["label_score"] == 0
    assert dataset[1]["label_score"] == 1
    assert label_source_count["scores_dim.final_response_quality"] == 1
    assert label_source_count["main_score"] == 1
    assert clipped_count == 0
