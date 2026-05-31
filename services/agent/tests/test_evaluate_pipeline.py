from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import types
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.evaluate.core.config import (
    EvalRuntimeConfig,
    ensure_langsmith_tracing_enabled,
)
from agent.evaluate.integrations import langsmith_bridge as langsmith_bridge_module
from agent.evaluate.integrations.langsmith_bridge import (
    create_langsmith_evaluator,
    write_local_scores_to_langsmith_experiment,
)
from agent.evaluate.pipelines.build_graders import _normalize_iterative_dataset
from agent.evaluate.core.schemas import (
    AnswerSample,
    GraderScore01Callback,
    QuerySample,
    ScoredSample,
    load_answer_samples,
    load_query_samples,
    load_scored_samples,
    write_jsonl,
)
from agent.evaluate.pipelines.score_pipeline import (
    ToolSelectionAccuracyGrader,
    _build_grader_configs,
    compute_dimension_scores,
    rebuild_answer_samples_for_posthoc_tool_rescore,
    run_scoring,
)
from agent.evaluate.core.trace_extract import (
    extract_trace_artifacts,
    rebuild_trace_artifacts,
)


run_pipeline_module = importlib.import_module("agent.evaluate.pipelines.run_pipeline")


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
        tool_execution_records=[
            {"step_id": "step_1", "name": "nl2sql", "status": "ok"}
        ],
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
    assert loaded_answer[0].tool_execution_records[0]["name"] == "nl2sql"

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
            "final_output": json.dumps(
                {"memories": ["m1"], "notes": ["n1", "n2"]}, ensure_ascii=False
            ),
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
                            "status": "ok",
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
    assert len(artifacts["tool_execution_records"]) == 1
    assert artifacts["tool_execution_records"][0]["status"] == "ok"
    assert "先查库再总结" in artifacts["plan_text"]
    assert "memories=1; notes=2" == artifacts["memory_text"]
    assert artifacts["trajectory_messages"][-1]["content"] == "共 100 条"
    assert "result_preview=rows=10" in artifacts["trajectory_messages"][2]["content"]
    assert len(artifacts["evidence_items"]) == 1
    assert artifacts["evidence_items"][0]["source"] == "nl2sql"
    assert "sources=nl2sql:1" in artifacts["evidence_summary"]


def test_rebuild_trace_artifacts_from_saved_payload() -> None:
    """验证后补模式可直接基于已保存 trace 载荷重建工具字段。"""
    node_records = [
        {
            "node_name": "execute_ready",
            "prompt_records": [
                {
                    "stage": "tool_dispatch_inputs",
                    "tools": [
                        {
                            "step_id": "step_1",
                            "tool": "rag",
                            "arguments": {"query": "自治系统", "top_k": 3},
                        }
                    ],
                },
                {
                    "stage": "tool_dispatch_outputs",
                    "results": [
                        {
                            "step_id": "step_1",
                            "status": "ok",
                            "result_preview": "chunks=3",
                        }
                    ],
                },
            ],
        }
    ]
    final_state_output = {
        "completed_ids": ["step_1"],
        "pending_ids": [],
        "conflicts": [],
        "evidence_items": [
            {
                "title": "RAG 文档片段",
                "source": "rag",
                "content": "自治系统定义",
                "score": 0.8,
                "metadata": {"step_id": "step_1"},
            }
        ],
    }

    rebuilt = rebuild_trace_artifacts(
        query="什么是自治系统？",
        answer="自治系统是...",
        node_records=node_records,
        final_state_output=final_state_output,
        main_flow_trace={"stage": "done"},
    )

    assert rebuilt["tool_execution_records"][0]["name"] == "rag"
    assert rebuilt["tool_execution_records"][0]["status"] == "ok"
    assert (
        rebuilt["trajectory_messages"][2]["content"]
        == "status=ok\nresult_preview=chunks=3"
    )
    assert "sources=rag:1" in rebuilt["evidence_summary"]


