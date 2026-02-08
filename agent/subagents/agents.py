"""子代理实现集合。"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from agent.core.llm import LLMClient, LLMMessage
from agent.core.prompts import SUBAGENT_GRAPH_PROMPT, SUBAGENT_VERIFIER_PROMPT
from agent.subagents.protocol import ResultEnvelope, ResultEvidence, TaskEnvelope
from agent.subagents.utils import extract_json, truncate_text
from agent.tools.nl2sql_tool import NL2SQLTool
from agent.tools.rag_tool import RAGTool
from agent.tools.neo4j_query_tool import Neo4jQueryTool


class BaseSubAgent:
    """子代理基类。"""

    name: str = "base"

    def run(self, task: TaskEnvelope) -> ResultEnvelope:  # pragma: no cover - 接口占位
        raise NotImplementedError


class SQLFactsAgent(BaseSubAgent):
    """结构化事实子代理，负责调用 NL2SQL。"""

    name = "sql_facts"

    def __init__(self, nl2sql_tool: NL2SQLTool) -> None:
        self.nl2sql_tool = nl2sql_tool

    def run(self, task: TaskEnvelope) -> ResultEnvelope:
        start = time.monotonic()
        try:
            question = self._build_question(task)
            tables = task.constraints.get("tables") or None
            result = self.nl2sql_tool.query(question, tables=tables)
            payload = {
                "sql": result.sql,
                "data": result.result,
            }
            evidence = [
                ResultEvidence(
                    source="nl2sql",
                    content=f"SQL: {truncate_text(result.sql, 500)}\n结果行数: {result.result.get('row_count')}",
                    metadata={"sql": result.sql},
                )
            ]
            return ResultEnvelope.ok(
                agent=self.name,
                result=payload,
                evidence=evidence,
                trace_id=task.trace_id,
                metrics={"elapsed_ms": int((time.monotonic() - start) * 1000)},
            )
        except Exception as exc:
            return ResultEnvelope.error(self.name, str(exc), trace_id=task.trace_id)

    @staticmethod
    def _build_question(task: TaskEnvelope) -> str:
        """将任务目标与上下文拼接成 NL2SQL 输入。"""
        parts = [task.objective]
        context_question = task.context.get("question") if isinstance(task.context, dict) else None
        if context_question:
            parts.append(f"补充问题: {context_question}")
        intent = task.context.get("intent") if isinstance(task.context, dict) else None
        if intent:
            parts.append(f"任务意图: {intent}")
        return "\n".join(parts)


class RagDocsAgent(BaseSubAgent):
    """文档检索子代理，负责调用 RAGTool。"""

    name = "rag_docs"

    def __init__(self, rag_tool: RAGTool, default_top_k: int = 5) -> None:
        self.rag_tool = rag_tool
        self.default_top_k = default_top_k

    def run(self, task: TaskEnvelope) -> ResultEnvelope:
        start = time.monotonic()
        try:
            query = self._build_query(task)
            top_k = int(task.constraints.get("top_k") or self.default_top_k)
            chunks = self.rag_tool.search(query, top_k=top_k)
            payload = {
                "query": query,
                "top_k": top_k,
                "chunks": [
                    {"text": chunk.text, "source": chunk.source, "score": chunk.metadata.get("score")}
                    for chunk in chunks
                ],
            }
            evidence: List[ResultEvidence] = []
            for chunk in chunks[:3]:
                evidence.append(
                    ResultEvidence(
                        source="rag",
                        content=f"来源: {chunk.source}\n摘要: {truncate_text(chunk.text, 300)}",
                        metadata={"source": chunk.source, "score": chunk.metadata.get("score")},
                    )
                )
            return ResultEnvelope.ok(
                agent=self.name,
                result=payload,
                evidence=evidence,
                trace_id=task.trace_id,
                metrics={"elapsed_ms": int((time.monotonic() - start) * 1000)},
            )
        except Exception as exc:
            return ResultEnvelope.error(self.name, str(exc), trace_id=task.trace_id)

    @staticmethod
    def _build_query(task: TaskEnvelope) -> str:
        parts = [task.objective]
        context_question = task.context.get("question") if isinstance(task.context, dict) else None
        if context_question:
            parts.append(context_question)
        intent = task.context.get("intent") if isinstance(task.context, dict) else None
        if intent:
            parts.append(intent)
        return "\n".join(parts)


class GraphRelationsAgent(BaseSubAgent):
    """关系图谱子代理，负责生成并执行 Cypher。"""

    name = "graph_relations"

    def __init__(self, llm: LLMClient, graph_tool: Optional[Neo4jQueryTool]) -> None:
        self.llm = llm
        self.graph_tool = graph_tool

    def run(self, task: TaskEnvelope) -> ResultEnvelope:
        start = time.monotonic()
        if not self.graph_tool:
            return ResultEnvelope.error(self.name, "Neo4j 未配置，无法执行图谱查询。", trace_id=task.trace_id)
        try:
            cypher = self._generate_cypher(task)
            max_rows = task.constraints.get("max_rows")
            payload = self.graph_tool.query(cypher, max_rows=max_rows)
            evidence = [
                ResultEvidence(
                    source="neo4j",
                    content=f"Cypher: {truncate_text(cypher, 400)}\n返回行数: {payload.get('row_count')}",
                    metadata={"cypher": cypher},
                )
            ]
            return ResultEnvelope.ok(
                agent=self.name,
                result=payload,
                evidence=evidence,
                trace_id=task.trace_id,
                metrics={"elapsed_ms": int((time.monotonic() - start) * 1000)},
            )
        except Exception as exc:
            return ResultEnvelope.error(self.name, str(exc), trace_id=task.trace_id)

    def _generate_cypher(self, task: TaskEnvelope) -> str:
        """使用 LLM 生成 Cypher 查询。"""
        prompt = SUBAGENT_GRAPH_PROMPT
        messages = [
            LLMMessage(role="system", content=prompt),
            LLMMessage(role="user", content=json.dumps(task.to_dict(), ensure_ascii=False)),
        ]
        content = self.llm.chat(messages)
        # 允许模型输出代码块，提取其中内容
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("cypher"):
                text = text[6:].strip()
        # 若返回 JSON，则尝试解析
        if "{" in text and "}" in text:
            try:
                data = extract_json(text)
                if isinstance(data, dict) and data.get("cypher"):
                    return str(data["cypher"]).strip()
            except Exception:
                pass
        return text


class VerifierAgent(BaseSubAgent):
    """可选核验子代理，用于冲突检测。"""

    name = "verifier"

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(self, task: TaskEnvelope) -> ResultEnvelope:
        start = time.monotonic()
        try:
            results = task.context.get("agent_results") if isinstance(task.context, dict) else None
            if not results:
                return ResultEnvelope.ok(
                    agent=self.name,
                    result={"verdict": "no_context", "conflicts": []},
                    trace_id=task.trace_id,
                    metrics={"elapsed_ms": int((time.monotonic() - start) * 1000)},
                )
            messages = [
                LLMMessage(role="system", content=SUBAGENT_VERIFIER_PROMPT),
                LLMMessage(role="user", content=json.dumps(results, ensure_ascii=False)),
            ]
            content = self.llm.chat(messages)
            try:
                data = extract_json(content)
            except Exception:
                data = {"verdict": "unknown", "conflicts": [], "notes": content}
            evidence = [
                ResultEvidence(
                    source="verifier",
                    content=truncate_text(json.dumps(data, ensure_ascii=False), 400),
                    metadata={},
                )
            ]
            return ResultEnvelope.ok(
                agent=self.name,
                result=data if isinstance(data, dict) else {"verdict": "unknown"},
                evidence=evidence,
                trace_id=task.trace_id,
                metrics={"elapsed_ms": int((time.monotonic() - start) * 1000)},
            )
        except Exception as exc:
            return ResultEnvelope.error(self.name, str(exc), trace_id=task.trace_id)
