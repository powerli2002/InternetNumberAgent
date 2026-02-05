"""
互联网号码资源问答系统 - 主智能体实现

FusionAgent 是系统的核心组件，负责整合 NL2SQL、RAG、记忆与上下文工程，
实现可解释的问答链路和可观测的运行过程。

主要功能：
1. 问题分类与路由：根据问题类型选择合适的工具组合
2. 工具调度：协调 NL2SQL（结构化查询）、RAG（文档检索）、任务规划
3. 上下文工程：基于 GSSC 流程组装证据、记忆与历史
4. 记忆管理：写入工作/情景/语义记忆，支持长期学习
5. 链路追踪：集成 LangSmith 实现端到端可观测性

架构位置：
- 数据层：连接 PostgreSQL（16 表）、Milvus（向量索引）、Neo4j（语义图谱）
- 工具层：调度 NL2SQLTool、RAGTool、TaskTool 等专业工具
- 记忆层：统一管理工作记忆（短期）、情景记忆（对话）、语义记忆（知识）
- 上下文层：通过 ContextBuilder 实现证据驱动的上下文组装
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Iterable, List, Optional, Tuple

from agent.config import AgentConfig
from agent.context import ContextBuilder
from agent.llm import LLMClient, LLMMessage
from agent.memory.semantic import SemanticRecord
from agent.models import ConversationTurn, EvidenceItem, MemoryItem, TodoItem
from agent.prompts import SEMANTIC_EXTRACT_PROMPT, SYSTEM_PROMPT, TODO_PLANNER_PROMPT
from agent.memory import EpisodicMemory, MemoryManager, SemanticMemory, WorkingMemory
from agent.tools import NL2SQLTool, NoteTool, RAGTool, TaskTool, TodoTool
from agent.tools.rag_tool import DashScopeEmbedding
from agent.tracing import LangSmithTracer
from src.utils.logging_manager import logger


MODULE_LOG_ENABLED = os.getenv("MODULE_LOG_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
MODULE_LOG_BODY_LIMIT = max(256, int(os.getenv("MODULE_LOG_BODY_LIMIT", "2000")))
MODULE_LOG_MAX_ITEMS = max(1, int(os.getenv("MODULE_LOG_MAX_ITEMS", "5")))


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
    """
    融合智能体主类 - 互联网号码资源问答系统的核心控制器

    实现基于工具调度的问答流程，整合多种检索与推理能力：
    - NL2SQL：将自然语言转换为 SQL 查询，访问结构化数据
    - RAG：检索增强生成，从文档向量中获取相关知识
    - 记忆系统：管理工作记忆（对话上下文）、情景记忆（历史对话）、语义记忆（长期知识）
    - 任务规划：复杂问题自动分解为子任务并执行
    - 上下文工程：基于 GSSC 流程组织证据驱动的上下文

    核心算法流程：
    1. 问题分析：通过关键词和实体识别判断工具需求
    2. 工具调度：并行调用 NL2SQL/RAG/规划工具获取证据
    3. 上下文组装：按优先级整合系统提示、历史、证据、记忆
    4. 回答生成：基于完整上下文生成可解释的回答
    5. 记忆写入：将工具结果和最终回答写入相应记忆系统
    6. 语义抽取：从对话中提取长期可用的概念和规则
    """

    def __init__(self, config: Optional[AgentConfig] = None) -> None:
        """
        初始化融合智能体，加载配置并准备所有组件

        初始化顺序：
        1. 加载配置参数（数据库、模型、向量库连接等）
        2. 初始化 LLM 客户端（用于问答生成和任务规划）
        3. 设置上下文构建器（控制上下文长度和组织方式）
        4. 初始化三类记忆系统（工作/情景/语义记忆）
        5. 加载专业工具（NL2SQL、RAG、笔记、待办、任务执行）
        6. 配置链路追踪器（LangSmith 集成）
        """
        # 加载配置（包含模型、数据库、向量库等连接信息）
        self.config = config or AgentConfig.load()

        # 初始化 LLM 客户端，统一用于生成与规划
        # 使用阿里云百炼兼容 OpenAI 接口，支持流式和结构化输出
        self.llm = LLMClient(
            api_key=self.config.dashscope_api_key,
            base_url=self.config.dashscope_base_url,
            model=self.config.dashscope_model,
        )

        # 上下文组装器：基于 GSSC 流程将系统/历史/证据整理为模型上下文
        # 控制最大 token 数，避免超出模型限制
        self.context_builder = ContextBuilder(max_tokens=self.config.max_context_tokens)

        # 语义记忆相关配置：控制是否启用和抽取阈值
        self.semantic_memory_enabled = self.config.semantic_memory_enabled
        self.semantic_memory_max_items = self.config.semantic_memory_max_items
        self.semantic_memory_min_importance = self.config.semantic_memory_min_importance

        # 统一记忆管理：三类记忆系统协同工作
        # - 工作记忆：短期对话上下文，容量较小但访问频繁
        # - 情景记忆：优先使用 PostgreSQL 持久化（无 PG 时回退 SQLite），支持时间衰减
        # - 语义记忆：Neo4j 图谱存储长期知识和概念关系
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

        # 初始化专业工具集合
        # NoteTool：笔记管理，支持创建和搜索知识条目
        self.note_tool = NoteTool(self.config.notes_dir)

        # TodoTool：任务规划管理，将复杂问题分解为可执行步骤
        self.todo_tool = TodoTool(self.config.project_root / "agent" / "todo.json")

        # LangSmith 链路追踪器：记录 LLM 调用、工具执行、记忆写入等关键环节
        self.tracer = LangSmithTracer()

        # NL2SQLTool：自然语言到 SQL 转换引擎
        # 基于 LlamaIndex 实现，支持表/列检索优化和缓存
        self.nl2sql_tool = NL2SQLTool(
            postgres_url=self.config.postgres_url or "",
            allowed_tables=self.config.allowed_tables,
            api_key=self.config.dashscope_api_key,
            base_url=self.config.dashscope_base_url,
            model=self.config.dashscope_model,
            embedding_model=self.config.dashscope_embedding_model,
            index_cache_dir=self.config.nl2sql_index_cache_dir,
            enable_index_cache=self.config.nl2sql_index_cache_enabled,
            force_rebuild_cache=self.config.nl2sql_index_cache_force_rebuild,
            max_rows=self.config.nl2sql_max_rows,
            statement_timeout_ms=self.config.nl2sql_statement_timeout_ms,
            max_sql_length=self.config.nl2sql_max_sql_length,
            allow_subquery=self.config.nl2sql_allow_subquery,
        )

        # RAGTool：文档向量检索工具
        # 基于 Milvus 向量数据库，支持文档分块和相似度检索
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

        # TaskTool：子任务执行器
        # 支持复杂问题的自动分解和并行执行
        self.task_tool = TaskTool(agent_factory=lambda: FusionAgent(self.config))

    def respond(self, user_message: str, history: Optional[List[ConversationTurn]] = None) -> Tuple[str, dict]:
        """
        主入口方法：处理用户问题并返回完整回答

        执行流程：
        1. 问题分类：识别问题类型（IP查询、ASN查询、概念解释等）
        2. 上下文准备：调用工具获取证据，检索记忆，组装上下文
        3. 回答生成：基于完整上下文调用 LLM 生成回答
        4. 记忆写入：将工具结果和最终回答写入相应记忆系统
        5. 语义抽取：从对话中提取长期知识写入语义记忆

        Args:
            user_message: 用户输入的问题文本
            history: 对话历史记录，用于提供上下文

        Returns:
            Tuple[str, dict]: (回答文本, 元数据字典包含来源信息)
        """
        history = history or []

        # LangSmith 链路追踪：将完整的问答流程作为一次链路运行
        # 记录输入问题、使用的工具、生成的回答等关键信息
        if self.tracer.enabled:
            with self.tracer.start_run(
                name="fusion_agent",  # 链路名称
                run_type="chain",     # 运行类型：完整链路
                inputs={"question": user_message},  # 输入参数
                tags=["fusion", "qa"],  # 标签用于分类和筛选
                metadata={"question_type": self._classify_question(user_message)},  # 元数据
            ) as root_run:
                return self._respond_core(user_message, history, root_run)

        return self._respond_core(user_message, history, None)

    def stream_response(
        self, user_message: str, history: Optional[List[ConversationTurn]] = None
    ) -> Tuple[Iterable[str], dict]:
        """流式返回 LLM 输出，用于前端 SSE。"""
        history = history or []
        # 与非流式一致，区别在于逐步返回 delta
        if self.tracer.enabled:
            with self.tracer.start_run(
                name="fusion_agent",
                run_type="chain",
                inputs={"question": user_message},
                tags=["fusion", "qa"],
                metadata={"question_type": self._classify_question(user_message)},
            ) as root_run:
                return self._stream_core(user_message, history, root_run)
        return self._stream_core(user_message, history, None)

    def _respond_core(self, user_message: str, history: List[ConversationTurn], root_run) -> Tuple[str, dict]:
        # 1) 准备上下文（证据/记忆/笔记） 2) 调用 LLM 生成 3) 写入记忆
        context, sources, question_type = self._prepare_context(user_message, history, root_run)

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

    def _stream_core(self, user_message: str, history: List[ConversationTurn], root_run) -> Tuple[Iterable[str], dict]:
        # 与 _respond_core 相同流程，但以流式输出答案片段
        context, sources, question_type = self._prepare_context(user_message, history, root_run)
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
        self, user_message: str, history: List[ConversationTurn], root_run
    ) -> Tuple[str, List[str], str]:
        """
        上下文准备核心方法：根据问题类型调度工具并组装证据

        执行策略：
        1. 问题分析：通过关键词和实体识别判断需要哪些工具
        2. 工具调度：根据判断结果调用 NL2SQL、RAG、任务规划工具
        3. 证据收集：将工具执行结果转换为结构化证据项
        4. 记忆检索：从三类记忆系统中搜索相关历史信息
        5. 上下文组装：使用 GSSC 流程整合所有信息

        工具选择逻辑：
        - NL2SQL：包含 IP/ASN/前缀/归属等关键词，或能提取到实体
        - RAG：解释性问题，或不适合 NL2SQL 的情况
        - 任务规划：长文本（>200字符）或显式包含"计划"/"步骤"

        Args:
            user_message: 用户问题文本
            history: 对话历史
            root_run: LangSmith 根运行对象，用于子链路追踪

        Returns:
            Tuple[str, List[str], str]: (组装后的上下文, 来源列表, 问题类型)
        """
        evidences: List[EvidenceItem] = []  # 收集的证据项
        sources: List[str] = []  # 证据来源，用于去重和溯源

        # 问题分析阶段：通过轻量规则判断是否走 NL2SQL / RAG / 规划
        # 基于关键词匹配和实体抽取，避免复杂 LLM 调用
        use_nl2sql = self._should_use_nl2sql(user_message)
        use_rag = self._should_use_rag(user_message)
        question_type = self._classify_question(user_message)

        # NL2SQL 工具调度：处理结构化数据查询
        if use_nl2sql:
            """
            NL2SQL 执行流程：
            1. 基于 LlamaIndex 调用阿里云百炼模型生成 SQL
            2. 在 PostgreSQL 上执行生成的 SQL 语句
            3. 将 SQL 和结果作为高优先级证据（score=1.0）
            4. 写入情景记忆，支持时间衰减的长期保留

            适用场景：IP 归属查询、ASN 统计、路由分析等需要精确数据的场景
            """
            use_columns = self._should_use_column_retrieval(user_message, question_type)
            if root_run:
                # LangSmith 子链路追踪：记录 NL2SQL 工具的完整执行过程
                with self.tracer.start_run(
                    name="nl2sql_query",
                    run_type="tool",
                    inputs={
                        "question": user_message,
                        "tables": self.config.allowed_tables,
                        "enable_column_retrieval": use_columns,
                    },
                    tags=["nl2sql", "tool"],
                    metadata={"question_type": question_type},
                    parent=root_run,
                ) as run:
                    nl2sql_result = self.nl2sql_tool.query(
                        user_message,
                        tables=self.config.allowed_tables,
                        enable_column_retrieval=use_columns,
                    )
                    run.add_outputs({"sql": nl2sql_result.sql, "result": str(nl2sql_result.result)})
            else:
                nl2sql_result = self.nl2sql_tool.query(
                    user_message,
                    tables=self.config.allowed_tables,
                    enable_column_retrieval=use_columns,
                )
            _log_module_io(
                "nl2sql",
                {
                    "question": _preview_text(user_message, MODULE_LOG_BODY_LIMIT),
                    "tables": self.config.allowed_tables,
                    "enable_column_retrieval": use_columns,
                },
                {
                    "sql": _preview_text(nl2sql_result.sql, MODULE_LOG_BODY_LIMIT),
                    "result": _preview_text(str(nl2sql_result.result), MODULE_LOG_BODY_LIMIT),
                },
            )

            # 将 SQL 执行结果转换为结构化证据
            evidences.append(
                EvidenceItem(
                    title="NL2SQL 结果",
                    content=f"SQL: {nl2sql_result.sql}\n结果: {nl2sql_result.result}",
                    source="nl2sql",
                    score=1.0,  # 最高优先级：结构化数据结果最可靠
                )
            )

            # 记忆写入：将查询过程写入情景记忆，便于后续追溯和学习
            # 使用情景记忆而不是工作记忆，因为 SQL 查询结果具有长期价值
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
                            memory_type="episodic",  # 情景记忆：重要对话片段
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
            _log_module_io(
                "memory_write",
                {
                    "type": "episodic",
                    "source": "nl2sql",
                    "content_preview": _preview_text(
                        f"SQL: {nl2sql_result.sql}\n结果: {nl2sql_result.result}",
                        min(512, MODULE_LOG_BODY_LIMIT),
                    ),
                },
                {"status": "ok"},
            )
            sources.append("nl2sql")

        if use_rag:
            # RAG：向量检索文档片段作为解释性证据
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
            _log_module_io(
                "rag",
                {
                    "query": _preview_text(user_message, MODULE_LOG_BODY_LIMIT),
                    "top_k": 5,
                    "collection": self.config.vector_collection,
                },
                {
                    "hits": len(rag_results),
                    "items": [
                        {
                            "source": _preview_text(chunk.source, min(256, MODULE_LOG_BODY_LIMIT)),
                            "score": chunk.metadata.get("score") if isinstance(chunk.metadata, dict) else None,
                            "text_preview": _preview_text(chunk.text, min(512, MODULE_LOG_BODY_LIMIT)),
                        }
                        for chunk in rag_results[:MODULE_LOG_MAX_ITEMS]
                    ],
                },
            )
            for chunk in rag_results:
                evidences.append(
                    EvidenceItem(
                        title="文档片段",
                        content=f"{chunk.text}\n来源: {chunk.source}",
                        source="rag",
                        score=0.8,
                    )
                )
                # 检索结果写入工作记忆，保留短期上下文
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
                _log_module_io(
                    "memory_write",
                    {
                        "type": "working",
                        "source": chunk.source,
                        "content_preview": _preview_text(chunk.text, min(512, MODULE_LOG_BODY_LIMIT)),
                    },
                    {"status": "ok"},
                )
                sources.append(chunk.source)

        if self._should_plan(user_message):
            # 任务规划：长问题拆解为待办项并执行子任务
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
            _log_module_io(
                "todo_plan",
                {
                    "question": _preview_text(user_message, MODULE_LOG_BODY_LIMIT),
                    "count": len(todo_items),
                    "items": [
                        {
                            "id": item.id,
                            "title": _preview_text(item.title, 256),
                            "intent": _preview_text(item.intent, min(512, MODULE_LOG_BODY_LIMIT)),
                        }
                        for item in todo_items[:MODULE_LOG_MAX_ITEMS]
                    ],
                },
                {"status": "ok"},
            )
            self.todo_tool.add_items(todo_items)
            task_results = self.task_tool.run_tasks(todo_items)
            _log_module_io(
                "task",
                {
                    "count": len(todo_items),
                    "items": [
                        {"id": item.id, "title": _preview_text(item.title, 256)}
                        for item in todo_items[:MODULE_LOG_MAX_ITEMS]
                    ],
                },
                {
                    "count": len(task_results),
                    "items": [
                        {
                            "id": result.task.id,
                            "summary_preview": _preview_text(result.summary, min(512, MODULE_LOG_BODY_LIMIT)),
                            "sources": result.sources[:MODULE_LOG_MAX_ITEMS],
                        }
                        for result in task_results[:MODULE_LOG_MAX_ITEMS]
                    ],
                },
            )
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
                _log_module_io(
                    "memory_write",
                    {
                        "type": "episodic",
                        "source": f"task:{result.task.id}",
                        "content_preview": _preview_text(result.summary, min(512, MODULE_LOG_BODY_LIMIT)),
                    },
                    {"status": "ok"},
                )
                sources.extend(result.sources)

        # 统一从三类记忆中检索高相关内容补充上下文
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
        _log_module_io(
            "memory_lookup",
            {
                "query": _preview_text(user_message, MODULE_LOG_BODY_LIMIT),
                "top_k": 5,
            },
            {
                "hits": len(memories),
                "items": [
                    {
                        "type": mem.memory_type,
                        "score": mem.score,
                        "preview": _preview_text(mem.content, min(512, MODULE_LOG_BODY_LIMIT)),
                        "metadata": mem.metadata,
                    }
                    for mem in memories[:MODULE_LOG_MAX_ITEMS]
                ],
            },
        )
        notes = self.note_tool.search(user_message, limit=3)
        _log_module_io(
            "notes_search",
            {
                "query": _preview_text(user_message, MODULE_LOG_BODY_LIMIT),
                "limit": 3,
            },
            {
                "hits": len(notes),
                "items": [
                    _preview_text(note.content, min(512, MODULE_LOG_BODY_LIMIT))
                    for note in notes[:MODULE_LOG_MAX_ITEMS]
                ],
            },
        )

        # GSSC：Gather/Select/Structure/Compress 组装上下文
        context = self.context_builder.build(
            system_prompt=SYSTEM_PROMPT,
            user_query=user_message,
            history=history,
            memories=memories,
            evidences=evidences,
            notes=notes,
        )

        return context, sources, question_type

    def _write_final_answer(self, user_message: str, answer: str, root_run) -> None:
        # 最终回答写入工作记忆，便于后续对话引用
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
        _log_module_io(
            "memory_write",
            {
                "type": "working",
                "source": "chat",
                "content_preview": _preview_text(f"用户问题：{user_message}\n回答：{answer}", min(512, MODULE_LOG_BODY_LIMIT)),
            },
            {"status": "ok"},
        )
        # 语义记忆：抽取稳定知识/规则/偏好写入 Neo4j
        self._maybe_write_semantic_memory(user_message, answer, root_run)

    def _maybe_write_semantic_memory(self, user_message: str, answer: str, root_run) -> None:
        if not self.semantic_memory_enabled:
            return
        if not answer.strip():
            return
        # 抽取语义记忆条目（失败时静默降级）
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
        _log_module_io(
            "semantic_memory_write",
            {
                "count": len(records),
                "items": [
                    {
                        "concept": _preview_text(record.concept, 128),
                        "description_preview": _preview_text(record.description, min(512, MODULE_LOG_BODY_LIMIT)),
                        "metadata": record.metadata,
                    }
                    for record in records[:MODULE_LOG_MAX_ITEMS]
                ],
            },
            {"status": "ok"},
        )

    def _extract_semantic_records(self, user_message: str, answer: str) -> List[SemanticRecord]:
        """抽取语义记忆条目，失败返回空列表。"""
        prompt = [
            LLMMessage(role="system", content=SEMANTIC_EXTRACT_PROMPT),
            LLMMessage(
                role="user",
                content=f"用户问题：{user_message}\n助手回答：{answer}\n请抽取语义记忆条目。",
            ),
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
        """写入语义记忆，异常时忽略以避免影响主流程。"""
        try:
            for record in records:
                self.memory_manager.semantic_memory.add_concept(record)
        except Exception:
            return

    def _should_use_nl2sql(self, text: str) -> bool:
        # 简易关键词 + 实体抽取启发式判断是否需要结构化查询
        keywords = ["IP", "ASN", "AS", "前缀", "归属", "国家", "排行", "数量", "bgp", "route"]
        if any(k.lower() in text.lower() for k in keywords):
            return True
        return bool(self._extract_ip(text) or self._extract_asn(text))

    def _should_use_rag(self, text: str) -> bool:
        # 解释性问题优先走 RAG；否则默认也可补充说明
        keywords = ["是什么", "定义", "背景", "原理", "说明", "解释", "如何"]
        return any(k in text for k in keywords) or not self._should_use_nl2sql(text)

    def _should_use_column_retrieval(self, text: str, question_type: str) -> bool:
        """
        根据问题类型与关键词判断是否启用列索引检索。

        设计原则：
        - 默认优先表索引，避免每次加载大量列索引造成延迟
        - 当问题涉及“属性/名称/国家/组织/行业/网站”等字段时再启用列索引
        """
        if question_type == "domain_query":
            return True
        keywords = [
            "国家",
            "组织",
            "公司",
            "行业",
            "域名",
            "网站",
            "标题",
            "名称",
            "名字",
            "描述",
            "类型",
            "状态",
            "country",
            "org",
            "organization",
            "industry",
            "domain",
            "website",
            "title",
            "name",
            "descr",
            "status",
            "type",
        ]
        lowered = text.lower()
        for keyword in keywords:
            if keyword.isascii():
                if keyword in lowered:
                    return True
            else:
                if keyword in text:
                    return True
        return False

    def _should_plan(self, text: str) -> bool:
        # 简单规则：显式“计划/步骤”或长问题触发分解
        return "计划" in text or "步骤" in text or len(text) > 200

    def _classify_question(self, text: str) -> str:
        # 用于埋点统计与策略参考的粗分类
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
        # 期望模型输出 JSON 数组：[{title, intent}, ...]
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

        # IPv4 简单匹配，用于触发 NL2SQL
        match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", text)
        return match.group(1) if match else None

    @staticmethod
    def _extract_asn(text: str) -> Optional[str]:
        import re

        # ASN 形如 AS123 或 ASN123 的提取
        match = re.search(r"AS\s*(\d+)|ASN\s*(\d+)", text, re.IGNORECASE)
        if not match:
            return None
        return next(g for g in match.groups() if g)