def test_posthoc_tool_rescore_rebuilds_answers_and_recomputes_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """验证 score_pipeline 可对已保存 answers 做后补工具重评分。"""

    class _Result:
        def __init__(self, score: float, reason: str) -> None:
            self.score = score
            self.reason = reason

    fake_runner_module = types.ModuleType("openjudge.runner.grading_runner")

    class _FakeRunner:
        def __init__(self, grader_configs, max_concurrency=8):
            self.grader_configs = grader_configs
            self.max_concurrency = max_concurrency

        async def arun(self, dataset):
            assert dataset[0]["tool_execution_records"][0]["name"] == "nl2sql"
            return {
                "reasoning_planning": [_Result(0.8, "plan")],
                "tool_selection_accuracy": [_Result(1.0, "sel")],
                "tool_argument_quality": [_Result(0.5, "arg")],
                "tool_outcome_effectiveness": [_Result(0.25, "outcome")],
                "final_response_quality": [_Result(0.9, "resp")],
                "evidence_groundedness": [_Result(0.7, "evidence")],
            }

    fake_runner_module.GradingRunner = _FakeRunner
    monkeypatch.setitem(
        sys.modules, "openjudge.runner.grading_runner", fake_runner_module
    )
    monkeypatch.setattr(
        "agent.evaluate.pipelines.score_pipeline._load_rubrics",
        lambda _path: {"last_message_rubrics": "ok"},
    )
    monkeypatch.setattr(
        "agent.evaluate.pipelines.score_pipeline._build_grader_configs",
        lambda **_kwargs: {
            "reasoning_planning": (object(), None),
            "tool_selection_accuracy": (object(), None),
            "tool_argument_quality": (object(), None),
            "tool_outcome_effectiveness": (object(), None),
            "final_response_quality": (object(), None),
            "evidence_groundedness": (object(), None),
        },
    )

    sample = AnswerSample(
        id="Q001",
        query="统计 AS 数量",
        answer="共 100 条",
        status="ok",
        node_records=[
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
                                "status": "ok",
                                "result_preview": "rows=1",
                            }
                        ],
                    },
                ],
            }
        ],
        final_state_output={
            "completed_ids": ["step_1"],
            "pending_ids": [],
            "conflicts": [],
            "evidence_items": [
                {
                    "title": "NL2SQL 结果",
                    "source": "nl2sql",
                    "content": "SQL: select count(*) ...",
                    "score": 1.0,
                    "metadata": {"step_id": "step_1"},
                }
            ],
        },
        expected_tools=["nl2sql"],
        expected_tool_calls=[{"name": "nl2sql"}],
    )

    posthoc_answers_out = tmp_path / "answers.posthoc.jsonl"
    summary = run_scoring(
        answer_samples=[sample],
        rubrics_path=tmp_path / "rubrics.json",
        scored_out_path=tmp_path / "scored.jsonl",
        summary_out_path=tmp_path / "summary.json",
        manual_review_csv_path=tmp_path / "manual_review.csv",
        push_langsmith=False,
        posthoc_tool_rescore=True,
        posthoc_answers_out_path=posthoc_answers_out,
    )

    rebuilt_answers = load_answer_samples(posthoc_answers_out)
    assert rebuilt_answers[0].tool_execution_records[0]["name"] == "nl2sql"
    assert (
        rebuilt_answers[0].trajectory_messages[2]["content"]
        == "status=ok\nresult_preview=rows=1"
    )
    assert summary["posthoc_tool_rescore"] is True
    assert abs(summary["avg_tool_subscores"]["tool_selection_accuracy"] - 1.0) < 1e-9
    assert abs(summary["avg_dim"]["tool_use_accuracy"] - 0.625) < 1e-9


