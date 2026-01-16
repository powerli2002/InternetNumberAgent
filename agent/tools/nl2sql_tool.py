from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Dict, List, Optional, Tuple

from llama_index.core.bridge.pydantic import PrivateAttr

from agent.schema import TABLE_CONTEXT_HINTS, TABLE_SCHEMA


class DashScopeLlamaEmbedding:
    """为 LlamaIndex 提供阿里云百炼嵌入模型适配。"""

    def __init__(self, api_key: str, base_url: str, model: str = "text-embedding-v3") -> None:
        try:
            from llama_index.core.base.embeddings.base import BaseEmbedding  # type: ignore
            from openai import OpenAI  # type: ignore
        except Exception as exc:
            raise RuntimeError("未安装 llama-index/openai，无法初始化嵌入模型。") from exc

        if not api_key:
            raise RuntimeError("缺少 DASHSCOPE_API_KEY，无法生成嵌入向量。")

        class _Embedding(BaseEmbedding):
            model_name: str = "dashscope-embedding"
            _client = PrivateAttr()
            _model = PrivateAttr()

            def __init__(self, client, model_name: str) -> None:
                super().__init__(embed_batch_size=10)
                self._client = client
                self._model = model_name

            def _embed_batch(self, texts: List[str]) -> List[List[float]]:
                # 按批调用百炼 Embedding，避免过大请求触发限流
                batch_size = 10
                vectors: List[List[float]] = []
                for i in range(0, len(texts), batch_size):
                    payload = texts[i : i + batch_size]
                    response = self._client.embeddings.create(model=self._model, input=payload)
                    vectors.extend([item.embedding for item in response.data])
                return vectors

            def _get_text_embedding(self, text: str) -> List[float]:
                return self._embed_batch([text])[0]

            def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
                return self._embed_batch(texts)

            def _get_query_embedding(self, query: str) -> List[float]:
                return self._embed_batch([query])[0]

            async def _aget_query_embedding(self, query: str) -> List[float]:
                return self._get_query_embedding(query)

        self._embedding = _Embedding(OpenAI(api_key=api_key, base_url=base_url), model)

    @property
    def embedding(self):
        return self._embedding


class DashScopeLlamaLLM:
    """为 LlamaIndex 提供阿里云百炼 LLM 适配。"""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        try:
            from langsmith.wrappers import wrap_openai  # type: ignore
            from llama_index.core.base.llms.types import LLMMetadata  # type: ignore
            from llama_index.core.llms.custom import CustomLLM  # type: ignore
            from openai import OpenAI  # type: ignore
        except Exception as exc:
            raise RuntimeError("未安装 llama-index/openai/langsmith，无法初始化 LLM。") from exc

        if not api_key:
            raise RuntimeError("缺少 DASHSCOPE_API_KEY，无法调用 LLM。")

        class _LLM(CustomLLM):
            _client = PrivateAttr()
            _model = PrivateAttr()
            _metadata = PrivateAttr()

            def __init__(self, client, model_name: str) -> None:
                super().__init__()
                self._client = client
                self._model = model_name
                # LlamaIndex 需要模型元数据以评估上下文窗口与输出长度
                self._metadata = LLMMetadata(
                    context_window=4096,
                    num_output=512,
                    is_chat_model=True,
                    model_name=model_name,
                )

            @property
            def metadata(self):  # type: ignore[override]
                return self._metadata

            def complete(self, prompt: str, formatted: bool = False, **kwargs):  # type: ignore[override]
                from llama_index.core.base.llms.types import CompletionResponse  # type: ignore

                # 统一走 chat.completions，保持与百炼兼容
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt}],
                    stream=False,
                )
                text = response.choices[0].message.content or ""
                return CompletionResponse(text=text, raw=response)

            def stream_complete(self, prompt: str, formatted: bool = False, **kwargs):  # type: ignore[override]
                from llama_index.core.base.llms.types import CompletionResponse  # type: ignore

                # 流式输出逐段返回，供 LlamaIndex 增量消费
                stream = self._client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt}],
                    stream=True,
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta.content or ""
                    if delta:
                        yield CompletionResponse(text=delta, delta=delta, raw=chunk)

        client = wrap_openai(OpenAI(api_key=api_key, base_url=base_url))
        self._llm = _LLM(client, model)

    @property
    def llm(self):
        return self._llm


