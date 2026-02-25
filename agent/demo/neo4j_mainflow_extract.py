"""
从主调用链抽取的 Neo4j 图查询单文件 Demo（直连驱动版）。

目标：
1. 复用 graph_relations 子代理的 Cypher 生成逻辑；
2. 复用关系白名单校验与 fallback 策略；
3. 通过 Neo4jQueryTool 直接执行只读查询；
4. 提供 CLI 入口，输出统一 JSON 结果。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


# 直接脚本启动时，确保从项目根目录解析 `agent.*` 包。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_module_from_path(module_name: str, file_path: Path):
    """按文件路径加载模块，避免触发 agent 包级导入副作用。"""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_config_module = _load_module_from_path(
    "neo4j_extract_agent_config",
    PROJECT_ROOT / "agent" / "core" / "config.py",
)
_llm_module = _load_module_from_path(
    "neo4j_extract_agent_llm",
    PROJECT_ROOT / "agent" / "core" / "llm.py",
)
_prompts_module = _load_module_from_path(
    "neo4j_extract_agent_prompts",
    PROJECT_ROOT / "agent" / "core" / "prompts.py",
)
_neo4j_tool_module = _load_module_from_path(
    "neo4j_extract_query_tool",
    PROJECT_ROOT / "agent" / "tools" / "neo4j_query_tool.py",
)

AgentConfig = _config_module.AgentConfig
LLMClient = _llm_module.LLMClient
LLMMessage = _llm_module.LLMMessage
SUBAGENT_GRAPH_PROMPT = _prompts_module.SUBAGENT_GRAPH_PROMPT
Neo4jQueryTool = _neo4j_tool_module.Neo4jQueryTool


GRAPH_RELATION_WHITELIST = {
    "BELONGS_TO",
    "LOCATED_IN",
    "BGP_ORIGIN",
    "REG_ORIGIN",
    "REGISTERED_TO",
    "OBSERVED_ORG",
    "IN_COUNTRY",
    "RESOLVES_TO",
    "AUTH_RESOLVES_TO",
    "IN_INDUSTRY",
    "PARENT_OF",
    "V4_UPSTREAM",
    "V4_PEER",
    "V4_DOWNSTREAM",
    "V6_UPSTREAM",
    "V6_PEER",
    "V6_DOWNSTREAM",
}

ASN_REGEX = re.compile(r"\bAS\s*([0-9]{1,10})\b", flags=re.IGNORECASE)


@dataclass
class GraphTaskPayload:
    """图查询任务载荷（与主链路最小兼容）。"""

    objective: str
    constraints: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    expected_output: str = "结构化结果 + 证据摘要"
    budget: Dict[str, Any] = field(default_factory=lambda: {"max_tokens": 1200, "max_time_ms": 15000})
    trace_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为 JSON 可序列化字典。"""
        return {
            "objective": self.objective,
            "constraints": self.constraints,
            "context": self.context,
            "expected_output": self.expected_output,
            "budget": self.budget,
            "trace_id": self.trace_id,
        }


