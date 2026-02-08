"""
互联网号码资源问答系统 - MCP + A2A 主智能体

核心原则：
1. 工具调用全部走 FastMCP（HTTP）。
2. 子代理任务全部走 A2A（HTTP+SSE）。
3. 全链路统一写入 LangSmith 追踪。
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Dict, Iterable, List, Optional, Tuple

from agent.context import ContextBuilder
from agent.core.config import AgentConfig
from agent.core.llm import LLMClient, LLMMessage
from agent.core.models import ConversationTurn, EvidenceItem, MemoryItem, TodoItem
from agent.core.prompts import (
    SEMANTIC_EXTRACT_PROMPT,
    STEP_ACTOR_PROMPT,
    SYSTEM_PROMPT,
    TODO_PLANNER_PROMPT,
    TOOL_ROUTER_PROMPT,
)
from agent.core.tracing import LangSmithTracer
from agent.mcp.client import MCPToolClient
from agent.memory import EpisodicMemory, MemoryManager, SemanticMemory, WorkingMemory
from agent.memory.semantic import SemanticRecord
from agent.protocols.a2a.client import A2AClient
from agent.protocols.a2a.models import A2AResultEnvelope, A2ATaskPayload
from agent.runtime.tool_router_protocol import ToolActionStep, ToolPlanStep, ToolRouterDecision, allowed_tool_names
from agent.runtime.tool_router_schemas import step_router_schema, tool_router_schema
from src.utils.logging_manager import logger


MODULE_LOG_ENABLED = os.getenv("MODULE_LOG_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
MODULE_LOG_BODY_LIMIT = max(256, int(os.getenv("MODULE_LOG_BODY_LIMIT", "2000")))
MODULE_LOG_MAX_ITEMS = max(1, int(os.getenv("MODULE_LOG_MAX_ITEMS", "5")))

_A2A_ALLOWED_AGENTS = ["graph_relations", "rag_docs", "sql_facts", "verifier"]


def _preview_text(text: str, limit: int) -> str:
    """截断长文本，避免日志过长。"""
    if text is None:
        return ""
    raw = str(text)
    if len(raw) > limit:
        return f"{raw[:limit]}...<truncated {len(raw)} chars>"
    return raw


def _log_module_io(name: str, input_data: dict, output_data: dict) -> None:
    """统一记录模块输入输出，使用结构化 JSON 便于排查。"""
    if not MODULE_LOG_ENABLED:
        return
    payload = {
        "module": name,
        "input": input_data,
        "output": output_data,
    }
    logger.info("MODULE_IO %s", json.dumps(payload, ensure_ascii=False))


class FusionAgent:
    """融合智能体主类（MCP/A2A 版本）。"""

    def __init__(self, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.load()
        self.tracer = LangSmithTracer()
        self.llm = LLMClient(
            api_key=self.config.dashscope_api_key,
            base_url=self.config.dashscope_base_url,
            model=self.config.dashscope_model,
        )
        self.context_builder = ContextBuilder(max_tokens=self.config.max_context_tokens)

        self.semantic_memory_enabled = self.config.semantic_memory_enabled
        self.semantic_memory_max_items = self.config.semantic_memory_max_items
        self.semantic_memory_min_importance = self.config.semantic_memory_min_importance

        memory_dir = self.config.project_root / "agent" / "memory_store"
        self.memory_manager = MemoryManager(
            working_memory=WorkingMemory(capacity=self.config.working_memory_size),
            episodic_memory=EpisodicMemory(
                sqlite_path=memory_dir / "episodic.sqlite",
                capacity=self.config.episodic_memory_size,
                postgres_url=self.config.postgres_url,
            ),
            semantic_memory=SemanticMemory(
                uri=self.config.neo4j_uri,
                user=self.config.neo4j_user,
                password=self.config.neo4j_password,
            ),
        )

        # 工具层统一走 MCP，子代理统一走 A2A。
        self.mcp_client = MCPToolClient(
            server_url=self.config.mcp_server_url,
            timeout_seconds=self.config.mcp_timeout_seconds,
            tracer=self.tracer,
        )
        self.a2a_client = A2AClient(
            base_url=self.config.a2a_server_url,
            timeout_seconds=self.config.a2a_timeout_seconds,
            tracer=self.tracer,
        )

    def respond(self, user_message: str, history: Optional[List[ConversationTurn]] = None) -> Tuple[str, dict]:
        """处理用户问题并返回完整回答。"""
        history = history or []
        trace_id = str(uuid.uuid4())
        if self.tracer.enabled:
            with self.tracer.start_run(
                name="fusion_agent",
                run_type="chain",
                inputs={"question": user_message},
                tags=["fusion", "qa"],
                metadata={"question_type": self._classify_question(user_message), "trace_id": trace_id},
            ) as root_run:
                return self._respond_core(user_message, history, root_run, trace_id)
        return self._respond_core(user_message, history, None, trace_id)

    def stream_response(
        self, user_message: str, history: Optional[List[ConversationTurn]] = None
    ) -> Tuple[Iterable[str], dict]:
        """流式返回 LLM 输出。"""
        history = history or []
        trace_id = str(uuid.uuid4())
        if self.tracer.enabled:
            with self.tracer.start_run(
                name="fusion_agent",
                run_type="chain",
                inputs={"question": user_message},
                tags=["fusion", "qa"],
                metadata={"question_type": self._classify_question(user_message), "trace_id": trace_id},
            ) as root_run:
                return self._stream_core(user_message, history, root_run, trace_id)
        return self._stream_core(user_message, history, None, trace_id)

    def _respond_core(self, user_message: str, history: List[ConversationTurn], root_run, trace_id: str) -> Tuple[str, dict]:
        context, sources, question_type = self._prepare_context(user_message, history, root_run, trace_id)
        messages = [
            LLMMessage(role="system", content=SYSTEM_PROMPT),
            LLMMessage(role="user", content=context),
        ]
        if root_run:
            with self.tracer.start_run(
                name="llm_generate",
                run_type="llm",
                inputs={"prompt": context},
                tags=["llm"],
                metadata={"question_type": question_type},
                parent=root_run,
            ) as run:
                answer = self.llm.chat(messages)
                run.add_outputs({"answer": answer})
        else:
            answer = self.llm.chat(messages)
        self._write_final_answer(user_message, answer, root_run)
        return answer, {"sources": list(dict.fromkeys(sources))}

    def _stream_core(
        self, user_message: str, history: List[ConversationTurn], root_run, trace_id: str
    ) -> Tuple[Iterable[str], dict]:
        context, sources, question_type = self._prepare_context(user_message, history, root_run, trace_id)
        messages = [
            LLMMessage(role="system", content=SYSTEM_PROMPT),
            LLMMessage(role="user", content=context),
        ]

        def _generator() -> Iterable[str]:
            answer_parts: List[str] = []
            if root_run:
                with self.tracer.start_run(
                    name="llm_generate",
                    run_type="llm",
                    inputs={"prompt": context},
                    tags=["llm"],
                    metadata={"question_type": question_type},
                    parent=root_run,
                ) as run:
                    for delta in self.llm.chat_stream(messages):
                        answer_parts.append(delta)
                        yield delta
                    run.add_outputs({"answer": "".join(answer_parts)})
            else:
                for delta in self.llm.chat_stream(messages):
                    answer_parts.append(delta)
                    yield delta
            answer = "".join(answer_parts)
            self._write_final_answer(user_message, answer, root_run)

        return _generator(), {"sources": list(dict.fromkeys(sources))}

    def _prepare_context(
        self, user_message: str, history: List[ConversationTurn], root_run, trace_id: str
    ) -> Tuple[str, List[str], str]:
        """按路由执行 MCP/A2A，并组装上下文。"""
        evidences: List[EvidenceItem] = []
        sources: List[str] = []
        question_type = self._classify_question(user_message)
        plan_decision = self._plan_steps(user_message, history, trace_id, root_run)
        _log_module_io(
            "plan_router",
            {"question": _preview_text(user_message, MODULE_LOG_BODY_LIMIT), "history_len": len(history)},
            {"reason": plan_decision.reason, "plan": [step.to_dict() for step in plan_decision.plan]},
        )

        for step_index, step in enumerate(plan_decision.plan[: plan_decision.max_turns]):
            action = self._route_step_tool(
                step=step,
                user_message=user_message,
                question_type=question_type,
                trace_id=trace_id,
                root_run=root_run,
                step_index=step_index,
            )
            _log_module_io(
                "step_router",
                {
                    "step_index": step_index,
                    "objective": _preview_text(step.objective, MODULE_LOG_BODY_LIMIT),
                    "constraints": step.constraints,
                },
                {"action": action.to_dict()},
            )
            tool = action.tool
            if tool == "none":
                continue

            step_objective = action.objective or step.objective
            action_args = action.arguments if isinstance(action.arguments, dict) else {}

            if tool == "nl2sql":
                plan_tables = action_args.get("tables")
                if plan_tables is None and isinstance(step.constraints, dict):
                    plan_tables = step.constraints.get("tables")
                tables = [t for t in (plan_tables or self.config.allowed_tables) if t in self.config.allowed_tables]
                if not tables:
                    tables = list(self.config.allowed_tables)
                use_columns_raw = action_args.get("enable_column_retrieval")
                if use_columns_raw is None and isinstance(step.constraints, dict):
                    use_columns_raw = step.constraints.get("enable_column_retrieval")
                use_columns = bool(use_columns_raw)
                question = str(action_args.get("question") or step_objective)
                retried_without_columns = False
                retry_error = ""
                try:
                    nl2sql_payload = self.mcp_client.call_tool(
                        "nl2sql_query",
                        {
                            "question": question,
                            "tables": tables,
                            "enable_column_retrieval": use_columns,
                            "trace_id": trace_id,
                        },
                        trace_id=trace_id,
                        root_run=root_run,
                    )
                except Exception as exc:
                    if not use_columns:
                        raise
                    # 列级索引在冷启动时可能较慢，超时后降级为表级检索重试
                    retried_without_columns = True
                    retry_error = str(exc)
                    logger.warning(
                        "NL2SQL 首次调用失败，降级重试（无列检索）question=%s error=%s",
                        _preview_text(question, 200),
                        retry_error,
                    )
                    nl2sql_payload = self.mcp_client.call_tool(
                        "nl2sql_query",
                        {
                            "question": question,
                            "tables": tables,
                            "enable_column_retrieval": False,
                            "trace_id": trace_id,
                        },
                        trace_id=trace_id,
                        root_run=root_run,
                    )
                sql = str(nl2sql_payload.get("sql", "")) if isinstance(nl2sql_payload, dict) else ""
                result = nl2sql_payload.get("result", {}) if isinstance(nl2sql_payload, dict) else {}
                _log_module_io(
                    "mcp_nl2sql",
                    {"question": _preview_text(question, MODULE_LOG_BODY_LIMIT), "tables": tables},
                    {"sql": _preview_text(sql, MODULE_LOG_BODY_LIMIT), "result": _preview_text(str(result), MODULE_LOG_BODY_LIMIT)},
                )
                evidences.append(
                    EvidenceItem(
                        title="NL2SQL 结果",
                        content=f"SQL: {sql}\n结果: {result}",
                        source="nl2sql",
                        score=1.0,
                        metadata={
                            "retried_without_columns": retried_without_columns,
                            "retry_error": retry_error,
                        },
                    )
                )
                self.memory_manager.add_memory(
                    MemoryItem(
                        content=f"SQL: {sql}\n结果: {result}",
                        memory_type="episodic",
                        metadata={"tool": "nl2sql"},
                    )
                )
                sources.append("nl2sql")

            elif tool == "rag":
                top_k = 5
                top_k_raw = action_args.get("top_k")
                if top_k_raw is None and isinstance(step.constraints, dict):
                    top_k_raw = step.constraints.get("top_k")
                if top_k_raw is not None:
                    try:
                        top_k = max(1, int(top_k_raw))
                    except (TypeError, ValueError):
                        top_k = 5
                query = str(action_args.get("query") or step_objective)
                rag_payload = self.mcp_client.call_tool(
                    "rag_search",
                    {"query": query, "top_k": top_k, "trace_id": trace_id},
                    trace_id=trace_id,
                    root_run=root_run,
                )
                rag_results = rag_payload.get("chunks", []) if isinstance(rag_payload, dict) else []
                _log_module_io(
                    "mcp_rag",
                    {"query": _preview_text(query, MODULE_LOG_BODY_LIMIT), "top_k": top_k},
                    {"hits": len(rag_results)},
                )
                for chunk in rag_results:
                    if not isinstance(chunk, dict):
                        continue
                    text = str(chunk.get("text", ""))
                    source = str(chunk.get("source", "rag"))
                    evidences.append(
                        EvidenceItem(
                            title="文档片段",
                            content=f"{text}\n来源: {source}",
                            source="rag",
                            score=0.8,
                        )
                    )
                    self.memory_manager.add_memory(
                        MemoryItem(
                            content=text,
                            memory_type="working",
                            metadata={"source": source},
                        )
                    )
                    sources.append(source)

            elif tool == "todo":
                todo_items = self._plan_todos(step_objective)
                self._persist_todos(todo_items, trace_id=trace_id, root_run=root_run)
                task_results = self._run_todo_via_a2a(
                    todo_items=todo_items,
                    user_message=user_message,
                    trace_id=trace_id,
                    root_run=root_run,
                )
                for result in task_results:
                    summary = self._summarize_a2a_result(result)
                    evidences.append(
                        EvidenceItem(
                            title=f"子任务 {result.agent}",
                            content=summary,
                            source="task",
                            score=0.7,
                        )
                    )
                    self.memory_manager.add_memory(
                        MemoryItem(
                            content=summary,
                            memory_type="episodic",
                            metadata={"task_agent": result.agent},
                        )
                    )
                    sources.extend(self._collect_a2a_sources(result))

        if root_run:
            with self.tracer.start_run(
                name="memory_lookup",
                run_type="tool",
                inputs={"query": user_message},
                tags=["memory", "search"],
                metadata={"question_type": question_type},
                parent=root_run,
            ) as run:
                memories = self.memory_manager.search(user_message, top_k=5)
                run.add_outputs({"count": len(memories)})
        else:
            memories = self.memory_manager.search(user_message, top_k=5)

        notes_payload = self.mcp_client.call_tool(
            "note_search",
            {"query": user_message, "limit": 3, "trace_id": trace_id},
            trace_id=trace_id,
            root_run=root_run,
        )
        notes = notes_payload.get("notes", []) if isinstance(notes_payload, dict) else []
        if not isinstance(notes, list):
            notes = []
        notes = [str(note) for note in notes]
        _log_module_io(
            "mcp_note_search",
            {"query": _preview_text(user_message, MODULE_LOG_BODY_LIMIT), "limit": 3},
            {"hits": len(notes), "items": notes[:MODULE_LOG_MAX_ITEMS]},
        )

        context = self.context_builder.build(
            system_prompt=SYSTEM_PROMPT,
            user_query=user_message,
            history=history,
            memories=memories,
            evidences=evidences,
            notes=notes,
        )
        return context, sources, question_type

    def _run_todo_via_a2a(
        self,
        todo_items: List[TodoItem],
        user_message: str,
        trace_id: str,
        root_run,
    ) -> List[A2AResultEnvelope]:
        """将 Todo 子任务发送给 A2A supervisor 执行。"""
        results: List[A2AResultEnvelope] = []
        for item in todo_items:
            payload = A2ATaskPayload(
                agent="supervisor",
                objective=f"{item.title}\n{item.intent}".strip(),
                constraints={
                    "tables": self.config.allowed_tables,
                    "tools_allowed": list(_A2A_ALLOWED_AGENTS),
                },
                context={"task_id": item.id, "intent": item.intent, "question": user_message},
                expected_output="结构化结果 + 证据摘要",
                budget={"max_tokens": self.config.subagent_max_tokens, "max_time_ms": self.config.subagent_max_time_ms},
                trace_id=trace_id,
            )
            result = self.a2a_client.execute_task(payload, root_run=root_run)
            results.append(result)
            _log_module_io(
                "a2a_task",
                {
                    "task_id": item.id,
                    "title": item.title,
                    "agent": payload.agent,
                },
                {
                    "status": result.status,
                    "agent": result.agent,
                    "errors": result.errors,
                },
            )
        return results

    def _persist_todos(self, todo_items: List[TodoItem], trace_id: str, root_run) -> None:
        """将待办写入 MCP todo 工具，失败时不影响主流程。"""
        try:
            self.mcp_client.call_tool(
                "todo_add",
                {
                    "items": [
                        {
                            "id": item.id,
                            "title": item.title,
                            "intent": item.intent,
                            "status": item.status,
                        }
                        for item in todo_items
                    ],
                    "trace_id": trace_id,
                },
                trace_id=trace_id,
                root_run=root_run,
            )
        except Exception as exc:
            _log_module_io("mcp_todo_add", {"count": len(todo_items)}, {"error": str(exc)})

    @staticmethod
    def _collect_a2a_sources(result: A2AResultEnvelope) -> List[str]:
        sources: List[str] = []
        for item in result.evidence:
            source = item.metadata.get("source") if isinstance(item.metadata, dict) else None
            source = source or item.source
            if source:
                sources.append(str(source))
        return sources

    @staticmethod
    def _summarize_a2a_result(result: A2AResultEnvelope) -> str:
        if result.status != "ok":
            return f"[{result.agent}] 失败: {', '.join(result.errors)}"
        if isinstance(result.result, dict) and result.result.get("summary"):
            return str(result.result.get("summary"))
        if result.evidence:
            return "\n".join(item.content for item in result.evidence[:3])
        return f"[{result.agent}] 已完成。"

    def _write_final_answer(self, user_message: str, answer: str, root_run) -> None:
        if root_run:
            with self.tracer.start_run(
                name="memory_write",
                run_type="tool",
                inputs={"content": "final_answer"},
                tags=["memory", "write"],
                metadata={"source": "chat"},
                parent=root_run,
            ) as run:
                self.memory_manager.add_memory(
                    MemoryItem(
                        content=f"用户问题：{user_message}\n回答：{answer}",
                        memory_type="working",
                        metadata={"source": "chat"},
                    )
                )
                run.add_outputs({"status": "ok"})
        else:
            self.memory_manager.add_memory(
                MemoryItem(
                    content=f"用户问题：{user_message}\n回答：{answer}",
                    memory_type="working",
                    metadata={"source": "chat"},
                )
            )
        self._maybe_write_semantic_memory(user_message, answer, root_run)

    def _maybe_write_semantic_memory(self, user_message: str, answer: str, root_run) -> None:
        if not self.semantic_memory_enabled:
            return
        if not answer.strip():
            return
        records = self._extract_semantic_records(user_message, answer)
        if not records:
            return
        if root_run:
            with self.tracer.start_run(
                name="semantic_memory_write",
                run_type="tool",
                inputs={"count": len(records)},
                tags=["memory", "semantic"],
                metadata={"source": "semantic_extract"},
                parent=root_run,
            ) as run:
                self._write_semantic_records(records)
                run.add_outputs({"status": "ok", "count": len(records)})
        else:
            self._write_semantic_records(records)

    def _extract_semantic_records(self, user_message: str, answer: str) -> List[SemanticRecord]:
        prompt = [
            LLMMessage(role="system", content=SEMANTIC_EXTRACT_PROMPT),
            LLMMessage(role="user", content=f"用户问题：{user_message}\n助手回答：{answer}\n请抽取语义记忆条目。"),
        ]
        try:
            raw = self.llm.structured_chat(prompt, schema={"type": "array"})
        except Exception:
            return []
        items = raw
        if isinstance(raw, dict):
            items = raw.get("items") or raw.get("concepts") or []
        if not isinstance(items, list):
            return []
        records: List[SemanticRecord] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            concept = str(item.get("concept", "")).strip()
            description = str(item.get("description", "")).strip()
            if not concept or not description:
                continue
            try:
                importance = float(item.get("importance", 0.0))
            except (TypeError, ValueError):
                importance = 0.0
            if importance < self.semantic_memory_min_importance:
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            category = str(item.get("category", "")).strip()
            if category:
                metadata.setdefault("category", category)
            metadata.setdefault("source", "semantic_extract")
            metadata.setdefault("importance", importance)
            records.append(SemanticRecord(concept=concept, description=description, metadata=metadata))
            if len(records) >= self.semantic_memory_max_items:
                break
        return records

    def _write_semantic_records(self, records: List[SemanticRecord]) -> None:
        for record in records:
            try:
                self.memory_manager.semantic_memory.add_concept(record)
            except Exception as exc:
                logger.warning("语义记忆写入失败 concept=%s error=%s", record.concept, exc)

    def _plan_steps(
        self, user_message: str, history: List[ConversationTurn], trace_id: str, root_run
    ) -> ToolRouterDecision:
        """规划阶段：先生成不绑定工具的计划步骤。"""
        history_tail = [
            {"role": turn.role, "content": _preview_text(turn.content, 400)}
            for turn in history[-4:]
        ]
        payload = {
            "objective": user_message,
            "constraints": {
                "tables": self.config.allowed_tables,
                "max_rows": self.config.nl2sql_max_rows,
            },
            "context": {"question": user_message, "history_tail": history_tail},
            "expected_output": "计划步骤",
            "budget": {
                "max_tokens": self.config.subagent_max_tokens,
                "max_time_ms": self.config.subagent_max_time_ms,
            },
            "trace_id": trace_id,
        }
        messages = [
            LLMMessage(role="system", content=TOOL_ROUTER_PROMPT),
            LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
        ]
        tools = [tool_router_schema()]

        try:
            if self.tracer.enabled and root_run:
                with self.tracer.start_run(
                    name="plan_router",
                    run_type="llm",
                    inputs={"task": payload},
                    tags=["router", "plan"],
                    metadata={"trace_id": trace_id},
                    parent=root_run,
                ) as run:
                    _, result_payload = self.llm.tool_call(messages, tools=tools, tool_choice="required")
                    run.add_outputs({"payload": result_payload})
            else:
                _, result_payload = self.llm.tool_call(messages, tools=tools, tool_choice="required")
            decision = ToolRouterDecision.from_dict(result_payload)
        except Exception:
            decision = ToolRouterDecision.from_dict(
                {
                    "plan": [
                        {
                            "objective": user_message,
                            "constraints": {"top_k": 5},
                            "expected_output": "文档证据摘要",
                            "budget": {"max_tokens": self.config.subagent_max_tokens},
                        }
                    ],
                    "reason": "规划失败，降级为单步执行",
                    "max_turns": 1,
                }
            )
        return decision

    def _route_step_tool(
        self,
        step: ToolPlanStep,
        user_message: str,
        question_type: str,
        trace_id: str,
        root_run,
        step_index: int,
    ) -> ToolActionStep:
        """执行阶段：针对单个 step 选择工具并生成参数。"""
        tools_allowed = allowed_tool_names()
        payload = {
            "question": user_message,
            "question_type": question_type,
            "step_index": step_index,
            "step": step.to_dict(),
            "constraints": {
                "tables": self.config.allowed_tables,
                "tools_allowed": tools_allowed,
                "max_rows": self.config.nl2sql_max_rows,
            },
            "trace_id": trace_id,
        }
        messages = [
            LLMMessage(role="system", content=STEP_ACTOR_PROMPT),
            LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
        ]
        tools = [step_router_schema(tools_allowed)]

        try:
            if self.tracer.enabled and root_run:
                with self.tracer.start_run(
                    name="step_router",
                    run_type="llm",
                    inputs={"task": payload},
                    tags=["router", "step"],
                    metadata={"trace_id": trace_id, "step_index": step_index},
                    parent=root_run,
                ) as run:
                    _, result_payload = self.llm.tool_call(messages, tools=tools, tool_choice="required")
                    run.add_outputs({"payload": result_payload})
            else:
                _, result_payload = self.llm.tool_call(messages, tools=tools, tool_choice="required")
            action = ToolActionStep.from_dict(result_payload)
        except Exception:
            action = ToolActionStep(tool="rag", objective=step.objective, arguments={"query": step.objective, "top_k": 5})

        if action.tool not in tools_allowed:
            return ToolActionStep(tool="none", objective=step.objective, arguments={})
        return action

    def _classify_question(self, text: str) -> str:
        lowered = text.lower()
        if "ip" in lowered or "ipv4" in lowered or "ipv6" in lowered:
            return "ip_query"
        if "asn" in lowered or "as " in lowered or "as号" in text:
            return "as_query"
        if "域名" in text or "domain" in lowered or "网站" in text:
            return "domain_query"
        if "路由" in text or "bgp" in lowered or "route" in lowered:
            return "routing_query"
        return "concept"

    def _plan_todos(self, text: str) -> List[TodoItem]:
        """使用 LLM 生成待办列表。"""
        prompt = [
            LLMMessage(role="system", content=TODO_PLANNER_PROMPT),
            LLMMessage(role="user", content=text),
        ]
        response = self.llm.chat(prompt)
        try:
            raw = json.loads(response)
        except Exception:
            raw = []
        data = raw
        if isinstance(raw, dict):
            data = (
                raw.get("subtasks")
                or raw.get("items")
                or raw.get("todos")
                or raw.get("plan")
                or []
            )
        if not isinstance(data, list):
            data = []
        items: List[TodoItem] = []
        for item in data[:6]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("name") or "").strip()
            if not title:
                continue
            intent = str(item.get("intent") or item.get("objective") or "").strip()
            if not intent:
                intent = text
            items.append(
                TodoItem(
                    id=str(uuid.uuid4())[:8],
                    title=title,
                    intent=intent,
                    status="pending",
                )
            )
        if not items:
            items.append(
                TodoItem(
                    id=str(uuid.uuid4())[:8],
                    title="执行综合检索",
                    intent=text,
                    status="pending",
                )
            )
        return items