def test_run_scoring_langsmith_writeback_mode_skips_remote_evaluate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """writeback 模式应直接写回本地分数，不再调用 LangSmith evaluate grader。"""

    class _Result:
        def __init__(self, score: float, reason: str) -> None:
            self.score = score
            self.reason = reason

    fake_runner_module = types.ModuleType("openjudge.runner.grading_runner")

    class _FakeRunner:
        def __init__(self, grader_configs, max_concurrency=8):
            self.grader_configs = grader_configs

        async def arun(self, dataset):
            return {
                "reasoning_planning": [_Result(0.8, "plan")],
                "tool_selection_accuracy": [_Result(1.0, "sel")],
                "tool_argument_quality": [_Result(0.5, "arg")],
                "tool_outcome_effectiveness": [_Result(0.25, "outcome")],
                "final_response_quality": [_Result(0.9, "resp")],
                "evidence_groundedness": [_Result(0.7, "evidence")],
            }

    fake_runner_module.GradingRunner = _FakeRunner
    monkeypatch.setitem(
        sys.modules, "openjudge.runner.grading_runner", fake_runner_module
    )
    monkeypatch.setattr(
        "agent.evaluate.pipelines.score_pipeline._load_rubrics",
        lambda _path: {"last_message_rubrics": "ok"},
    )
    monkeypatch.setattr(
        "agent.evaluate.pipelines.score_pipeline._build_grader_configs",
        lambda **_kwargs: {
            "reasoning_planning": (object(), None),
            "tool_selection_accuracy": (object(), None),
            "tool_argument_quality": (object(), None),
            "tool_outcome_effectiveness": (object(), None),
            "final_response_quality": (object(), None),
            "evidence_groundedness": (object(), None),
        },
    )

    observed: dict[str, object] = {}

    def _fake_writeback(**kwargs):
        observed["writeback"] = kwargs
        return {"mode": "writeback", "experiment": "exp", "experiment_url": "url"}

    def _fake_evaluate(**kwargs):
        raise AssertionError("writeback 模式不应触发 run_langsmith_experiment")

    monkeypatch.setattr(
        "agent.evaluate.pipelines.score_pipeline.write_local_scores_to_langsmith_experiment",
        _fake_writeback,
    )
    monkeypatch.setattr(
        "agent.evaluate.pipelines.score_pipeline.run_langsmith_experiment",
        _fake_evaluate,
    )

    sample = AnswerSample(id="Q001", query="问题", answer="回答", status="ok")
    summary = run_scoring(
        answer_samples=[sample],
        rubrics_path=tmp_path / "rubrics.json",
        scored_out_path=tmp_path / "scored.jsonl",
        summary_out_path=tmp_path / "summary.json",
        manual_review_csv_path=tmp_path / "manual_review.csv",
        push_langsmith=True,
        langsmith_mode="writeback",
    )

    assert observed["writeback"]
    assert summary["langsmith"]["mode"] == "writeback"


def test_compute_dimension_scores_formula() -> None:
    """验证维度分与总分公式符合约定。"""
    scores_raw = {
        "reasoning_planning": 0.75,
        "tool_selection_accuracy": 1.0,
        "tool_argument_quality": 0.5,
        "tool_outcome_effectiveness": 0.25,
        "final_response_quality": 0.9,
        "evidence_groundedness": 0.7,
    }
    dims, overall = compute_dimension_scores(scores_raw)

    assert abs(dims["reasoning_planning"] - 0.75) < 1e-9
    assert abs(dims["tool_use_accuracy"] - 0.625) < 1e-9
    assert abs(dims["final_response_quality"] - 0.9) < 1e-9
    assert abs(dims["evidence_groundedness"] - 0.7) < 1e-9
    expected_overall = 0.15 * 0.75 + 0.15 * 0.625 + 0.35 * 0.9 + 0.35 * 0.7
    assert abs(overall - expected_overall) < 1e-9


def test_grader_score_01_callback_rejects_out_of_range_score() -> None:
    """0~1 评分 schema 应直接拒绝越界分数。"""

    with pytest.raises(ValidationError):
        GraderScore01Callback(reason="bad", score=1.2)


