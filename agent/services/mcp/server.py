"""FastMCP 工具服务。"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

from agent.core.config import AgentConfig
from agent.core.models import TodoItem
from agent.tools.neo4j_llamaindex_tool import Neo4jLlamaIndexTool
from agent.tools.nl2sql_tool import NL2SQLTool
from agent.tools.note_tool import NoteTool
from agent.tools.rag_tool import RAGTool, build_rag_embedding
from agent.tools.todo_tool import TodoTool


class _MCPRuntime:
    """MCP 运行时资源，启动时一次性初始化。"""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.nl2sql_tool = NL2SQLTool(
            postgres_url=self.config.postgres_url or "",
            allowed_tables=self.config.allowed_tables,
            milvus_host=self.config.milvus_host,
            milvus_port=self.config.milvus_port,
            milvus_collection=self.config.nl2sql_vector_collection,
            api_key=self.config.dashscope_api_key,
            base_url=self.config.dashscope_base_url,
            model=self.config.dashscope_model,
            embedding_backend=self.config.nl2sql_embedding_backend,
            embedding_model=self.config.nl2sql_embedding_model,
            embedding_device=self.config.nl2sql_embedding_device,
            embedding_batch_size=self.config.nl2sql_embedding_batch_size,
            embedding_normalize=self.config.nl2sql_embedding_normalize,
            index_cache_dir=self.config.nl2sql_index_cache_dir,
            enable_index_cache=self.config.nl2sql_index_cache_enabled,
            force_rebuild_cache=self.config.nl2sql_index_cache_force_rebuild,
            max_rows=self.config.nl2sql_max_rows,
            statement_timeout_ms=self.config.nl2sql_statement_timeout_ms,
            max_sql_length=self.config.nl2sql_max_sql_length,
            allow_subquery=self.config.nl2sql_allow_subquery,
        )
        self.rag_tool = RAGTool(
            host=self.config.milvus_host,
            port=self.config.milvus_port,
            collection_name=self.config.vector_collection,
            embedding=build_rag_embedding(self.config),
            enable_mqe=self.config.rag_enable_mqe,
            mqe_max_queries=self.config.rag_mqe_max_queries,
            candidate_multiplier=self.config.rag_candidate_multiplier,
            rrf_k=self.config.rag_rrf_k,
        )
        self.graph_llamaindex_tool = Neo4jLlamaIndexTool(
            uri=self.config.neo4j_uri,
            user=self.config.neo4j_user,
            password=self.config.neo4j_password,
            api_key=self.config.dashscope_api_key or "",
            base_url=self.config.dashscope_base_url,
            model=self.config.dashscope_model,
            database=self.config.neo4j_database,
            max_rows=self.config.graph_max_rows,
            max_cypher_length=self.config.graph_max_cypher_length,
            refresh_schema_each_query=self.config.graph_refresh_schema_each_query,
        )
        self.note_tool = NoteTool(self.config.notes_dir)
        self.todo_tool = TodoTool(self.config.project_root / "agent" / "todo.json")


def create_mcp_server(config: Optional[AgentConfig] = None) -> FastMCP:
    """创建 FastMCP server。"""
    # MCP 服务端进程默认关闭 LangSmith/LangChain tracing，避免产生噪声埋点。
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    cfg = config or AgentConfig.load()
    runtime = _MCPRuntime(cfg)
    mcp = FastMCP(name="fusion-tools", instructions="Fusion 工具层（NL2SQL / RAG / Neo4j-LlamaIndex / Note / Todo）")

    def _trace_tool(name: str, trace_id: str, inputs: Dict[str, Any], fn):
        """统一工具包装：服务端不再写入 LangSmith，仅执行工具函数。"""
        # 保留函数签名，避免调用侧改动；参数仅用于兼容。
        _ = (name, trace_id, inputs)
        return fn()

    @mcp.tool
    def health() -> Dict[str, Any]:
        """工具服务健康检查。"""
        return {"status": "ok"}

    @mcp.tool
    def nl2sql_query(
        question: str,
        tables: Optional[List[str]] = None,
        enable_column_retrieval: bool = False,
        query_mode: str = "OTHER",
        intent_policy: str = "auto",
        intent_labels_required: Optional[List[str]] = None,
        trace_id: str = "",
    ) -> Dict[str, Any]:
        """执行 NL2SQL 查询。

        说明：
        - query_mode 为当前生效参数；
        - intent_policy / intent_labels_required 为兼容字段，已废弃但暂时保留。
        """

        def _run() -> Dict[str, Any]:
            result = runtime.nl2sql_tool.query(
                question,
                tables=tables,
                enable_column_retrieval=enable_column_retrieval,
                query_mode=query_mode,
                trace_id=trace_id,
            )
            return {"sql": result.sql, "result": result.result}

        return _trace_tool(
            "nl2sql_query",
            trace_id,
            {
                "question": question,
                "tables": tables or [],
                "enable_column_retrieval": enable_column_retrieval,
                "query_mode": query_mode,
                "intent_policy": intent_policy,
                "intent_labels_required": intent_labels_required or [],
            },
            _run,
        )

    @mcp.tool
    def rag_search(query: str, top_k: int = 5, trace_id: str = "") -> Dict[str, Any]:
        """执行文档向量检索。"""

        def _run() -> Dict[str, Any]:
            chunks = runtime.rag_tool.search(query, top_k=max(1, int(top_k)))
            return {
                "query": query,
                "top_k": max(1, int(top_k)),
                "chunks": [
                    {
                        "text": chunk.text,
                        "source": chunk.source,
                        "score": chunk.metadata.get("score"),
                    }
                    for chunk in chunks
                ],
            }

        return _trace_tool("rag_search", trace_id, {"query": query, "top_k": top_k}, _run)

    @mcp.tool
    def neo4j_llamaindex_query(question: str, max_rows: Optional[int] = None, trace_id: str = "") -> Dict[str, Any]:
        """使用 LlamaIndex 自动读取图结构并生成 Cypher 执行查询。"""

        def _run() -> Dict[str, Any]:
            return runtime.graph_llamaindex_tool.query(question, max_rows=max_rows, trace_id=trace_id)

        return _trace_tool(
            "neo4j_llamaindex_query",
            trace_id,
            {"question": question, "max_rows": max_rows},
            _run,
        )

    @mcp.tool
    def note_search(query: str, limit: int = 3, trace_id: str = "") -> Dict[str, Any]:
        """搜索笔记。"""

        def _run() -> Dict[str, Any]:
            notes = runtime.note_tool.search(query, limit=max(1, int(limit)))
            return {"notes": notes}

        return _trace_tool("note_search", trace_id, {"query": query, "limit": limit}, _run)

    @mcp.tool
    def todo_add(items: List[Dict[str, Any]], trace_id: str = "") -> Dict[str, Any]:
        """批量写入 Todo。"""

        def _run() -> Dict[str, Any]:
            todo_items: List[TodoItem] = []
            for item in items:
                todo_items.append(
                    TodoItem(
                        id=str(item.get("id", "")),
                        title=str(item.get("title", "")).strip(),
                        intent=str(item.get("intent", "")).strip(),
                        status=str(item.get("status", "pending")),
                    )
                )
            runtime.todo_tool.add_items(todo_items)
            return {"count": len(todo_items)}

        return _trace_tool("todo_add", trace_id, {"count": len(items)}, _run)

    @mcp.tool
    def todo_list(trace_id: str = "") -> Dict[str, Any]:
        """读取 Todo 列表。"""

        def _run() -> Dict[str, Any]:
            return {
                "items": [
                    {
                        "id": item.id,
                        "title": item.title,
                        "intent": item.intent,
                        "status": item.status,
                        "created_at": item.created_at.isoformat(),
                        "updated_at": item.updated_at.isoformat(),
                    }
                    for item in runtime.todo_tool.list_items()
                ]
            }

        return _trace_tool("todo_list", trace_id, {}, _run)

    return mcp


config = AgentConfig.load()
mcp_server = create_mcp_server(config)
app = mcp_server.http_app(path="/mcp", transport="streamable-http")