class Neo4jMainFlowExtractor:
    """Neo4j 主流程抽取执行器（最小闭环）。"""

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        neo4j_uri: Optional[str] = None,
        neo4j_user: Optional[str] = None,
        neo4j_password: Optional[str] = None,
        default_max_rows: int = 200,
    ) -> None:
        self.config = config or AgentConfig.load(project_root=PROJECT_ROOT)
        self.default_max_rows = max(1, int(default_max_rows))
        self.llm = LLMClient(
            api_key=self.config.dashscope_api_key,
            base_url=self.config.dashscope_base_url,
            model=self.config.dashscope_model,
        )
        self.neo4j_uri = str(neo4j_uri or self.config.neo4j_uri)
        self.neo4j_user = str(neo4j_user or self.config.neo4j_user)
        self.neo4j_password = str(neo4j_password or self.config.neo4j_password)
        self.graph_tool = Neo4jQueryTool(
            uri=self.neo4j_uri,
            user=self.neo4j_user,
            password=self.neo4j_password,
            max_rows=self.default_max_rows,
            max_cypher_length=self.config.graph_max_cypher_length,
        )

    def run(self, question: str, max_rows: int | None = None, use_llm: bool = True) -> Dict[str, Any]:
        """执行完整流程：生成 Cypher -> 校验/降级 -> 查询。"""
        clean_question = (question or "").strip()
        if not clean_question:
            raise ValueError("question 不能为空。")

        effective_max_rows = self._normalize_max_rows(max_rows if max_rows is not None else self.default_max_rows)
        payload = GraphTaskPayload(
            objective=clean_question,
            constraints={"max_rows": effective_max_rows},
            context={"question": clean_question},
        )
        cypher, used_fallback, fallback_reason = self._generate_cypher(payload, use_llm=use_llm)
        result = self.graph_tool.query(cypher, max_rows=effective_max_rows)

        return {
            "question": clean_question,
            "cypher": cypher,
            "result": result,
            "used_fallback": used_fallback,
            "fallback_reason": fallback_reason,
            "meta": {
                "max_rows": effective_max_rows,
                "relation_whitelist_size": len(GRAPH_RELATION_WHITELIST),
                "use_llm_requested": bool(use_llm),
                "neo4j_uri": self.neo4j_uri,
            },
        }

    def _generate_cypher(self, payload: GraphTaskPayload, use_llm: bool) -> Tuple[str, bool, str]:
        """生成 Cypher，失败或不安全时回退到模板查询。"""
        if not use_llm:
            return self._fallback_cypher(payload), True, "llm_disabled"

        messages = [
            LLMMessage(role="system", content=SUBAGENT_GRAPH_PROMPT),
            LLMMessage(role="user", content=json.dumps(payload.to_dict(), ensure_ascii=False)),
        ]
        try:
            content = self.llm.chat(messages)
        except Exception as exc:
            return self._fallback_cypher(payload), True, f"llm_error: {exc}"

        text = self._normalize_llm_output(content)
        if not text:
            return self._fallback_cypher(payload), True, "empty_cypher"
        if self._has_unknown_relations(text):
            return self._fallback_cypher(payload), True, "unknown_relation_type"
        return text, False, ""

    @staticmethod
    def _normalize_llm_output(content: str) -> str:
        """将模型输出规整为纯 Cypher。"""
        text = (content or "").strip()
        if not text:
            return ""

        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text, flags=re.IGNORECASE).strip()
            if text.lower().startswith("cypher"):
                text = text[6:].strip()

        json_payload = Neo4jMainFlowExtractor._extract_json_object(text)
        if isinstance(json_payload, dict) and json_payload.get("cypher"):
            return str(json_payload.get("cypher", "")).strip()

        return text.strip()

    @staticmethod
    def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
        """从文本中提取第一个可解析 JSON 对象。"""
        candidates = re.findall(r"\{[\s\S]*\}", text)
        for raw in candidates:
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            if isinstance(payload, dict):
                return payload
        return None

    @staticmethod
    def _has_unknown_relations(cypher: str) -> bool:
        """检查关系类型是否全部在白名单中。"""
        bracket_segments = re.findall(r"\[[^\]]*\]", cypher)
        for segment in bracket_segments:
            if ":" not in segment:
                continue
            rel_part = segment.split(":", 1)[1]
            rel_part = rel_part.split("{", 1)[0]
            candidates = [token.strip() for token in rel_part.split("|")]
            for token in candidates:
                cleaned = token.strip("` []").split("*", 1)[0].strip("` []")
                if not cleaned:
                    continue
                if cleaned.upper() not in GRAPH_RELATION_WHITELIST:
                    return True
        return False

    @staticmethod
    def _normalize_max_rows(value: int) -> int:
        """统一 max_rows 约束，上限保持与主链路一致。"""
        normalized = max(1, int(value))
        return min(normalized, 200)

    def _fallback_cypher(self, payload: GraphTaskPayload) -> str:
        """主链路同款 fallback 逻辑。"""
        constraints = payload.constraints if isinstance(payload.constraints, dict) else {}
        try:
            limit = self._normalize_max_rows(int(constraints.get("max_rows", 50)))
        except (TypeError, ValueError):
            limit = 50
        question = payload.objective
        if isinstance(payload.context, dict) and payload.context.get("question"):
            question = f"{payload.context.get('question')} {question}"
        asn_match = ASN_REGEX.search(question or "")
        asn = asn_match.group(1) if asn_match else ""
        lowered = (question or "").lower()

        if asn and ("上游" in question or "upstream" in lowered):
            return (
                f"MATCH (a:AS {{asn: {asn}}})-[:V4_UPSTREAM]->(up:AS) "
                "RETURN a.asn AS target_asn, up.asn AS upstream_asn, up.org_name AS upstream_org "
                f"LIMIT {limit}"
            )
        if asn and ("下游" in question or "downstream" in lowered):
            return (
                f"MATCH (a:AS {{asn: {asn}}})-[:V4_DOWNSTREAM]->(down:AS) "
                "RETURN a.asn AS target_asn, down.asn AS downstream_asn, down.org_name AS downstream_org "
                f"LIMIT {limit}"
            )
        if asn and ("对等" in question or "peer" in lowered):
            return (
                f"MATCH (a:AS {{asn: {asn}}})-[:V4_PEER]->(peer:AS) "
                "RETURN a.asn AS target_asn, peer.asn AS peer_asn, peer.org_name AS peer_org "
                f"LIMIT {limit}"
            )
        if asn:
            return (
                f"MATCH (a:AS {{asn: {asn}}})-[:BELONGS_TO]->(o:Org) "
                "RETURN a.asn AS asn, o.org_name AS org_name, o.uuid AS org_uuid "
                f"LIMIT {limit}"
            )
        return (
            "MATCH (a:AS)-[:V4_UPSTREAM]->(up:AS) "
            "RETURN a.asn AS target_asn, up.asn AS upstream_asn, up.org_name AS upstream_org "
            f"LIMIT {limit}"
        )