def test_build_grader_configs_uses_score_01_schema_for_llm_dims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """最终回复质量与证据一致性评分应绑定 0~1 schema。"""

    plan_module = types.ModuleType("openjudge.graders.agent.plan.plan_feasibility")
    tool_module = types.ModuleType("openjudge.graders.agent.tool.tool_parameter_check")
    trajectory_module = types.ModuleType(
        "openjudge.graders.agent.trajectory.trajectory_comprehensive"
    )
    llm_module = types.ModuleType("openjudge.graders.llm_grader")
    schema_module = types.ModuleType("openjudge.graders.schema")
    prompt_module = types.ModuleType("openjudge.models.schema.prompt_template")

    class _DummyGrader:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _FakeLLMGrader(_DummyGrader):
        pass

    plan_module.PlanFeasibilityGrader = _DummyGrader
    tool_module.ToolParameterCheckGrader = _DummyGrader
    trajectory_module.TrajectoryComprehensiveGrader = _DummyGrader
    llm_module.LLMGrader = _FakeLLMGrader
    schema_module.GraderMode = types.SimpleNamespace(POINTWISE="pointwise")
    prompt_module.LanguageEnum = types.SimpleNamespace(ZH="zh")

    monkeypatch.setitem(
        sys.modules, "openjudge.graders.agent.plan.plan_feasibility", plan_module
    )
    monkeypatch.setitem(
        sys.modules, "openjudge.graders.agent.tool.tool_parameter_check", tool_module
    )
    monkeypatch.setitem(
        sys.modules,
        "openjudge.graders.agent.trajectory.trajectory_comprehensive",
        trajectory_module,
    )
    monkeypatch.setitem(sys.modules, "openjudge.graders.llm_grader", llm_module)
    monkeypatch.setitem(sys.modules, "openjudge.graders.schema", schema_module)
    monkeypatch.setitem(
        sys.modules, "openjudge.models.schema.prompt_template", prompt_module
    )
    monkeypatch.setattr(
        "agent.evaluate.pipelines.score_pipeline.AgentConfig.load",
        lambda: object(),
    )
    monkeypatch.setattr(
        "agent.evaluate.pipelines.score_pipeline.build_openjudge_model",
        lambda _cfg, model_name="": object(),
    )

    grader_configs = _build_grader_configs({"last_message_rubrics": "ok"})
    assert (
        grader_configs["final_response_quality"][0].kwargs["structured_model"]
        is GraderScore01Callback
    )
    assert (
        grader_configs["evidence_groundedness"][0].kwargs["structured_model"]
        is GraderScore01Callback
    )