@dataclass
class NL2SQLResult:
    """NL2SQL 输出结构。"""

    sql: str
    result: Any


class DatabaseClient:
    """统一数据库执行入口，优先使用 SQLAlchemy。"""

    def __init__(self, postgres_url: str) -> None:
        self.postgres_url = postgres_url
        self._engine = None

    def _get_engine(self):
        if self._engine:
            return self._engine
        try:
            from sqlalchemy import create_engine  # type: ignore
        except Exception as exc:
            raise RuntimeError("未安装 SQLAlchemy，无法建立数据库连接。") from exc
        # 延迟创建，减少冷启动开销
        self._engine = create_engine(self.postgres_url)
        return self._engine

    def get_engine(self):
        """获取 SQLAlchemy 引擎，便于复用连接池。"""
        return self._get_engine()

    def run_sql(self, sql: str) -> List[Tuple]:
        # 统一执行入口，返回原始行数据
        engine = self._get_engine()
        with engine.connect() as conn:
            from sqlalchemy import text as sql_text  # type: ignore

            result = conn.execute(sql_text(sql))  # type: ignore
            return result.fetchall()


class NL2SQLTool:
    """自然语言转 SQL 并执行。"""

    # 默认列索引配置：仅选择相对稳定、类别化程度高的字段
    COLUMN_INDEX_CONFIG: Dict[str, List[str]] = {
        "as_entity": [
            "as_country",
            "as_country_cn",
            "org_country",
            "org_country_cn",
            "status",
            "source",
            "type",
            "type_cn",
            "aut_name",
            "org_name",
            "org_name_cn",
        ],
        "asn_entity": ["country", "status", "source", "org_name"],
        "country_entity": ["country", "country_cn", "country_en", "region"],
        "industry_entity": ["industry", "parent", "title", "key", "ip_org", "auth_ip_org"],
        "ip_bgp_entity": [
            "country",
            "source",
            "route",
            "bgp",
            "org_handle_prefix",
            "org_name_prefix",
            "org_name_cn_prefix",
            "org_handle_bgp",
            "org_name_bgp",
            "org_name_cn_bgp",
            "domain",
            "domain_auth",
        ],
        "ip_inetnum_entity": ["country", "source", "netname", "org", "org_name", "org_name_cn"],
        "ip_rdap_entity": ["country", "source", "netname", "org", "org_name", "org_name_cn"],
        "ip_route_entity": ["source", "origin"],
        "ipv4_entity": ["country", "source", "status", "org_name"],
        "ipv6_bgp_entity": [
            "country",
            "source",
            "route",
            "bgp",
            "org_handle_prefix",
            "org_name_prefix",
            "org_name_cn_prefix",
            "org_handle_bgp",
            "org_name_bgp",
            "org_name_cn_bgp",
        ],
        "ipv6_entity": ["country", "source", "status", "org_name"],
        "ipv6_inetnum_entity": ["country", "source", "netname", "org", "org_name", "org_name_cn"],
        "ipv6_rdap_entity": ["country", "source", "netname", "org", "org_name", "org_name_cn"],
        "ipv6_route_entity": ["source", "origin"],
        "org_entity": ["org_country", "org_country_cn", "org_name", "org_name_cn"],
        "website_entity": ["industry", "title", "key", "url"],
    }

    def __init__(
        self,
        postgres_url: str,
        allowed_tables: Optional[List[str]] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "qwen3-max-preview",
        enable_table_retrieval: bool = True,
        enable_column_retrieval: bool = True,
        table_retriever_top_k: int = 4,
        column_retriever_top_k: int = 3,
        column_index_max_values: int = 200,
        column_index_max_value_length: int = 128,
        column_index_config: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        self.postgres_url = postgres_url
        self.allowed_tables = allowed_tables or []
        self.db = DatabaseClient(postgres_url) if postgres_url else None
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        # 仅保留允许表的 schema，避免 NL2SQL 访问非核心表
        self.table_schema = {k: v for k, v in TABLE_SCHEMA.items() if not self.allowed_tables or k in self.allowed_tables}
        self.enable_table_retrieval = enable_table_retrieval
        self.enable_column_retrieval = enable_column_retrieval
        self.table_retriever_top_k = table_retriever_top_k
        self.column_retriever_top_k = column_retriever_top_k
        self.column_index_max_values = column_index_max_values
        self.column_index_max_value_length = column_index_max_value_length
        self.column_index_config = column_index_config or self.COLUMN_INDEX_CONFIG
        self._llm = None
        self._embed_model = None

    def query(self, question: str, tables: Optional[List[str]] = None) -> NL2SQLResult:
        """使用 LlamaIndex NL2SQL 生成查询并执行。"""
        try:
            from llama_index.core import SQLDatabase  # type: ignore
            from llama_index.core import VectorStoreIndex  # type: ignore
            from llama_index.core.objects import ObjectIndex, SQLTableNodeMapping, SQLTableSchema  # type: ignore
            from llama_index.core.schema import TextNode  # type: ignore
            try:
                from llama_index.core.indices.struct_store import SQLTableRetrieverQueryEngine  # type: ignore
            except Exception:
                from llama_index.core.indices.struct_store.sql_query import (  # type: ignore
                    SQLTableRetrieverQueryEngine,
                )
        except Exception as exc:
            raise RuntimeError("缺少 llama-index 依赖，无法执行 NL2SQL。") from exc

        if not self.postgres_url:
            raise RuntimeError("未配置 POSTGRES_URL，无法执行 NL2SQL。")
        if not self.api_key:
            raise RuntimeError("未配置 DASHSCOPE_API_KEY，无法执行 NL2SQL。")

        table_names = tables or self.allowed_tables
        if not table_names:
            raise RuntimeError("未提供可用表名，无法执行 NL2SQL。")
        # 连接数据库并准备 LLM/Embedding
        db = SQLDatabase.from_uri(self.postgres_url, include_tables=table_names)
        llm = self._get_llm()
        embed_model = self._get_embed_model()

        # 为每张表构建上下文提示，帮助模型理解字段语义
        table_context = {k: v for k, v in self._build_table_context().items() if k in table_names}
        table_schema = [
            SQLTableSchema(
                table_name=table,
                context_str=table_context.get(table, ""),
            )
            for table in table_names
        ]
        # 基于表结构构建向量索引，支持“相关表”检索
        table_node_mapping = SQLTableNodeMapping(db)
        table_index = ObjectIndex.from_objects(
            table_schema,
            table_node_mapping,
            VectorStoreIndex,
            embed_model=embed_model,
        )
        # 若显式关闭表检索，则回退到返回全部表，避免 SQL 引擎失去表上下文
        table_top_k = self.table_retriever_top_k if self.enable_table_retrieval else len(table_names)
        table_retriever = table_index.as_retriever(similarity_top_k=table_top_k)

        cols_retrievers = None
        if self.enable_column_retrieval:
            # 可选的列值检索：通过列的离散值帮助模型对齐实体
            cols_retrievers = self._build_column_retrievers(
                table_names=table_names,
                embed_model=embed_model,
                text_node_cls=TextNode,
                vector_index_cls=VectorStoreIndex,
            )

        engine = SQLTableRetrieverQueryEngine(
            sql_database=db,
            table_retriever=table_retriever,
            cols_retrievers=cols_retrievers,
            llm=llm,
            context_query_kwargs=table_context,
            embed_model=embed_model,
            verbose=False,
        )
        # 让引擎生成 SQL 并执行，返回结构化结果
        response = engine.query(question)
        return NL2SQLResult(sql=str(response.metadata.get("sql_query", "")), result=str(response))

    def _execute(self, sql: str) -> List[Tuple]:
        if not self.db:
            raise RuntimeError("未配置数据库连接，无法执行 SQL。")
        return self.db.run_sql(sql)

    def _build_table_context(self) -> Dict[str, str]:
        """将 summary.md 的字段信息转为 NL2SQL 提示上下文。"""
        context: Dict[str, str] = {}
        for table, columns in self.table_schema.items():
            hint = TABLE_CONTEXT_HINTS.get(table, "")
            if hint:
                context[table] = f"字段: {', '.join(columns)}。说明: {hint}"
            else:
                context[table] = f"字段: {', '.join(columns)}"
        return context

    def _get_llm(self):
        if self._llm is None:
            self._llm = DashScopeLlamaLLM(
                api_key=self.api_key,
                base_url=self.base_url or "",
                model=self.model,
            ).llm
        return self._llm

    def _get_embed_model(self):
        if self._embed_model is None:
            self._embed_model = DashScopeLlamaEmbedding(
                api_key=self.api_key,
                base_url=self.base_url or "",
                model="text-embedding-v3",
            ).embedding
        return self._embed_model

    def _build_column_retrievers(
        self,
        table_names: List[str],
        embed_model,
        text_node_cls,
        vector_index_cls,
    ) -> Optional[Dict[str, Dict[str, Any]]]:
        """构建列级检索器：按列索引去重后的离散取值。"""
        if not self.db:
            return None
        try:
            from sqlalchemy import MetaData, Table, select  # type: ignore
        except Exception as exc:
            raise RuntimeError("未安装 SQLAlchemy，无法构建列索引。") from exc

        engine = self.db.get_engine()
        metadata = MetaData()
        cols_retrievers: Dict[str, Dict[str, Any]] = {}

        for table_name in table_names:
            # 根据配置选择“稳定且可枚举”的列来构建向量检索
            column_names = self.column_index_config.get(table_name, [])
            if not column_names:
                continue
            try:
                table = Table(table_name, metadata, autoload_with=engine)
            except Exception:
                continue
            table_retrievers: Dict[str, Any] = {}
            for column_name in column_names:
                if column_name not in table.c:
                    continue
                column = table.c[column_name]
                # 取列的去重值作为索引文本，限制数量避免过大
                values = self._fetch_distinct_values(engine, select(column).distinct().limit(self.column_index_max_values))
                nodes = self._build_column_nodes(
                    values,
                    text_node_cls,
                    metadata={"table": table_name, "column": column_name},
                )
                if not nodes:
                    continue
                column_index = vector_index_cls(nodes, embed_model=embed_model)
                table_retrievers[column_name] = column_index.as_retriever(
                    similarity_top_k=self.column_retriever_top_k
                )
            if table_retrievers:
                cols_retrievers[table_name] = table_retrievers

        return cols_retrievers or None

    def _fetch_distinct_values(self, engine, stmt) -> List[Any]:
        """执行列值查询，统一返回值列表。"""
        with engine.connect() as conn:
            result = conn.execute(stmt)  # type: ignore
            return [row[0] for row in result.fetchall()]

    def _build_column_nodes(self, values: List[Any], text_node_cls, metadata: Optional[Dict[str, Any]] = None) -> List[Any]:
        """将列值标准化为可向量化节点。"""
        nodes = []
        seen = set()
        for value in values:
            text = self._normalize_column_value(value)
            if not text:
                continue
            # 过滤过长值与重复值，降低噪声
            if len(text) > self.column_index_max_value_length:
                continue
            if text in seen:
                continue
            seen.add(text)
            nodes.append(text_node_cls(text=text, metadata=metadata or {}))
        return nodes

    def _normalize_column_value(self, value: Any) -> Optional[str]:
        """标准化列值，尽量减少无意义或空值。"""
        if value is None:
            return None
        if isinstance(value, (list, tuple, set)):
            parts = [str(item).strip() for item in value if item is not None and str(item).strip()]
            return ", ".join(parts) if parts else None
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        text = str(value).strip()
        return text or None