def _parse_bool(value: str) -> bool:
    """解析 CLI 布尔字符串。"""
    lowered = str(value or "").strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"非法布尔值: {value}")


def build_arg_parser() -> argparse.ArgumentParser:
    """构建命令行参数。"""
    parser = argparse.ArgumentParser(description="抽取版 Neo4j 主流程 Demo（直连驱动）。")
    parser.add_argument("--question", required=True, help="自然语言问题。")
    parser.add_argument("--max-rows", type=int, default=200, help="最大返回行数（默认 200）。")
    parser.add_argument("--neo4j-uri", default="", help="覆盖 Neo4j URI。")
    parser.add_argument("--neo4j-user", default="", help="覆盖 Neo4j 用户名。")
    parser.add_argument("--neo4j-password", default="", help="覆盖 Neo4j 密码。")
    parser.add_argument("--use-llm", type=_parse_bool, default=True, help="是否启用 LLM 生成 Cypher（true/false）。")
    parser.add_argument("--pretty", action="store_true", help="美化 JSON 输出。")
    return parser


def main() -> int:
    """CLI 入口。"""
    args = build_arg_parser().parse_args()
    cfg = AgentConfig.load(project_root=PROJECT_ROOT)
    extractor = Neo4jMainFlowExtractor(
        config=cfg,
        neo4j_uri=args.neo4j_uri or None,
        neo4j_user=args.neo4j_user or None,
        neo4j_password=args.neo4j_password or None,
        default_max_rows=max(1, int(args.max_rows)),
    )
    payload = extractor.run(
        question=args.question,
        max_rows=max(1, int(args.max_rows)),
        use_llm=bool(args.use_llm),
    )
    if args.pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
