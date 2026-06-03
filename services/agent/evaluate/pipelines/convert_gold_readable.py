"""把人工可读 YAML 标注转换为 gold.jsonl。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List

import yaml


MAIN_SCORE_WEIGHTS: Dict[str, float] = {
    "tool_use_accuracy": 0.15,
    "reasoning_planning": 0.15,
    "final_response_quality": 0.35,
    "evidence_groundedness": 0.35,
}


def _clamp_01(value: Any) -> float:
    """将任意输入安全转换为 0~1 分数。"""
    try:
        score = float(value)
    except Exception:
        score = 0.0
    return max(0.0, min(1.0, score))


def _load_jsonl_map(path: Path) -> Dict[str, Dict[str, Any]]:
    """按 id 读取 JSONL 为映射。"""
    if not path.exists():
        return {}
    data: Dict[str, Dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as fr:
        for line in fr:
            text = line.strip()
            if not text:
                continue
            row = json.loads(text)
            if not isinstance(row, dict):
                continue
            item_id = str(row.get("id") or "").strip()
            if not item_id:
                continue
            data[item_id] = row
    return data


def _tool_name_list(tool_calls: List[Dict[str, Any]]) -> List[str]:
    """提取工具名列表并统一小写。"""
    names: List[str] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        name = str(call.get("name") or "").strip().lower()
        if name:
            names.append(name)
    return names


def _compute_tool_recall(expected_tool_calls: List[Dict[str, Any]], tool_calls: List[Dict[str, Any]]) -> float:
    """按工具名多重集计算 recall（与当前自动评分器口径保持一致）。"""
    expected = _tool_name_list(expected_tool_calls)
    actual = _tool_name_list(tool_calls)
    if not expected:
        return 1.0

    remaining: Dict[str, int] = {}
    for name in actual:
        remaining[name] = remaining.get(name, 0) + 1

    matched = 0
    for name in expected:
        cnt = remaining.get(name, 0)
        if cnt <= 0:
            continue
        matched += 1
        remaining[name] = cnt - 1
    return _clamp_01(matched / max(1, len(expected)))


def _compute_tool_scores(
    human_tool_scores: List[Dict[str, Any]],
    expected_tools: List[str],
) -> tuple[float, Dict[str, float]]:
    """计算 tool_score（均值）与 tool_score_dict（按工具聚合）。"""
    tool_to_scores: Dict[str, List[float]] = {}
    all_scores: List[float] = []

    for item in human_tool_scores:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "").strip().lower()
        if not tool:
            continue
        if item.get("score") is None:
            continue
        score = _clamp_01(item.get("score"))
        tool_to_scores.setdefault(tool, []).append(score)
        all_scores.append(score)

    tool_score_dict: Dict[str, float] = {}
    tool_names = sorted(set([str(t).strip().lower() for t in expected_tools if str(t).strip()] + list(tool_to_scores.keys())))
    for tool in tool_names:
        scores = tool_to_scores.get(tool, [])
        tool_score_dict[tool] = float(mean(scores)) if scores else -1.0

    tool_score = float(mean(all_scores)) if all_scores else -1.0
    return tool_score, tool_score_dict


def _as_list_of_dict(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: List[Dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            result.append(dict(item))
    return result


def _derive_expected_tools(
    expected_tool_calls: List[Dict[str, Any]],
    fallback_expected_tools: List[Any],
) -> List[str]:
    """优先从 expected_tool_calls 派生 expected_tools。"""
    names = _tool_name_list(expected_tool_calls)
    if names:
        return sorted(set(names))
    tools = [str(item).strip().lower() for item in fallback_expected_tools if str(item).strip()]
    return sorted(set(tools))


def _to_binary_label(score: float) -> int:
    """把 0~1 连续分数映射为 0/1 标签，供 Iterative Rubric 使用。"""
    return 1 if _clamp_01(score) >= 0.5 else 0


def _convert_record(
    row: Dict[str, Any],
    base_row: Dict[str, Any],
    answers_row: Dict[str, Any],
    score_source: str,
    trace_source_default: str,
) -> Dict[str, Any]:
    """转换单条 YAML 记录为 gold.jsonl 行。"""
    item_id = str(row.get("id") or "").strip()
    query = str(row.get("query") or base_row.get("query") or "").strip()
    if not item_id or not query:
        raise ValueError(f"记录缺少 id/query: id={item_id!r}")

    expected_tool_calls = _as_list_of_dict(row.get("expected_tool_calls") or base_row.get("expected_tool_calls"))
    tool_calls = _as_list_of_dict(row.get("tool_calls") or [])
    expected_tools = _derive_expected_tools(expected_tool_calls, row.get("expected_tools") or base_row.get("expected_tools") or [])
    tool_use_accuracy = _compute_tool_recall(expected_tool_calls, tool_calls)

    reasoning = _clamp_01(row.get("human_reasoning_planning"))
    final_quality = _clamp_01(row.get("human_final_response_quality"))
    evidence_grounded = _clamp_01(row.get("human_evidence_groundedness"))
    scores_dim = {
        "reasoning_planning": reasoning,
        "tool_use_accuracy": tool_use_accuracy,
        "final_response_quality": final_quality,
        "evidence_groundedness": evidence_grounded,
    }
    main_score = round(_clamp_01(sum(MAIN_SCORE_WEIGHTS[key] * scores_dim[key] for key in MAIN_SCORE_WEIGHTS)), 6)

    human_tool_scores = _as_list_of_dict(row.get("human_tool_call_scores"))
    tool_score, tool_score_dict = _compute_tool_scores(human_tool_scores, expected_tools)
    human_comment = str(row.get("human_comment") or "").strip()
    matched_tool_calls = int(round(tool_use_accuracy * max(1, len(expected_tool_calls)))) if expected_tool_calls else 0

    reference_answer = str(row.get("reference_answer") or "").strip()
    if not reference_answer:
        reference_answer = str(row.get("answer") or base_row.get("reference_answer") or "").strip()
    answer_text = str(row.get("answer") or reference_answer).strip()
    if not answer_text:
        answer_text = reference_answer
    label_score = _to_binary_label(final_quality)

    output: Dict[str, Any] = {
        "id": item_id,
        "query": query,
        # 作为 grader 样本时优先消费 answer/response/label_score 三个字段。
        "answer": answer_text,
        "response": answer_text,
        "label_score": label_score,
        "label_score_raw": final_quality,
        "category": str(base_row.get("category") or ""),
        "difficulty": str(base_row.get("difficulty") or ""),
        "expected_tools": expected_tools,
        "expected_tool_calls": expected_tool_calls,
        "tags": list(base_row.get("tags") or []),
        "reference_answer": reference_answer,
        "status": "ok",
        "main_score": main_score,
        "overall_score": main_score,
        "tool_score": tool_score,
        "tool_score_dict": tool_score_dict,
        "scores_dim": scores_dim,
        "scores_raw": dict(scores_dim),
        "score_reasons": {
            "reasoning_planning": f"人工评分={reasoning:.3f}；判断依据见 plan_text。",
            "tool_use_accuracy": (
                f"自动计算 recall={tool_use_accuracy:.3f} "
                f"(matched={matched_tool_calls}, expected={len(expected_tool_calls)})"
            ),
            "final_response_quality": f"人工评分={final_quality:.3f}",
            "evidence_groundedness": f"人工评分={evidence_grounded:.3f}",
            "tool_score": (
                f"工具参数评分均值={tool_score:.3f}" if tool_score >= 0 else "未提供工具参数人工评分，记为 -1"
            ),
            "human_comment": human_comment,
        },
        "score_source": score_source,
        "plan_text": str(row.get("plan_text") or base_row.get("plan_text") or answers_row.get("plan_text") or ""),
        "observation_text": str(
            row.get("observation_text") or base_row.get("observation_text") or answers_row.get("observation_text") or ""
        ),
        "memory_text": str(row.get("memory_text") or base_row.get("memory_text") or answers_row.get("memory_text") or ""),
        "evidence_summary": str(
            row.get("evidence_summary") or base_row.get("evidence_summary") or answers_row.get("evidence_summary") or ""
        ),
        "tool_calls": tool_calls,
        "trace_id": str(base_row.get("trace_id") or answers_row.get("trace_id") or ""),
        "trace_source": str(base_row.get("trace_source") or trace_source_default),
    }
    return output


def convert_readable_to_gold(
    readable_path: Path,
    out_path: Path,
    base_gold_path: Path,
    answers_path: Path,
    score_source: str,
) -> int:
    """主转换流程。"""
    payload = yaml.safe_load(readable_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("gold.readable.yaml 顶层必须是对象")
    records = payload.get("records")
    if not isinstance(records, list):
        raise RuntimeError("gold.readable.yaml 缺少 records 列表")

    base_map = _load_jsonl_map(base_gold_path)
    answers_map = _load_jsonl_map(answers_path)

    rows: List[Dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        item_id = str(record.get("id") or "").strip()
        base_row = dict(base_map.get(item_id) or {})
        answers_row = dict(answers_map.get(item_id) or {})
        row = _convert_record(
            row=record,
            base_row=base_row,
            answers_row=answers_row,
            score_source=score_source,
            trace_source_default=str(answers_path),
        )
        rows.append(row)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fw:
        for row in rows:
            fw.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def build_arg_parser() -> argparse.ArgumentParser:
    """构建命令行参数。"""
    parser = argparse.ArgumentParser(description="将 gold.readable.yaml 转换为 gold.jsonl")
    parser.add_argument("--readable", default="agent/evaluate/data/gold.readable.yaml", help="人工标注 YAML 输入路径")
    parser.add_argument("--out", default="agent/evaluate/data/gold.jsonl", help="gold.jsonl 输出路径")
    parser.add_argument("--base-gold", default="agent/evaluate/data/gold.jsonl", help="旧 gold.jsonl（用于补齐元字段）")
    parser.add_argument("--answers", default="agent/evaluate/data/answers.jsonl", help="answers.jsonl（补齐 trace/观察字段）")
    parser.add_argument("--score-source", default="agent/evaluate/data/gold.readable.yaml", help="score_source 写入值")
    return parser


def main() -> int:
    """脚本入口。"""
    args = build_arg_parser().parse_args()
    count = convert_readable_to_gold(
        readable_path=Path(args.readable).resolve(),
        out_path=Path(args.out).resolve(),
        base_gold_path=Path(args.base_gold).resolve(),
        answers_path=Path(args.answers).resolve(),
        score_source=str(args.score_source),
    )
    print(f"[convert_gold_readable] 写入完成: {args.out} rows={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
