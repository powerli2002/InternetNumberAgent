"""阶段 C：生成 Rubric 并保存评分配置。"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from agent.core.config import AgentConfig
from agent.evaluate.core.grader_prompts import (
    LAST_MESSAGE_SCENARIO,
    LAST_MESSAGE_TASK_DESCRIPTION,
)

MAX_RUBRIC_QUERY_CHARS = 300
MAX_RUBRIC_RESPONSE_CHARS = 1600


def _load_dataset(path: Path) -> List[Dict[str, Any]]:
    """加载 JSON/JSONL 标注数据。"""
    if not path.exists():
        raise FileNotFoundError(f"标注数据不存在: {path}")
    if path.suffix.lower() == ".jsonl":
        rows: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fr:
            for idx, line in enumerate(fr, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"JSONL 解析失败 line={idx}: {exc}") from exc
                if not isinstance(parsed, dict):
                    raise ValueError(f"JSONL 每行必须是对象 line={idx}")
                rows.append(parsed)
        return rows

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("标注数据必须是 JSON 数组")
    return [dict(item) for item in data]


def _clip_text(text: str, max_chars: int) -> str:
    """按字符数截断文本，避免小上下文模型在 Rubric 生成时超长。"""
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n...(内容已截断)"


def _parse_label_score(value: Any) -> int | None:
    """解析 label_score，当前仅接受 0/1。"""
    try:
        score = int(float(value))
    except Exception:
        return None
    return score if score in {0, 1} else None


def _normalize_iterative_dataset(
    rows: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], Dict[str, int], int]:
    """把输入样本标准化为 Iterative Rubric 所需字段。"""
    normalized_rows: List[Dict[str, Any]] = []
    label_source_count: Dict[str, int] = {}
    clipped_count = 0

    for idx, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise RuntimeError(f"Iterative Rubric 样本必须是对象，样本索引={idx}")

        query = str(row.get("query") or "").strip()
        response = str(
            row.get("response")
            or row.get("answer")
            or row.get("reference_answer")
            or ""
        ).strip()
        if not query:
            raise RuntimeError(f"Iterative Rubric 缺少 query，样本索引={idx}")
        if not response:
            raise RuntimeError(
                f"Iterative Rubric 缺少 response/answer/reference_answer，样本索引={idx}"
            )

        label_score = _parse_label_score(row.get("label_score"))
        if label_score is None:
            raise RuntimeError(
                f"Iterative Rubric 缺少合法 label_score（仅允许 0/1），样本索引={idx}"
            )

        query_clipped = _clip_text(query, MAX_RUBRIC_QUERY_CHARS)
        response_clipped = _clip_text(response, MAX_RUBRIC_RESPONSE_CHARS)
        if query_clipped != query or response_clipped != response:
            clipped_count += 1

        normalized_row: Dict[str, Any] = {
            "query": query_clipped,
            "response": response_clipped,
            "label_score": int(label_score),
        }
        sample_id = str(row.get("id") or "").strip()
        if sample_id:
            normalized_row["id"] = sample_id

        normalized_rows.append(normalized_row)
        label_source_count["label_score"] = label_source_count.get("label_score", 0) + 1

    return normalized_rows, label_source_count, clipped_count


def build_openjudge_model(config: AgentConfig, model_name: str = ""):
    """构建 OpenJudge 使用的 LLM 模型。"""
    from openjudge.models.openai_chat_model import OpenAIChatModel

    if not config.dashscope_api_key:
        raise RuntimeError(
            "未找到 DASHSCOPE_API_KEY / OPENAI_API_KEY，无法构建评分模型"
        )

    model = (model_name or config.dashscope_model).strip()
    if not model:
        raise RuntimeError("评分模型名为空")

    return OpenAIChatModel(
        model=model,
        api_key=config.dashscope_api_key,
        base_url=config.dashscope_base_url,
        extra_body={"enable_thinking": False},
    )


def generate_rubrics(
    out_path: Path, labeled_data_path: Path | None = None, model_name: str = ""
) -> Dict[str, Any]:
    """生成 LastMessage Rubric，并保存到 JSON。"""
    from openjudge.generator.simple_rubric import (
        SimpleRubricsGenerator,
        SimpleRubricsGeneratorConfig,
    )
    from openjudge.graders.schema import GraderMode

    cfg = AgentConfig.load()
    model = build_openjudge_model(cfg, model_name=model_name)

    mode = "simple"
    sample_count = 0

    if labeled_data_path is None:
        generator = SimpleRubricsGenerator(
            SimpleRubricsGeneratorConfig(
                grader_name="last_message_quality_grader",
                model=model,
                grader_mode=GraderMode.POINTWISE,
                task_description=LAST_MESSAGE_TASK_DESCRIPTION,
                scenario=LAST_MESSAGE_SCENARIO,
                min_score=0,
                max_score=1,
            )
        )
        grader = asyncio.run(
            generator.generate(
                dataset=[],
                sample_queries=[
                    "请判断某 AS 是否存在路由劫持风险，并说明依据。",
                    "比较注册归属与 BGP 归属差异，给出结论。",
                    "统计某国家前缀规模并总结异常现象。",
                ],
            )
        )
    else:
        print(f"加载标注数据: {labeled_data_path}")
        # 仅在启用迭代 Rubric 时加载该依赖，避免无标注场景触发 sklearn 等重依赖导入。
        from openjudge.generator.iterative_rubric.generator import (
            IterativePointwiseRubricsGeneratorConfig,
            IterativeRubricsGenerator,
        )

        mode = "iterative"
        dataset_raw = _load_dataset(labeled_data_path)
        dataset, label_source_count, clipped_count = _normalize_iterative_dataset(
            dataset_raw
        )
        sample_count = len(dataset)
        if not dataset:
            raise RuntimeError("Iterative Rubric 模式要求标注数据非空")
        print(
            "[build_graders] 标注样本规范化完成: "
            f"rows={sample_count}, label_sources={label_source_count}, clipped_rows={clipped_count}"
        )

        generator = IterativeRubricsGenerator(
            IterativePointwiseRubricsGeneratorConfig(
                grader_name="last_message_quality_grader",
                model=model,
                min_score=0,
                max_score=1,
                query_specific_generate_number=2,
                enable_categorization=True,
                categories_number=4,
                task_description=LAST_MESSAGE_TASK_DESCRIPTION,
            )
        )
        grader = asyncio.run(generator.generate(dataset))

    rubrics_text = str(grader.kwargs.get("rubrics") or "").strip()
    if not rubrics_text:
        raise RuntimeError("Rubric 生成失败：返回为空")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "model": model_name or cfg.dashscope_model,
        "sample_count": sample_count,
        "last_message_rubrics": rubrics_text,
        "task_description": LAST_MESSAGE_TASK_DESCRIPTION,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    """构建命令行参数。"""
    parser = argparse.ArgumentParser(description="生成 OpenJudge 评分 Rubrics")
    parser.add_argument("--out", required=True, help="rubrics.json 输出路径")
    parser.add_argument(
        "--rubric-labeled-data",
        default="",
        help="可选标注数据路径（JSON/JSONL，要求含 label_score=0/1）",
    )
    parser.add_argument("--model", default="", help="可选覆盖评分模型名")
    return parser


def main() -> int:
    """脚本入口。"""
    # 统一在入口阶段加载 conf/.env，避免评测命令依赖手工 source。
    AgentConfig.load()
    args = build_arg_parser().parse_args()
    out_path = Path(args.out).resolve()
    labeled_data = (
        Path(args.rubric_labeled_data).resolve() if args.rubric_labeled_data else None
    )

    payload = generate_rubrics(
        out_path=out_path,
        labeled_data_path=labeled_data,
        model_name=str(args.model or "").strip(),
    )
    print(f"[build_graders] 写入完成: {out_path}")
    print(f"[build_graders] mode={payload['mode']} model={payload['model']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