def test_run_scoring_clamps_out_of_range_raw_scores(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """评分器若返回异常分值，score_pipeline 应在落盘前裁剪到 0~1。"""

    class _Result:
        def __init__(self, score: float, reason: str) -> None:
            self.score = score
            self.reason = reason

    fake_runner_module = types.ModuleType("openjudge.runner.grading_runner")

    class _FakeRunner:
        def __init__(self, grader_configs, max_concurrency=8):
            self.grader_configs = grader_configs

        async def arun(self, dataset):
            return {
                "reasoning_planning": [_Result(1.0, "plan")],
                "tool_selection_accuracy": [_Result(1.0, "sel")],
                "tool_argument_quality": [_Result(1.0, "arg")],
                "tool_outcome_effectiveness": [_Result(1.0, "outcome")],
                "final_response_quality": [_Result(4.5, "resp")],
                "evidence_groundedness": [_Result(9.0, "evidence")],
            }

    fake_runner_module.GradingRunner = _FakeRunner
    monkeypatch.setitem(
        sys.modules, "openjudge.runner.grading_runner", fake_runner_module
    )
    monkeypatch.setattr(
        "agent.evaluate.pipelines.score_pipeline._load_rubrics",
        lambda _path: {"last_message_rubrics": "ok"},
    )
    monkeypatch.setattr(
        "agent.evaluate.pipelines.score_pipeline._build_grader_configs",
        lambda **_kwargs: {
            "reasoning_planning": (object(), None),
            "tool_selection_accuracy": (object(), None),
            "tool_argument_quality": (object(), None),
            "tool_outcome_effectiveness": (object(), None),
            "final_response_quality": (object(), None),
            "evidence_groundedness": (object(), None),
        },
    )

    run_scoring(
        answer_samples=[
            AnswerSample(id="Q001", query="问题", answer="回答", status="ok")
        ],
        rubrics_path=tmp_path / "rubrics.json",
        scored_out_path=tmp_path / "scored.jsonl",
        summary_out_path=tmp_path / "summary.json",
        manual_review_csv_path=tmp_path / "manual_review.csv",
        push_langsmith=False,
    )

    scored_samples = load_scored_samples(tmp_path / "scored.jsonl")
    assert scored_samples[0].scores_raw["final_response_quality"] == 1.0
    assert scored_samples[0].scores_raw["evidence_groundedness"] == 1.0
    assert (
        "原始分=4.500000" in scored_samples[0].score_reasons["final_response_quality"]
    )
    assert "原始分=9.000000" in scored_samples[0].score_reasons["evidence_groundedness"]


def test_tool_selection_accuracy_grader_uses_f1() -> None:
    """验证工具选择评分按集合 F1 计算。"""
    grader = ToolSelectionAccuracyGrader()

    result = asyncio.run(
        grader.aevaluate(
            tool_calls=[{"name": "nl2sql"}, {"name": "rag"}],
            reference_tool_calls=[{"name": "nl2sql"}],
            expected_tools=["nl2sql"],
        )
    )

    assert abs(result.score - (2 / 3)) < 1e-9
    assert "precision=0.500" in result.reason
    assert "recall=1.000" in result.reason


def test_ensure_langsmith_tracing_enabled_sets_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未显式配置时，评测流水线应自动写入 LANGSMITH_TRACING=true。"""
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)

    updated = ensure_langsmith_tracing_enabled()

    assert updated is True
    assert os.environ["LANGSMITH_TRACING"] == "true"


def test_run_pipeline_auto_enables_langsmith_tracing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """一键评测入口应在阶段 B 前自动开启 LangSmith tracing。"""
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)

    query_sample = QuerySample(
        id="Q001",
        query="统计 AS 数量",
        category="nl2sql",
        difficulty="easy",
        expected_tools=["nl2sql"],
        expected_tool_calls=[{"name": "nl2sql"}],
        tags=["smoke"],
    )
    answer_sample = AnswerSample(
        id="Q001",
        query="统计 AS 数量",
        answer="共 100 条",
        status="ok",
        expected_tools=["nl2sql"],
        expected_tool_calls=[{"name": "nl2sql"}],
    )
    observed: dict[str, str] = {}

    monkeypatch.setattr(run_pipeline_module, "generate_queries", lambda **_kwargs: None)
    monkeypatch.setattr(
        run_pipeline_module, "load_query_samples", lambda _path: [query_sample]
    )

    def _fake_fill_answers(**_kwargs):
        observed["tracing"] = os.getenv("LANGSMITH_TRACING", "")
        return [answer_sample]

    monkeypatch.setattr(run_pipeline_module, "fill_answers", _fake_fill_answers)
    monkeypatch.setattr(run_pipeline_module, "generate_rubrics", lambda **_kwargs: None)
    monkeypatch.setattr(
        run_pipeline_module, "load_answer_samples", lambda _path: [answer_sample]
    )
    monkeypatch.setattr(run_pipeline_module, "run_scoring", lambda **_kwargs: {})

    run_pipeline_module.run_pipeline(
        runtime_cfg=EvalRuntimeConfig(
            workdir=tmp_path, summary_path=tmp_path / "summary.md", query_count=1
        ),
        push_langsmith=False,
        dataset_name="fusion-openjudge-eval",
        experiment_prefix="fusion-openjudge",
        rubric_labeled_data=None,
        model_name="",
        gold_readable_path=None,
        gold_out_path=None,
        gold_base_path=None,
    )

    assert observed["tracing"] == "true"


def test_create_langsmith_evaluator_mapper_and_error_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    evaluator = create_langsmith_evaluator(
        grader=grader, mapper={"query": "query", "response": "answer"}
    )

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


def test_create_langsmith_evaluator_clamps_out_of_range_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LangSmith evaluator 模式也应裁剪异常分值，避免 feedback 出现 >1。"""

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

    schema_module.GraderScore = _GraderScore
    schema_module.GraderRank = _GraderRank
    schema_module.GraderError = _GraderError
    schema_module.GraderResult = object
    mapping_module.parse_data_with_mapper = lambda data, mapper=None: data

    monkeypatch.setitem(sys.modules, "openjudge.graders.schema", schema_module)
    monkeypatch.setitem(sys.modules, "openjudge.utils.mapping", mapping_module)

    class _FakeGrader:
        name = "fake_grader"

        async def aevaluate(self, **kwargs):
            return _GraderScore(score=9.0, reason="overflow")

    evaluator = create_langsmith_evaluator(grader=_FakeGrader(), mapper=None)
    result = evaluator(
        inputs={"id": "Q001"}, outputs={"status": "ok"}, reference_outputs={}
    )
    assert result["score"] == 1.0


def test_upsert_examples_splits_create_and_update() -> None:
    """重复推送 LangSmith 时应对已存在样本走 update，而不是再次 create。"""

    class _Dataset:
        id = "dataset-1"
        name = "fusion-openjudge-eval"

    class _Example:
        def __init__(self, example_id: str) -> None:
            self.id = example_id

    class _FakeClient:
        def __init__(self) -> None:
            self.created: list[dict] = []
            self.updated: list[dict] = []

        def read_dataset(self, dataset_name: str):
            assert dataset_name == "fusion-openjudge-eval"
            return _Dataset()

        def list_examples(self, dataset_id: str, example_ids: list[str]):
            assert dataset_id == "dataset-1"
            existing_id = langsmith_bridge_module._stable_example_id("Q001")
            return [_Example(existing_id)] if existing_id in example_ids else []

        def create_examples(self, dataset_id: str, examples: list[dict]):
            assert dataset_id == "dataset-1"
            self.created.extend(examples)

        def update_examples(self, dataset_id: str, updates: list[dict]):
            assert dataset_id == "dataset-1"
            self.updated.extend(updates)

    client = _FakeClient()
    samples = [
        AnswerSample(id="Q001", query="问题1", answer="回答1", status="ok"),
        AnswerSample(id="Q002", query="问题2", answer="回答2", status="ok"),
    ]

    dataset = langsmith_bridge_module.upsert_examples(
        client=client,
        dataset_name="fusion-openjudge-eval",
        samples=samples,
    )

    assert dataset.id == "dataset-1"
    assert len(client.created) == 1
    assert client.created[0]["id"] == langsmith_bridge_module._stable_example_id("Q002")
    assert len(client.updated) == 1
    assert client.updated[0]["id"] == langsmith_bridge_module._stable_example_id("Q001")


def test_write_local_scores_to_langsmith_experiment_creates_runs_and_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """本地分数直写模式应创建 run 并写入 feedback，而不是再次执行 evaluator。"""

    class _Dataset:
        id = "dataset-1"
        name = "fusion-openjudge-eval"

    class _Project:
        id = "project-1"
        name = "fusion-openjudge-testexp"
        url = "https://smith.langchain.com/o/test/projects/p/project-1"

    class _FakeClient:
        def __init__(self) -> None:
            self.created_examples: list[dict] = []
            self.created_runs: list[dict] = []
            self.created_feedback: list[dict] = []

        def read_dataset(self, dataset_name: str):
            assert dataset_name == "fusion-openjudge-eval"
            return _Dataset()

        def list_examples(self, dataset_id: str, example_ids: list[str]):
            assert dataset_id == "dataset-1"
            return []

        def create_examples(self, dataset_id: str, examples: list[dict]):
            assert dataset_id == "dataset-1"
            self.created_examples.extend(examples)

        def update_examples(self, dataset_id: str, updates: list[dict]):
            raise AssertionError("不应走 update_examples")

        def create_project(self, **kwargs):
            assert kwargs["reference_dataset_id"] == "dataset-1"
            return _Project()

        def create_run(self, **kwargs):
            self.created_runs.append(kwargs)

        def create_feedback(self, **kwargs):
            self.created_feedback.append(kwargs)

    fake_client = _FakeClient()
    monkeypatch.setattr(langsmith_bridge_module, "Client", lambda: fake_client)

    sample = AnswerSample(
        id="Q001",
        query="统计 AS 数量",
        answer="共 100 条",
        status="ok",
        tool_execution_records=[
            {"step_id": "step_1", "name": "nl2sql", "status": "ok"}
        ],
        tool_calls=[{"name": "nl2sql", "step_id": "step_1"}],
        trajectory_messages=[{"role": "user", "content": "统计 AS 数量"}],
        evidence_summary="tool_calls=1",
    )
    scored = ScoredSample(
        id="Q001",
        query="统计 AS 数量",
        answer="共 100 条",
        status="ok",
        scores_raw={
            "tool_selection_accuracy": 1.0,
            "tool_argument_quality": 0.5,
            "tool_outcome_effectiveness": 0.25,
        },
        scores_dim={
            "reasoning_planning": 0.8,
            "tool_use_accuracy": 0.625,
            "final_response_quality": 0.9,
            "evidence_groundedness": 0.7,
        },
        overall_score=0.74875,
        score_reasons={"tool_use_accuracy": "聚合说明"},
    )

    result = write_local_scores_to_langsmith_experiment(
        samples=[sample],
        scored_samples=[scored],
        dataset_name="fusion-openjudge-eval",
        experiment_prefix="fusion-openjudge",
        description="test",
    )

    assert result["mode"] == "writeback"
    assert "compare?selectedSessions=project-1" in result["experiment_url"]
    assert len(fake_client.created_examples) == 1
    assert len(fake_client.created_runs) == 1
    assert (
        fake_client.created_runs[0]["outputs"]["overall_score"] == scored.overall_score
    )
    feedback_keys = {item["key"] for item in fake_client.created_feedback}
    assert "overall_score" in feedback_keys
    assert "tool_use_accuracy" in feedback_keys
    assert "tool_selection_accuracy" in feedback_keys


def test_write_local_scores_to_langsmith_experiment_clamps_outputs_and_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """writeback 模式应裁剪旧 scored 文件中的异常分值。"""

    class _Dataset:
        id = "dataset-1"
        name = "fusion-openjudge-eval"

    class _Project:
        id = "project-1"
        name = "fusion-openjudge-12345678"
        url = "https://smith.langchain.com/projects/p/project-1"

    class _FakeClient:
        def __init__(self) -> None:
            self.created_runs = []
            self.created_feedback = []

        def read_dataset(self, dataset_name: str):
            return _Dataset()

        def list_examples(self, dataset_id: str, example_ids: list[str]):
            return []

        def create_examples(self, dataset_id: str, examples: list[dict]):
            return None

        def update_examples(self, dataset_id: str, updates: list[dict]):
            return None

        def create_project(self, **kwargs):
            return _Project()

        def create_run(self, **kwargs):
            self.created_runs.append(kwargs)

        def create_feedback(self, **kwargs):
            self.created_feedback.append(kwargs)

    fake_client = _FakeClient()
    monkeypatch.setattr(langsmith_bridge_module, "Client", lambda: fake_client)

    sample = AnswerSample(id="Q001", query="问题", answer="回答", status="ok")
    scored = ScoredSample(
        id="Q001",
        query="问题",
        answer="回答",
        status="ok",
        scores_raw={"tool_selection_accuracy": 1.8},
        scores_dim={"reasoning_planning": 1.2},
        overall_score=7.0,
    )

    write_local_scores_to_langsmith_experiment(
        samples=[sample],
        scored_samples=[scored],
        dataset_name="fusion-openjudge-eval",
        experiment_prefix="fusion-openjudge",
        description="test",
    )

    assert (
        fake_client.created_runs[0]["outputs"]["scores_raw"]["tool_selection_accuracy"]
        == 1.0
    )
    assert (
        fake_client.created_runs[0]["outputs"]["scores_dim"]["reasoning_planning"]
        == 1.0
    )
    assert fake_client.created_runs[0]["outputs"]["overall_score"] == 1.0
    feedback_by_key = {
        item["key"]: item["score"] for item in fake_client.created_feedback
    }
    assert feedback_by_key["overall_score"] == 1.0
    assert feedback_by_key["reasoning_planning"] == 1.0
    assert feedback_by_key["tool_selection_accuracy"] == 1.0


def test_normalize_iterative_dataset_from_gold_shape() -> None:
    """验证 gold 风格样本可规范化为 Iterative Rubric 所需格式。"""
    rows = [
        {
            "id": "Q001",
            "query": "解释自治系统",
            "reference_answer": "自治系统是由统一管理策略控制的路由域。",
            "label_score": 0,
        },
        {
            "id": "Q002",
            "query": "统计 AS 数量",
            "answer": "共有 100 个。",
            "label_score": 1,
        },
    ]

    dataset, label_source_count, clipped_count = _normalize_iterative_dataset(rows)

    assert len(dataset) == 2
    assert dataset[0]["id"] == "Q001"
    assert dataset[0]["response"] == "自治系统是由统一管理策略控制的路由域。"
    assert dataset[0]["label_score"] == 0
    assert dataset[1]["label_score"] == 1
    assert label_source_count["label_score"] == 2
    assert clipped_count == 0


def test_normalize_iterative_dataset_requires_binary_label_score() -> None:
    """验证缺少或非法 label_score 会直接报错。"""
    with pytest.raises(RuntimeError, match="label_score"):
        _normalize_iterative_dataset(
            [
                {
                    "id": "Q003",
                    "query": "测试",
                    "response": "测试回答",
                }
            ]
        )
