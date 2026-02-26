"""基于 LlamaIndex 的 Neo4j 自主查询工具。

能力说明：
1. 使用 Neo4jPropertyGraphStore 读取图结构（schema）；
2. 使用 TextToCypherRetriever 根据自然语言问题生成 Cypher；
3. 在工具内部执行 Cypher 并返回结构化结果。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from agent.tools.neo4j_query_tool import CypherGuard
from agent.tools.nl2sql_tool import DashScopeLlamaLLM


class Neo4jLlamaIndexTool:
    """LlamaIndex Neo4j 查询工具：问题 -> Cypher -> 结果。"""

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        api_key: str,
        base_url: str,
        model: str,
        database: str = "neo4j",
        max_rows: int = 200,
        max_cypher_length: int = 4000,
        refresh_schema_each_query: bool = True,
    ) -> None:
        """初始化 LlamaIndex 图查询执行器。

        Args:
            uri: Neo4j 连接地址（bolt 协议）。
            user: Neo4j 用户名。
            password: Neo4j 密码。
            api_key: DashScope/OpenAI 兼容 API Key。
            base_url: DashScope/OpenAI 兼容 Base URL。
            model: 生成 Cypher 的大模型名称。
            database: Neo4j 数据库名。
            max_rows: 查询最大返回行数。
            max_cypher_length: Cypher 最大长度限制。
            refresh_schema_each_query: 每次查询前是否刷新 schema。
        """
        try:
            from llama_index.core.indices.property_graph import TextToCypherRetriever  # type: ignore
            from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore  # type: ignore
        except Exception as exc:
            raise RuntimeError("缺少 llama-index-graph-stores-neo4j 依赖，无法执行图谱自然语言查询。") from exc

        self.max_rows = max(1, int(max_rows))
        self.max_cypher_length = max(256, int(max_cypher_length))
        self.refresh_schema_each_query = bool(refresh_schema_each_query)

        # 复用项目内 LlamaIndex 兼容 LLM 适配器，保持统一鉴权与追踪能力。
        self._llm = DashScopeLlamaLLM(api_key=api_key, base_url=base_url, model=model).llm
        # 使用 Neo4jPropertyGraphStore 作为 LlamaIndex 图存储后端。
        self._graph_store = Neo4jPropertyGraphStore(
            username=user,
            password=password,
            url=uri,
            database=database,
            refresh_schema=True,
            sanitize_query_output=True,
            # 查询链路不负责写入索引，避免连接时触发写操作。
            create_indexes=False,
        )
        self._retriever_cls = TextToCypherRetriever

    def query(self, question: str, max_rows: Optional[int] = None, trace_id: str = "") -> Dict[str, Any]:
        """执行自然语言图查询并返回 Cypher 与结果。

        Args:
            question: 用户自然语言问题。
            max_rows: 本次查询结果上限；为空时使用工具默认值。
            trace_id: 追踪 ID，用于绑定 LLM 子调用链路。

        Returns:
            包含 schema、生成的 cypher、查询 rows、row_count 的结构化结果。
        """
        text = str(question or "").strip()
        if not text:
            raise ValueError("question 不能为空")

        limit = self.max_rows if max_rows is None else max(1, int(max_rows))
        guard = CypherGuard(max_rows=limit, max_cypher_length=self.max_cypher_length)

        # 让 LLM 调用链路继承当前 trace_id，便于 LangSmith 关联检索。
        if hasattr(self._llm, "set_trace_id"):
            self._llm.set_trace_id(trace_id)

        # 按需刷新 schema，确保查询基于当前数据库结构生成 Cypher。
        schema_snapshot = self._graph_store.get_schema_str(refresh=self.refresh_schema_each_query)

        retriever = self._retriever_cls(
            graph_store=self._graph_store,
            llm=self._llm,
            # 把现有 Cypher 安全守卫接入 LlamaIndex 生成链路。
            cypher_validator=lambda raw_cypher: guard.sanitize(str(raw_cypher)).get("cypher", ""),
            include_raw_response_as_metadata=True,
        )
        nodes = retriever.retrieve(text)
        if not nodes:
            raise RuntimeError("LlamaIndex 图查询未返回任何结果节点。")

        cypher, rows, node_text = self._extract_first_node_payload(nodes)
        row_count = len(rows)
        return {
            "question": text,
            "schema": schema_snapshot,
            "cypher": cypher,
            "rows": rows,
            "row_count": row_count,
            "raw_response_text": node_text,
        }

    @staticmethod
    def _extract_first_node_payload(nodes: List[Any]) -> Tuple[str, List[Any], str]:
        """从 TextToCypherRetriever 返回节点中提取 cypher 与结果行。"""
        first = nodes[0]
        node = getattr(first, "node", None)
        if node is None:
            raise RuntimeError("LlamaIndex 返回节点缺少 node 数据。")

        node_text = ""
        if hasattr(node, "get_content"):
            node_text = str(node.get_content())
        elif hasattr(node, "text"):
            node_text = str(getattr(node, "text"))

        metadata = node.metadata if isinstance(getattr(node, "metadata", None), dict) else {}
        cypher = str(metadata.get("query") or "").strip()
        raw_rows = metadata.get("response")
        if raw_rows is None:
            return cypher, [], node_text
        if isinstance(raw_rows, list):
            return cypher, raw_rows, node_text
        return cypher, [raw_rows], node_text
