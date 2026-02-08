"""子代理 Supervisor：执行 RouterDecision 并聚合结果。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agent.core.llm import LLMClient
from agent.core.tracing import LangSmithTracer
from agent.subagents.agents import GraphRelationsAgent, RagDocsAgent, SQLFactsAgent, VerifierAgent
from agent.subagents.protocol import ResultEnvelope, ResultEvidence, RouterDecision, TaskEnvelope
from agent.subagents.router import SubAgentRouter
from agent.subagents.utils import truncate_text
from agent.tools.nl2sql_tool import NL2SQLTool
from agent.tools.rag_tool import RAGTool
from agent.tools.neo4j_query_tool import Neo4jQueryTool


@dataclass
class SubAgentExecution:
    """Supervisor 执行后的聚合结果。"""

    results: List[ResultEnvelope]
    summary: str
    sources: List[str]
    decision: RouterDecision
    trace_id: str


class SubAgentSupervisor:
    """Supervisor / Orchestrator 统一调度子代理。"""

    def __init__(
        self,
        llm: LLMClient,
        nl2sql_tool: NL2SQLTool,
        rag_tool: RAGTool,
        graph_tool: Optional[Neo4jQueryTool] = None,
        tracer: Optional[LangSmithTracer] = None,
        max_turns: int = 4,
    ) -> None:
        self.llm = llm
        self.tracer = tracer
        self.max_turns = max(1, int(max_turns))
        self.router = SubAgentRouter(llm=llm, tracer=tracer)
        # 子代理注册表
        self.registry = {
            "sql_facts": SQLFactsAgent(nl2sql_tool),
            "rag_docs": RagDocsAgent(rag_tool),
            "graph_relations": GraphRelationsAgent(llm, graph_tool),
            "verifier": VerifierAgent(llm),
        }

    def execute(self, task: TaskEnvelope, root_run=None) -> SubAgentExecution:
        """执行子代理计划，输出聚合结果。"""
        start = time.monotonic()
        # 生成路由决策
        decision = self.router.decide(task, root_run=root_run)
        results: List[ResultEnvelope] = []
        sources: List[str] = []
        context = dict(task.context)
        # 顺序执行计划，不做并行
        for idx, step in enumerate(decision.plan[: self.max_turns]):
            merged_constraints = dict(task.constraints)
            merged_constraints.update(step.constraints or {})
            step_envelope = TaskEnvelope(
                objective=step.objective,
                constraints=merged_constraints,
                context=context,
                expected_output=step.expected_output or task.expected_output,
                budget=step.budget or task.budget,
                trace_id=task.trace_id,
                task_id=task.task_id,
            )
            agent = self.registry.get(step.agent)
            if not agent:
                result = ResultEnvelope.error(step.agent, "子代理未注册", trace_id=task.trace_id)
            else:
                if self.tracer and self.tracer.enabled and root_run:
                    with self.tracer.start_run(
                        name=f"subagent_{step.agent}",
                        run_type="tool",
                        inputs={"task": step_envelope.to_dict()},
                        tags=["subagent", step.agent],
                        metadata={"trace_id": task.trace_id, "plan_index": idx},
                        parent=root_run,
                    ) as run:
                        result = agent.run(step_envelope)
                        run.add_outputs({"status": result.status, "agent": result.agent})
                else:
                    result = agent.run(step_envelope)
            results.append(result)
            sources.extend(self._collect_sources(result))
            # 将结果注入上下文，供后续子代理使用
            context.setdefault("agent_results", []).append(result.to_dict())
            if result.status != "ok":
                # 错误时提前停止，避免无谓消耗
                break
        summary = self._build_summary(results)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        if results:
            results[-1].metrics.setdefault("supervisor_elapsed_ms", elapsed_ms)
        return SubAgentExecution(
            results=results,
            summary=summary,
            sources=list(dict.fromkeys(sources)),
            decision=decision,
            trace_id=task.trace_id,
        )

    @staticmethod
    def _collect_sources(result: ResultEnvelope) -> List[str]:
        sources: List[str] = []
        for item in result.evidence:
            source = item.metadata.get("source") if isinstance(item.metadata, dict) else None
            if not source:
                source = item.source
            if source:
                sources.append(str(source))
        return sources

    @staticmethod
    def _build_summary(results: List[ResultEnvelope]) -> str:
        """将多个 ResultEnvelope 合并为简短摘要。"""
        if not results:
            return "未执行子代理。"
        parts: List[str] = []
        for result in results:
            if result.status != "ok":
                parts.append(f"[{result.agent}] 执行失败: {', '.join(result.errors)}")
                continue
            if result.evidence:
                for evidence in result.evidence[:2]:
                    parts.append(f"[{result.agent}] {truncate_text(evidence.content, 400)}")
            else:
                parts.append(f"[{result.agent}] 已完成，未返回证据摘要。")
        return "\n".join(parts)
