"""基于 LlamaIndex 的 Neo4j 自主查询工具。

能力说明：
1. 使用 Neo4jPropertyGraphStore 读取图结构（schema）；
2. 使用 TextToCypherRetriever 根据自然语言问题生成 Cypher；
3. 在工具内部执行 Cypher 并返回结构化结果。
4. 支持传入 repair_context 进行 Cypher 修复重试（换修复模板，复用 LlamaIndex 组件）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from agent.core.llm import strip_think_blocks
from agent.tools.neo4j_query_tool import CypherGuard
from agent.tools.nl2sql_tool import DashScopeLlamaLLM

logger = logging.getLogger(__name__)


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

    def query(
        self,
        question: str,
        max_rows: Optional[int] = None,
        trace_id: str = "",
        repair_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行自然语言图查询并返回 Cypher 与结果。

        Args:
            question: 用户自然语言问题（重试时保持原始问题不变）。
            max_rows: 本次查询结果上限；为空时使用工具默认值。
            trace_id: 追踪 ID，用于绑定 LLM 子调用链路。
            repair_context: 修复上下文，包含 raw_cypher（上次生成的错误 Cypher）和
                error（错误信息）。不为空时使用修复 PromptTemplate 替换默认模板，
                错误信息在 schema/question 同级位置，LLM 能正确理解修复任务。

        Returns:
            包含 schema、生成的 cypher、查询 rows、row_count 的结构化结果。
        """
        try:
            from llama_index.core.prompts import PromptTemplate  # type: ignore
        except Exception as exc:
            raise RuntimeError("缺少 llama-index-core 依赖。") from exc

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

        # 用 closure 捕获 LLM 生成的原始 Cypher，便于失败时记录和传递给重试逻辑。
        _captured_cypher: List[str] = []

        def _validate_and_capture(raw_cypher: str) -> str:
            # 推理模型输出前含 <think>...</think> 块，复用共享工具剥离后再交给 CypherGuard 校验
            cypher_to_validate = strip_think_blocks(str(raw_cypher))
            _captured_cypher.clear()
            _captured_cypher.append(cypher_to_validate)
            logger.warning("LLM生成Cypher trace_id=%s cypher=%s", trace_id or "-", cypher_to_validate)
            return guard.sanitize(cypher_to_validate).get("cypher", "")

        # repair_context 不为空时，使用修复 PromptTemplate：
        # 把错误 Cypher 和错误原因放在 template 的独立变量位置（而非混入 question），
        # 确保 LLM 理解这是"修复已有 Cypher"的任务，而非重新生成。
        if repair_context:
            prev_cypher = str(repair_context.get("raw_cypher") or "").strip()
            prev_error = str(repair_context.get("error") or "").strip()
            repair_template = PromptTemplate(
                "Schema:\n{schema}\n\n"
                f"上次生成的 Cypher（有误，禁止原样返回）:\n{prev_cypher}\n\n"
                f"错误原因: {prev_error}\n\n"
                "修复要求:\n"
                "1. 只能以 MATCH / OPTIONAL MATCH / WITH 开头\n"
                "2. 不得含有 CALL/CREATE/MERGE/DELETE/SET/DROP 等写操作关键字\n"
                "3. 末尾必须有 LIMIT 子句\n"
                "4. 仅输出修正后的 Cypher，不加解释\n\n"
                "为以下问题生成修正后的 Cypher:\n{question}"
            )
            retriever = self._retriever_cls(
                graph_store=self._graph_store,
                llm=self._llm,
                text_to_cypher_template=repair_template,
                cypher_validator=_validate_and_capture,
                include_raw_response_as_metadata=True,
            )
        else:
            retriever = self._retriever_cls(
                graph_store=self._graph_store,
                llm=self._llm,
                cypher_validator=_validate_and_capture,
                include_raw_response_as_metadata=True,
            )

        try:
            nodes = retriever.retrieve(text)
        except Exception as exc:
            # 把生成的原始 Cypher 注入异常消息，供 orchestrator 提取用于下一轮修复。
            raw = _captured_cypher[0] if _captured_cypher else ""
            raise RuntimeError(f"{exc}|raw_cypher={raw}") from exc

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
