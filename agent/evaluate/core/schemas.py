"""评测数据契约与 JSONL 序列化工具。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _require_non_empty_str(name: str, value: Any) -> str:
    """校验字符串字段非空。"""
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"字段 {name} 不能为空")
    return text


def _as_list(value: Any) -> List[Any]:
    """把输入转换为列表，非法值抛错。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("目标字段必须为 list")
    return value


@dataclass
class QuerySample:
    """阶段 A 生成的题目样本。"""

    id: str
    query: str
    category: str
    difficulty: str
    expected_tools: List[str] = field(default_factory=list)
    expected_tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    reference_answer: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuerySample":
        """从字典构建 QuerySample 并进行字段校验。"""
        expected_tools = [str(item).strip() for item in _as_list(data.get("expected_tools")) if str(item).strip()]
        expected_tool_calls_raw = _as_list(data.get("expected_tool_calls"))
        expected_tool_calls: List[Dict[str, Any]] = []
        for item in expected_tool_calls_raw:
            if not isinstance(item, dict):
                raise ValueError("expected_tool_calls 元素必须为对象")
            expected_tool_calls.append(item)
        tags = [str(item).strip() for item in _as_list(data.get("tags")) if str(item).strip()]
        return cls(
            id=_require_non_empty_str("id", data.get("id")),
            query=_require_non_empty_str("query", data.get("query")),
            category=_require_non_empty_str("category", data.get("category")),
            difficulty=_require_non_empty_str("difficulty", data.get("difficulty")),
            expected_tools=expected_tools,
            expected_tool_calls=expected_tool_calls,
            tags=tags,
            reference_answer=str(data.get("reference_answer") or ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        return asdict(self)


@dataclass
class AnswerSample:
    """阶段 B 生成的回答样本。"""

    id: str
    query: str
    answer: str
    status: str
    error: str = ""
    trace_id: str = ""
    agent_metadata: Dict[str, Any] = field(default_factory=dict)
    node_records: List[Dict[str, Any]] = field(default_factory=list)
    final_state_output: Dict[str, Any] = field(default_factory=dict)
    main_flow_trace: Dict[str, Any] = field(default_factory=dict)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    trajectory_messages: List[Dict[str, Any]] = field(default_factory=list)
    plan_text: str = ""
    observation_text: str = ""
    memory_text: str = ""
    evidence_items: List[Dict[str, Any]] = field(default_factory=list)
    evidence_summary: str = ""
    expected_tools: List[str] = field(default_factory=list)
    expected_tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    reference_answer: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnswerSample":
        """从字典构建 AnswerSample 并进行字段校验。"""
        status = _require_non_empty_str("status", data.get("status"))
        if status not in {"ok", "error"}:
            raise ValueError("status 只能是 ok 或 error")
        return cls(
            id=_require_non_empty_str("id", data.get("id")),
            query=_require_non_empty_str("query", data.get("query")),
            answer=str(data.get("answer") or ""),
            status=status,
            error=str(data.get("error") or ""),
            trace_id=str(data.get("trace_id") or ""),
            agent_metadata=dict(data.get("agent_metadata") or {}),
            node_records=list(data.get("node_records") or []),
            final_state_output=dict(data.get("final_state_output") or {}),
            main_flow_trace=dict(data.get("main_flow_trace") or {}),
            tool_calls=list(data.get("tool_calls") or []),
            trajectory_messages=list(data.get("trajectory_messages") or []),
            plan_text=str(data.get("plan_text") or ""),
            observation_text=str(data.get("observation_text") or ""),
            memory_text=str(data.get("memory_text") or ""),
            evidence_items=list(data.get("evidence_items") or []),
            evidence_summary=str(data.get("evidence_summary") or ""),
            expected_tools=list(data.get("expected_tools") or []),
            expected_tool_calls=list(data.get("expected_tool_calls") or []),
            reference_answer=str(data.get("reference_answer") or ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        return asdict(self)


@dataclass
class ScoredSample:
    """阶段 D 输出的评分样本。"""

    id: str
    query: str
    answer: str
    status: str
    error: str = ""
    scores_raw: Dict[str, float] = field(default_factory=dict)
    scores_dim: Dict[str, float] = field(default_factory=dict)
    overall_score: float = 0.0
    score_reasons: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScoredSample":
        """从字典构建 ScoredSample 并进行字段校验。"""
        return cls(
            id=_require_non_empty_str("id", data.get("id")),
            query=_require_non_empty_str("query", data.get("query")),
            answer=str(data.get("answer") or ""),
            status=_require_non_empty_str("status", data.get("status")),
            error=str(data.get("error") or ""),
            scores_raw={str(k): float(v) for k, v in dict(data.get("scores_raw") or {}).items()},
            scores_dim={str(k): float(v) for k, v in dict(data.get("scores_dim") or {}).items()},
            overall_score=float(data.get("overall_score") or 0.0),
            score_reasons={str(k): str(v) for k, v in dict(data.get("score_reasons") or {}).items()},
        )

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        return asdict(self)


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    """写入 JSONL 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fw:
        for row in rows:
            fw.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    """读取 JSONL 文件。"""
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fr:
        for idx, line in enumerate(fr, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL 解析失败 line={idx}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"JSONL 每行必须是对象 line={idx}")
            rows.append(row)
    return rows


def load_query_samples(path: Path) -> List[QuerySample]:
    """从 JSONL 加载 QuerySample 列表。"""
    return [QuerySample.from_dict(item) for item in read_jsonl(path)]


def load_answer_samples(path: Path) -> List[AnswerSample]:
    """从 JSONL 加载 AnswerSample 列表。"""
    return [AnswerSample.from_dict(item) for item in read_jsonl(path)]


def load_scored_samples(path: Path) -> List[ScoredSample]:
    """从 JSONL 加载 ScoredSample 列表。"""
    return [ScoredSample.from_dict(item) for item in read_jsonl(path)]
