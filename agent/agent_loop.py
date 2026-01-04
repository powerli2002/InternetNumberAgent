from __future__ import annotations

import json
import uuid
from typing import List, Optional, Tuple

from agent.config import AgentConfig
from agent.context import ContextBuilder
from agent.llm import LLMClient, LLMMessage
from agent.models import ConversationTurn, EvidenceItem, MemoryItem, TodoItem
from agent.prompts import SYSTEM_PROMPT, TODO_PLANNER_PROMPT
from agent.memory import EpisodicMemory, MemoryManager, SemanticMemory, WorkingMemory
from agent.tools import NL2SQLTool, NoteTool, RAGTool, TaskTool, TodoTool
from agent.tools.rag_tool import DashScopeEmbedding
from agent.tracing import LangSmithTracer


class FusionAgent:
    """融合 NL2SQL、RAG、记忆与上下文工程的主代理。"""

    def __init__(self, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.load()
        self.llm = LLMClient(
            api_key=self.config.dashscope_api_key,
            base_url=self.config.dashscope_base_url,
            model=self.config.dashscope_model,
        )
        self.context_builder = ContextBuilder(max_tokens=self.config.max_context_tokens)

        memory_dir = self.config.project_root / "agent" / "memory_store"
        self.memory_manager = MemoryManager(
            working_memory=WorkingMemory(capacity=self.config.working_memory_size),
            episodic_memory=EpisodicMemory(memory_dir / "episodic.sqlite", capacity=self.config.episodic_memory_size),
            semantic_memory=SemanticMemory(
                uri=self.config.neo4j_uri,
                user=self.config.neo4j_user,
                password=self.config.neo4j_password,
            ),
        )

        self.note_tool = NoteTool(self.config.notes_dir)
        self.todo_tool = TodoTool(self.config.project_root / "agent" / "todo.json")
        self.tracer = LangSmithTracer()
        self.nl2sql_tool = NL2SQLTool(
            postgres_url=self.config.postgres_url or "",
            allowed_tables=self.config.allowed_tables,
            api_key=self.config.dashscope_api_key,
            base_url=self.config.dashscope_base_url,
            model=self.config.dashscope_model,
        )
        self.rag_tool = RAGTool(
            host=self.config.milvus_host,
            port=self.config.milvus_port,
            collection_name=self.config.vector_collection,
            embedding=DashScopeEmbedding(
                api_key=self.config.dashscope_api_key,
                base_url=self.config.dashscope_base_url,
                model=self.config.dashscope_embedding_model,
            ),
        )
        self.task_tool = TaskTool(agent_factory=lambda: FusionAgent(self.config))

    def respond(self, user_message: str, history: Optional[List[ConversationTurn]] = None) -> Tuple[str, dict]:
        """主入口：处理用户问题，返回回复与元数据。"""
        history = history or []
        if self.tracer.enabled:
            with self.tracer.start_run(
                name="fusion_agent",
                run_type="chain",
                inputs={"question": user_message},
                tags=["fusion", "qa"],
                metadata={"question_type": self._classify_question(user_message)},
            ) as root_run:
                return self._respond_core(user_message, history, root_run)

        return self._respond_core(user_message, history, None)

    def _respond_core(self, user_message: str, history: List[ConversationTurn], root_run) -> Tuple[str, dict]:
        evidences: List[EvidenceItem] = []
        sources: List[str] = []

        use_nl2sql = self._should_use_nl2sql(user_message)
        use_rag = self._should_use_rag(user_message)
        question_type = self._classify_question(user_message)

        if use_nl2sql:
            if root_run:
                with self.tracer.start_run(
                    name="nl2sql_query",
                    run_type="tool",
                    inputs={"question": user_message, "tables": self.config.allowed_tables},
                    tags=["nl2sql", "tool"],
                    metadata={"question_type": question_type},
                    parent=root_run,
                ) as run:
                    nl2sql_result = self.nl2sql_tool.query(user_message, tables=self.config.allowed_tables)
                    run.add_outputs({"sql": nl2sql_result.sql, "result": str(nl2sql_result.result)})
            else:
                nl2sql_result = self.nl2sql_tool.query(user_message, tables=self.config.allowed_tables)
            evidences.append(
                EvidenceItem(
                    title="NL2SQL 结果",
                    content=f"SQL: {nl2sql_result.sql}\n结果: {nl2sql_result.result}",
                    source="nl2sql",
                    score=1.0,
                )
            )
            if root_run:
                with self.tracer.start_run(
                    name="memory_write",
                    run_type="tool",
                    inputs={"content": "nl2sql_result"},
                    tags=["memory", "write"],
                    metadata={"tool": "nl2sql"},
                    parent=root_run,
                ) as run:
                    self.memory_manager.add_memory(
                        MemoryItem(
                            content=f"SQL: {nl2sql_result.sql}\n结果: {nl2sql_result.result}",
                            memory_type="episodic",
                            metadata={"tool": "nl2sql"},
                        )
                    )
                    run.add_outputs({"status": "ok"})
            else:
                self.memory_manager.add_memory(
                    MemoryItem(
                        content=f"SQL: {nl2sql_result.sql}\n结果: {nl2sql_result.result}",
                        memory_type="episodic",
                        metadata={"tool": "nl2sql"},
                    )
                )
            sources.append("nl2sql")

        if use_rag:
            if root_run:
                with self.tracer.start_run(
                    name="vector_search",
                    run_type="tool",
                    inputs={"query": user_message},
                    tags=["rag", "vector"],
                    metadata={"collection": self.config.vector_collection, "question_type": question_type},
                    parent=root_run,
                ) as run:
                    rag_results = self.rag_tool.search(user_message, top_k=5)
                    run.add_outputs({"hits": len(rag_results)})
            else:
                rag_results = self.rag_tool.search(user_message, top_k=5)
            for chunk in rag_results:
                evidences.append(
                    EvidenceItem(
                        title="文档片段",
                        content=f"{chunk.text}\n来源: {chunk.source}",
                        source="rag",
                        score=0.8,
                    )
                )
                if root_run:
                    with self.tracer.start_run(
                        name="memory_write",
                        run_type="tool",
                        inputs={"content": "rag_chunk"},
                        tags=["memory", "write"],
                        metadata={"source": chunk.source},
                        parent=root_run,
                    ) as run:
                        self.memory_manager.add_memory(
                            MemoryItem(
                                content=chunk.text,
                                memory_type="working",
                                metadata={"source": chunk.source},
                            )
                        )
                        run.add_outputs({"status": "ok"})
                else:
                    self.memory_manager.add_memory(
                        MemoryItem(
                            content=chunk.text,
                            memory_type="working",
                            metadata={"source": chunk.source},
                        )
                    )
                sources.append(chunk.source)

        if self._should_plan(user_message):
            if root_run:
                with self.tracer.start_run(
                    name="todo_plan",
                    run_type="tool",
                    inputs={"question": user_message},
                    tags=["todo", "planner"],
                    metadata={"question_type": question_type},
                    parent=root_run,
                ) as run:
                    todo_items = self._plan_todos(user_message)
                    run.add_outputs({"count": len(todo_items)})
            else:
                todo_items = self._plan_todos(user_message)
            self.todo_tool.add_items(todo_items)
            task_results = self.task_tool.run_tasks(todo_items)
            for result in task_results:
                evidences.append(
                    EvidenceItem(
                        title=f"子任务 {result.task.id}",
                        content=result.summary,
                        source="task",
                        score=0.7,
                    )
                )
                if root_run:
                    with self.tracer.start_run(
                        name="memory_write",
                        run_type="tool",
                        inputs={"content": "task_summary"},
                        tags=["memory", "write"],
                        metadata={"task_id": result.task.id},
                        parent=root_run,
                    ) as run:
                        self.memory_manager.add_memory(
                            MemoryItem(
                                content=result.summary,
                                memory_type="episodic",
                                metadata={"task_id": result.task.id},
                            )
                        )
                        run.add_outputs({"status": "ok"})
                else:
                    self.memory_manager.add_memory(
                        MemoryItem(
                            content=result.summary,
                            memory_type="episodic",
                            metadata={"task_id": result.task.id},
                        )
                    )
                sources.extend(result.sources)

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
        notes = self.note_tool.search(user_message, limit=3)

        context = self.context_builder.build(
            system_prompt=SYSTEM_PROMPT,
            user_query=user_message,
            history=history,
            memories=memories,
            evidences=evidences,
            notes=notes,
        )

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

        return answer, {"sources": list(dict.fromkeys(sources))}

    def _should_use_nl2sql(self, text: str) -> bool:
        keywords = ["IP", "ASN", "AS", "前缀", "归属", "国家", "排行", "数量", "bgp", "route"]
        if any(k.lower() in text.lower() for k in keywords):
            return True
        return bool(self._extract_ip(text) or self._extract_asn(text))

    def _should_use_rag(self, text: str) -> bool:
        keywords = ["是什么", "定义", "背景", "原理", "说明", "解释", "如何"]
        return any(k in text for k in keywords) or not self._should_use_nl2sql(text)

    def _should_plan(self, text: str) -> bool:
        return "计划" in text or "步骤" in text or len(text) > 200

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
        data = json.loads(response)
        return [
            TodoItem(
                id=str(uuid.uuid4())[:8],
                title=item["title"],
                intent=item.get("intent", ""),
                status="pending",
            )
            for item in data
        ]

    @staticmethod
    def _extract_ip(text: str) -> Optional[str]:
        import re

        match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", text)
        return match.group(1) if match else None

    @staticmethod
    def _extract_asn(text: str) -> Optional[str]:
        import re

        match = re.search(r"AS\s*(\d+)|ASN\s*(\d+)", text, re.IGNORECASE)
        if not match:
            return None
        return next(g for g in match.groups() if g)
