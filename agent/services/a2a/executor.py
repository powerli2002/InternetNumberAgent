"""A2A Worker 执行器。"""

from __future__ import annotations

from contextlib import nullcontext
import json
import re
import time
from typing import Any, Dict, List

from agent.core.config import AgentConfig
from agent.core.llm import LLMClient, LLMMessage
from agent.core.prompts import SUBAGENT_GRAPH_PROMPT, SUBAGENT_VERIFIER_PROMPT
from agent.core.tracing import LangSmithTracer
from agent.services.a2a.models import A2AResultEnvelope, A2AResultEvidence, A2ATaskPayload
from agent.services.mcp.client import MCPToolClient
from agent.subagents.protocol import TaskEnvelope
from agent.subagents.router import SubAgentRouter
from agent.subagents.utils import extract_json, truncate_text

_GRAPH_RELATION_WHITELIST = {
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

_ASN_REGEX = re.compile(r"\bAS\s*([0-9]{1,10})\b", flags=re.IGNORECASE)


class WorkerExecutor:
    """A2A 任务执行器。"""

    def __init__(self, config: AgentConfig, tracer: LangSmithTracer) -> None:
        self.config = config
        self.tracer = tracer
        self.llm = LLMClient(
            api_key=config.dashscope_api_key,
            base_url=config.dashscope_base_url,
            model=config.dashscope_model,
        )
        self.mcp_client = MCPToolClient(
            server_url=config.mcp_server_url,
            timeout_seconds=config.mcp_timeout_seconds,
            tracer=tracer,
        )
        self.router = SubAgentRouter(llm=self.llm, tracer=tracer)

    def execute(self, payload: A2ATaskPayload, root_run=None) -> A2AResultEnvelope:
        """执行单个 A2A 任务。"""
        handlers = {
            "supervisor": self._run_supervisor,
            "sql_facts": self._run_sql_facts,
            "rag_docs": self._run_rag_docs,
            "graph_relations": self._run_graph_relations,
            "verifier": self._run_verifier,
        }
        handler = handlers.get(payload.agent)
        if not handler:
            return A2AResultEnvelope(
                status="error",
                agent=payload.agent,
                trace_id=payload.trace_id,
                errors=[f"未知 agent: {payload.agent}"],
            )
        run_ctx = (
            self.tracer.start_run(
                name=f"a2a_worker:{payload.agent}",
                run_type="tool",
                inputs={"payload": payload.model_dump(mode="json")},
                tags=["a2a", "worker", f"agent:{payload.agent}"],
                metadata={"trace_id": payload.trace_id},
                parent=root_run,
            )
            if self.tracer.enabled
            else nullcontext()
        )
        with run_ctx as run:
            result = handler(payload, root_run=run or root_run)
            if run:
                run.add_outputs({"result": result.model_dump(mode="json")})
            return result

    def _run_supervisor(self, payload: A2ATaskPayload, root_run=None) -> A2AResultEnvelope:
        """Supervisor：先路由，再依次执行子代理。"""
        task = TaskEnvelope(
            objective=payload.objective,
            constraints=payload.constraints,
            context=payload.context,
            expected_output=payload.expected_output,
            budget=payload.budget,
            trace_id=payload.trace_id,
            task_id=payload.task_id,
        )
        start = time.monotonic()
        decision = self.router.decide(task, root_run=root_run)
        results: List[A2AResultEnvelope] = []
        evidences: List[A2AResultEvidence] = []
        context = dict(payload.context)
        for step in decision.plan[: decision.max_turns]:
            merged_constraints = dict(payload.constraints)
            merged_constraints.update(step.constraints or {})
            child_payload = A2ATaskPayload(
                agent=step.agent,
                objective=step.objective,
                constraints=merged_constraints,
                context=context,
                expected_output=step.expected_output or payload.expected_output,
                budget=step.budget or payload.budget,
                trace_id=payload.trace_id,
            )
            result = self.execute(child_payload, root_run=root_run)
            results.append(result)
            context.setdefault("agent_results", []).append(result.model_dump(mode="json"))
            for item in result.evidence:
                evidences.append(item)
            if result.status != "ok":
                break

        summary_parts: List[str] = []
        for result in results:
            if result.status != "ok":
                summary_parts.append(f"[{result.agent}] 失败: {', '.join(result.errors)}")
                continue
            if result.evidence:
                summary_parts.append(f"[{result.agent}] {truncate_text(result.evidence[0].content, 280)}")
            else:
                summary_parts.append(f"[{result.agent}] 已执行。")
        summary = "\n".join(summary_parts) if summary_parts else "未执行子代理。"
        return A2AResultEnvelope(
            status="ok",
            agent="supervisor",
            trace_id=payload.trace_id,
            result={
                "decision": decision.to_dict(),
                "children": [item.model_dump(mode="json") for item in results],
                "summary": summary,
            },
            evidence=evidences[:8],
            metrics={"elapsed_ms": int((time.monotonic() - start) * 1000), "steps": len(results)},
        )

    def _run_sql_facts(self, payload: A2ATaskPayload, root_run=None) -> A2AResultEnvelope:
        """SQL 子代理。"""
        start = time.monotonic()
        try:
            constraints = payload.constraints if isinstance(payload.constraints, dict) else {}
            tables = constraints.get("tables")
            use_columns = bool(constraints.get("enable_column_retrieval", False))
            retried_without_columns = False
            retry_error = ""
            try:
                result = self.mcp_client.call_tool(
                    "nl2sql_query",
                    {
                        "question": payload.objective,
                        "tables": tables,
                        "enable_column_retrieval": use_columns,
                        "trace_id": payload.trace_id,
                    },
                    trace_id=payload.trace_id,
                    root_run=root_run,
                )
            except Exception as exc:
                if not use_columns:
                    raise
                # 列级检索重建较慢，超时时降级为表级检索重试一次
                retried_without_columns = True
                retry_error = str(exc)
                result = self.mcp_client.call_tool(
                    "nl2sql_query",
                    {
                        "question": payload.objective,
                        "tables": tables,
                        "enable_column_retrieval": False,
                        "trace_id": payload.trace_id,
                    },
                    trace_id=payload.trace_id,
                    root_run=root_run,
                )
            sql = str(result.get("sql", ""))
            data = result.get("result", {}) if isinstance(result, dict) else {}
            evidence = [
                A2AResultEvidence(
                    source="nl2sql",
                    content=f"SQL: {truncate_text(sql, 500)}\n结果行数: {data.get('row_count')}",
                    metadata={
                        "sql": sql,
                        "retried_without_columns": retried_without_columns,
                        "retry_error": retry_error,
                    },
                )
            ]
            return A2AResultEnvelope(
                status="ok",
                agent="sql_facts",
                trace_id=payload.trace_id,
                result=result if isinstance(result, dict) else {"data": result},
                evidence=evidence,
                metrics={"elapsed_ms": int((time.monotonic() - start) * 1000)},
            )
        except Exception as exc:
            return A2AResultEnvelope(
                status="error",
                agent="sql_facts",
                trace_id=payload.trace_id,
                errors=[str(exc)],
            )

    def _run_rag_docs(self, payload: A2ATaskPayload, root_run=None) -> A2AResultEnvelope:
        """RAG 子代理。"""
        start = time.monotonic()
        try:
            top_k = 5
            if isinstance(payload.constraints, dict):
                try:
                    top_k = max(1, int(payload.constraints.get("top_k", 5)))
                except Exception:
                    top_k = 5
            result = self.mcp_client.call_tool(
                "rag_search",
                {
                    "query": payload.objective,
                    "top_k": top_k,
                    "trace_id": payload.trace_id,
                },
                trace_id=payload.trace_id,
                root_run=root_run,
            )
            chunks = result.get("chunks", []) if isinstance(result, dict) else []
            evidence: List[A2AResultEvidence] = []
            for chunk in chunks[:3]:
                if not isinstance(chunk, dict):
                    continue
                evidence.append(
                    A2AResultEvidence(
                        source="rag",
                        content=f"来源: {chunk.get('source')}\n摘要: {truncate_text(str(chunk.get('text', '')), 280)}",
                        metadata={"source": chunk.get("source"), "score": chunk.get("score")},
                    )
                )
            return A2AResultEnvelope(
                status="ok",
                agent="rag_docs",
                trace_id=payload.trace_id,
                result=result if isinstance(result, dict) else {"data": result},
                evidence=evidence,
                metrics={"elapsed_ms": int((time.monotonic() - start) * 1000)},
            )
        except Exception as exc:
            return A2AResultEnvelope(
                status="error",
                agent="rag_docs",
                trace_id=payload.trace_id,
                errors=[str(exc)],
            )

    def _run_graph_relations(self, payload: A2ATaskPayload, root_run=None) -> A2AResultEnvelope:
        """图谱关系子代理。"""
        start = time.monotonic()
        try:
            cypher = self._generate_cypher(payload)
            result = self.mcp_client.call_tool(
                "neo4j_query",
                {
                    "cypher": cypher,
                    "max_rows": payload.constraints.get("max_rows"),
                    "trace_id": payload.trace_id,
                },
                trace_id=payload.trace_id,
                root_run=root_run,
            )
            evidence = [
                A2AResultEvidence(
                    source="neo4j",
                    content=f"Cypher: {truncate_text(cypher, 400)}\n返回行数: {result.get('row_count') if isinstance(result, dict) else 'unknown'}",
                    metadata={"cypher": cypher},
                )
            ]
            return A2AResultEnvelope(
                status="ok",
                agent="graph_relations",
                trace_id=payload.trace_id,
                result=result if isinstance(result, dict) else {"data": result},
                evidence=evidence,
                metrics={"elapsed_ms": int((time.monotonic() - start) * 1000)},
            )
        except Exception as exc:
            return A2AResultEnvelope(
                status="error",
                agent="graph_relations",
                trace_id=payload.trace_id,
                errors=[str(exc)],
            )

    def _run_verifier(self, payload: A2ATaskPayload, root_run=None) -> A2AResultEnvelope:
        """核验子代理。"""
        start = time.monotonic()
        try:
            results = payload.context.get("agent_results") if isinstance(payload.context, dict) else None
            if not results:
                result = {"verdict": "no_context", "conflicts": []}
                return A2AResultEnvelope(
                    status="ok",
                    agent="verifier",
                    trace_id=payload.trace_id,
                    result=result,
                    metrics={"elapsed_ms": int((time.monotonic() - start) * 1000)},
                )
            messages = [
                LLMMessage(role="system", content=SUBAGENT_VERIFIER_PROMPT),
                LLMMessage(role="user", content=json.dumps(results, ensure_ascii=False)),
            ]
            content = self.llm.chat(messages)
            try:
                result = extract_json(content)
            except Exception:
                result = {"verdict": "unknown", "conflicts": [], "notes": content}
            evidence = [
                A2AResultEvidence(
                    source="verifier",
                    content=truncate_text(json.dumps(result, ensure_ascii=False), 300),
                    metadata={},
                )
            ]
            return A2AResultEnvelope(
                status="ok",
                agent="verifier",
                trace_id=payload.trace_id,
                result=result if isinstance(result, dict) else {"verdict": "unknown"},
                evidence=evidence,
                metrics={"elapsed_ms": int((time.monotonic() - start) * 1000)},
            )
        except Exception as exc:
            return A2AResultEnvelope(
                status="error",
                agent="verifier",
                trace_id=payload.trace_id,
                errors=[str(exc)],
            )

    def _generate_cypher(self, payload: A2ATaskPayload) -> str:
        """使用 LLM 生成 Cypher。"""
        messages = [
            LLMMessage(role="system", content=SUBAGENT_GRAPH_PROMPT),
            LLMMessage(role="user", content=json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)),
        ]
        content = self.llm.chat(messages)
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("cypher"):
                text = text[6:].strip()
        if "{" in text and "}" in text:
            try:
                data = extract_json(text)
                if isinstance(data, dict) and data.get("cypher"):
                    text = str(data.get("cypher")).strip()
            except Exception:
                pass
        if not text:
            return self._fallback_cypher(payload)
        if self._has_unknown_relations(text):
            return self._fallback_cypher(payload)
        return text

    def _has_unknown_relations(self, cypher: str) -> bool:
        # 只检查关系语法中的类型，避免把节点标签误判成关系类型
        bracket_segments = re.findall(r"\[[^\]]*\]", cypher)
        for segment in bracket_segments:
            if ":" not in segment:
                continue
            rel_part = segment.split(":", 1)[1]
            rel_part = rel_part.split("{", 1)[0]
            candidates = [token.strip() for token in rel_part.split("|")]
            for token in candidates:
                cleaned = token.strip("` ").split("*", 1)[0].strip()
                if not cleaned:
                    continue
                cleaned = cleaned.upper()
                if cleaned not in _GRAPH_RELATION_WHITELIST:
                    return True
        return False

    def _fallback_cypher(self, payload: A2ATaskPayload) -> str:
        constraints = payload.constraints if isinstance(payload.constraints, dict) else {}
        try:
            limit = max(1, int(constraints.get("max_rows", 50)))
        except (TypeError, ValueError):
            limit = 50
        if limit > 200:
            limit = 200
        question = payload.objective
        if isinstance(payload.context, dict) and payload.context.get("question"):
            question = f"{payload.context.get('question')} {question}"
        asn_match = _ASN_REGEX.search(question or "")
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
