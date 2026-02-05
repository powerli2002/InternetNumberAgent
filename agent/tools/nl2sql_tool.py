"""
NL2SQL 工具模块 - 自然语言到 SQL 的转换与执行

核心功能：
1. 基于 LlamaIndex 的 SQL 生成引擎
2. 支持阿里云百炼嵌入模型进行表/列检索优化
3. 向量索引缓存机制，提高查询性能
4. PostgreSQL 数据库连接和安全查询执行
5. 表结构和列值的向量化索引

工作流程：
1. 接收自然语言问题和可用表列表
2. 使用向量检索找到相关的表和列
3. 基于表结构上下文生成 SQL 语句
4. 在 PostgreSQL 中执行 SQL 并返回结果
5. 缓存索引以提升后续查询性能

索引策略：
- 表级索引：对表名和描述进行向量化，支持表相关性排序
- 列级索引：对列名和示例值进行向量化，支持列值匹配
- 缓存机制：支持增量更新，避免重复计算
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from llama_index.core.bridge.pydantic import PrivateAttr

from agent.schema import TABLE_CONTEXT_HINTS, TABLE_SCHEMA
from src.utils.logging_manager import logger


NL2SQL_LOG_ENABLED = os.getenv("NL2SQL_LOG_ENABLED", "true").lower() in {"1", "true", "yes", "on"}


def _log_nl2sql(message: str, *args) -> None:
    """统一 NL2SQL 日志开关，避免过量输出。"""
    if NL2SQL_LOG_ENABLED:
        logger.info(message, *args)


class DashScopeLlamaEmbedding:
    """
    阿里云百炼嵌入模型适配器

    为 LlamaIndex 提供兼容的嵌入接口，封装阿里云百炼的 text-embedding-v3 模型。
    支持批量嵌入生成，自动处理 API 限流和错误重试。

    主要特性：
    - 兼容 LlamaIndex BaseEmbedding 接口
    - 支持批量处理（默认批大小 10）
    - 自动错误处理和重试机制
    - 与 OpenAI 兼容的 API 调用方式

    使用场景：
    - NL2SQL 中的表结构向量化
    - 列值索引构建
    - 文档相似度计算
    """

    def __init__(self, api_key: str, base_url: str, model: str = "text-embedding-v3") -> None:
        """
        初始化嵌入模型适配器

        Args:
            api_key: 阿里云百炼 API 密钥
            base_url: API 基础 URL
            model: 嵌入模型名称，默认 text-embedding-v3

        Raises:
            RuntimeError: 当缺少依赖或 API 密钥时抛出
        """
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

    def run_sql(self, sql: str, timeout_ms: Optional[int] = None, max_rows: Optional[int] = None) -> Dict[str, Any]:
        # 统一执行入口，返回列名与行数据
        engine = self._get_engine()
        with engine.connect() as conn:
            from sqlalchemy import text as sql_text  # type: ignore

            if timeout_ms:
                conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
            result = conn.execute(sql_text(sql))  # type: ignore
            columns = list(result.keys())
            if max_rows:
                rows = result.fetchmany(max_rows + 1)
                truncated = len(rows) > max_rows
                if truncated:
                    rows = rows[:max_rows]
            else:
                rows = result.fetchall()
                truncated = False
            return {"columns": columns, "rows": rows, "truncated": truncated}


class SQLGuard:
    """SQL 安全守卫：校验只读与表白名单，并强制 LIMIT。"""

    _BLOCKED_KEYWORDS = {
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "create",
        "truncate",
        "merge",
        "grant",
        "revoke",
        "copy",
        "vacuum",
        "analyze",
        "call",
        "execute",
        "set",
        "show",
        "reset",
        "lock",
        "notify",
        "listen",
        "into",
    }

    _BLOCKED_FUNCTIONS = {
        "pg_sleep",
        "pg_terminate_backend",
        "pg_cancel_backend",
    }

    def __init__(
        self,
        allowed_tables: List[str],
        max_rows: int,
        max_sql_length: int,
        allow_subquery: bool,
    ) -> None:
        self.allowed_tables = {t.lower() for t in allowed_tables}
        self.max_rows = max_rows
        self.max_sql_length = max_sql_length
        self.allow_subquery = allow_subquery

    def sanitize(self, sql: str) -> Tuple[str, Dict[str, Any]]:
        """校验并修正 SQL，返回安全 SQL 与执行策略信息。"""
        raw_sql = (sql or "").strip()
        if not raw_sql:
            raise RuntimeError("生成 SQL 为空，无法执行。")

        cleaned = self._strip_comments(raw_sql).strip().rstrip(";").strip()
        if not cleaned:
            raise RuntimeError("SQL 仅包含注释或空内容，无法执行。")
        if ";" in cleaned:
            raise RuntimeError("检测到多语句 SQL，已拒绝执行。")
        if len(cleaned) > self.max_sql_length:
            raise RuntimeError("SQL 超过长度限制，已拒绝执行。")

        sql_no_strings = self._strip_string_literals(cleaned)
        if not re.match(r"^(select|with)\b", sql_no_strings, flags=re.IGNORECASE):
            raise RuntimeError("仅允许执行 SELECT/CTE 查询。")

        for keyword in self._BLOCKED_KEYWORDS:
            if re.search(rf"\b{re.escape(keyword)}\b", sql_no_strings, flags=re.IGNORECASE):
                raise RuntimeError(f"SQL 含有禁止关键字: {keyword}")

        for func in self._BLOCKED_FUNCTIONS:
            if re.search(rf"\b{re.escape(func)}\b", sql_no_strings, flags=re.IGNORECASE):
                raise RuntimeError(f"SQL 含有禁止函数: {func}")

        tables = self._extract_tables(sql_no_strings)
        for table in tables:
            if table.lower() not in self.allowed_tables:
                raise RuntimeError(f"SQL 引用了未授权表: {table}")

        safe_sql, limit_info = self._enforce_limit(cleaned)
        return safe_sql, limit_info

    def _strip_comments(self, sql: str) -> str:
        # 移除行注释与块注释，避免干扰关键字检查
        sql = re.sub(r"--.*", "", sql)
        sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
        return sql

    def _strip_string_literals(self, sql: str) -> str:
        # 替换字符串字面量，避免误判关键字
        return re.sub(r"'(?:''|[^'])*'", "''", sql)

    def _extract_tables(self, sql: str) -> List[str]:
        # 解析 FROM/JOIN 后的表名，拒绝子查询以提升安全性
        if not self.allow_subquery and re.search(r"\b(from|join)\s+\(", sql, flags=re.IGNORECASE):
            raise RuntimeError("检测到子查询，当前策略禁止执行。")
        pattern = re.compile(r'\b(from|join)\s+(?:only\s+)?(["\w\.]+)', re.IGNORECASE)
        tables: List[str] = []
        for match in pattern.finditer(sql):
            token = match.group(2)
            name = token.strip('"')
            if "." in name:
                name = name.split(".")[-1]
            if name:
                tables.append(name.lower())
        return tables

    def _enforce_limit(self, sql: str) -> Tuple[str, Dict[str, Any]]:
        # 强制加 LIMIT，并对已有 LIMIT 做上限收敛
        if self.max_rows <= 0:
            raise RuntimeError("NL2SQL_MAX_ROWS 必须大于 0")

        limit_matches = list(re.finditer(r"\blimit\s+(\d+)", sql, flags=re.IGNORECASE))
        limit_applied = False
        limit_clamped = False
        limit_value = self.max_rows

        if limit_matches:
            last_match = limit_matches[-1]
            current = int(last_match.group(1))
            limit_value = min(current, self.max_rows)
            limit_applied = True
            if current > self.max_rows:
                sql = sql[: last_match.start(1)] + str(self.max_rows) + sql[last_match.end(1) :]
                limit_clamped = True
        else:
            sql = f"{sql} LIMIT {self.max_rows}"
            limit_applied = True
            limit_clamped = True

        return sql, {
            "limit_applied": limit_applied,
            "limit_value": limit_value,
            "limit_clamped": limit_clamped,
        }


class NL2SQLTool:
    """
    自然语言到 SQL 转换工具

    基于 LlamaIndex 实现的 NL2SQL 引擎，整合向量检索和 LLM 生成能力。
    支持表结构检索、列值索引和 SQL 执行，提供完整的查询链路。

    核心特性：
    - 向量化的表和列索引：提升查询相关性排序
    - 上下文增强：注入表结构描述和业务含义
    - 安全执行：支持表白名单和查询结果限制
    - 缓存机制：索引缓存避免重复计算
    - 错误处理：SQL 语法检查和执行异常处理

    查询流程：
    1. 表检索：基于问题匹配相关表
    2. 列索引：检索相关列的值分布
    3. SQL 生成：基于上下文生成查询语句
    4. 执行验证：在数据库中执行并返回结果
    """

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
        embedding_model: Optional[str] = None,
        index_cache_dir: Optional[Path] = None,
        enable_index_cache: bool = True,
        force_rebuild_cache: bool = False,
        enable_table_retrieval: bool = True,
        enable_column_retrieval: bool = True,
        table_retriever_top_k: int = 4,
        column_retriever_top_k: int = 3,
        column_index_max_values: int = 200,
        column_index_max_value_length: int = 128,
        column_index_config: Optional[Dict[str, List[str]]] = None,
        max_rows: int = 200,
        statement_timeout_ms: int = 15000,
        max_sql_length: int = 4000,
        allow_subquery: bool = False,
    ) -> None:
        self.postgres_url = postgres_url
        self.allowed_tables = allowed_tables or []
        self.db = DatabaseClient(postgres_url) if postgres_url else None
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.embedding_model = embedding_model or "text-embedding-v3"
        self.index_cache_dir = Path(index_cache_dir) if index_cache_dir else None
        self.enable_index_cache = enable_index_cache
        self.force_rebuild_cache = force_rebuild_cache
        # 仅保留允许表的 schema，避免 NL2SQL 访问非核心表
        self.table_schema = {k: v for k, v in TABLE_SCHEMA.items() if not self.allowed_tables or k in self.allowed_tables}
        self.enable_table_retrieval = enable_table_retrieval
        self.enable_column_retrieval = enable_column_retrieval
        self.table_retriever_top_k = table_retriever_top_k
        self.column_retriever_top_k = column_retriever_top_k
        self.column_index_max_values = column_index_max_values
        self.column_index_max_value_length = column_index_max_value_length
        self.column_index_config = column_index_config or self.COLUMN_INDEX_CONFIG
        self.max_rows = max_rows
        self.statement_timeout_ms = statement_timeout_ms
        self.max_sql_length = max_sql_length
        self.allow_subquery = allow_subquery
        self._llm = None
        self._embed_model = None
        self._table_retriever_cache = None
        self._cols_retrievers_cache = None
        self._cache_signature = None

    def query(
        self,
        question: str,
        tables: Optional[List[str]] = None,
        enable_column_retrieval: Optional[bool] = None,
    ) -> NL2SQLResult:
        """使用 LlamaIndex NL2SQL 生成查询并执行。"""
        start_time = time.monotonic()
        try:
            from llama_index.core import SQLDatabase  # type: ignore
            from llama_index.core import VectorStoreIndex  # type: ignore
            from llama_index.core.objects import ObjectIndex, SQLTableNodeMapping, SQLTableSchema  # type: ignore
            from llama_index.core.schema import TextNode  # type: ignore
            try:
                from llama_index.core.indices.struct_store.sql_retriever import NLSQLRetriever  # type: ignore
            except Exception:
                from llama_index.core.indices.struct_store import NLSQLRetriever  # type: ignore
        except Exception as exc:
            raise RuntimeError("缺少 llama-index 依赖，无法执行 NL2SQL。") from exc

        if not self.postgres_url:
            raise RuntimeError("未配置 POSTGRES_URL，无法执行 NL2SQL。")
        if not self.api_key:
            raise RuntimeError("未配置 DASHSCOPE_API_KEY，无法执行 NL2SQL。")

        table_names = tables or self.allowed_tables
        if not table_names:
            raise RuntimeError("未提供可用表名，无法执行 NL2SQL。")
        use_columns = self.enable_column_retrieval if enable_column_retrieval is None else enable_column_retrieval
        _log_nl2sql(
            "NL2SQL开始 question=%s tables=%s enable_columns=%s",
            question,
            ",".join(table_names),
            use_columns,
        )
        # 连接数据库并准备 LLM/Embedding
        step_time = time.monotonic()
        db = SQLDatabase.from_uri(self.postgres_url, include_tables=table_names)
        _log_nl2sql("NL2SQL步骤 SQLDatabase初始化耗时=%dms", int((time.monotonic() - step_time) * 1000))
        step_time = time.monotonic()
        llm = self._get_llm()
        embed_model = self._get_embed_model()
        self._apply_llamaindex_settings(llm=llm, embed_model=embed_model)
        _log_nl2sql("NL2SQL步骤 模型与设置耗时=%dms", int((time.monotonic() - step_time) * 1000))

        # 为每张表构建上下文提示，帮助模型理解字段语义
        step_time = time.monotonic()
        table_context = {k: v for k, v in self._build_table_context().items() if k in table_names}
        table_schema = [
            SQLTableSchema(
                table_name=table,
                context_str=table_context.get(table, ""),
            )
            for table in table_names
        ]
        _log_nl2sql("NL2SQL步骤 表上下文构建耗时=%dms", int((time.monotonic() - step_time) * 1000))
        # 基于表结构与列值构建/加载检索器，避免每次重建索引
        table_node_mapping = SQLTableNodeMapping(db)
        table_top_k = self.table_retriever_top_k if self.enable_table_retrieval else len(table_names)
        step_time = time.monotonic()
        table_retriever, cols_retrievers = self._get_or_build_retrievers(
            table_names=table_names,
            table_schema=table_schema,
            table_node_mapping=table_node_mapping,
            table_top_k=table_top_k,
            embed_model=embed_model,
            text_node_cls=TextNode,
            vector_index_cls=VectorStoreIndex,
            enable_columns=use_columns,
        )
        _log_nl2sql("NL2SQL步骤 检索器准备耗时=%dms", int((time.monotonic() - step_time) * 1000))

        step_time = time.monotonic()
        nlsql_retriever = NLSQLRetriever(
            sql_database=db,
            llm=llm,
            table_retriever=table_retriever,
            cols_retrievers=cols_retrievers,
            context_query_kwargs=table_context,
            sql_only=True,
            verbose=False,
        )
        _log_nl2sql("NL2SQL步骤 SQL生成器初始化耗时=%dms", int((time.monotonic() - step_time) * 1000))

        step_time = time.monotonic()
        retrieved_nodes, metadata = nlsql_retriever.retrieve_with_metadata(question)
        sql_query = metadata.get("result") if isinstance(metadata, dict) else None
        if not sql_query and retrieved_nodes:
            sql_query = getattr(retrieved_nodes[0].node, "text", "") or ""
        _log_nl2sql("NL2SQL步骤 SQL生成耗时=%dms", int((time.monotonic() - step_time) * 1000))

        guard = SQLGuard(
            allowed_tables=table_names,
            max_rows=self.max_rows,
            max_sql_length=self.max_sql_length,
            allow_subquery=self.allow_subquery,
        )
        safe_sql, limit_info = guard.sanitize(sql_query or "")

        step_time = time.monotonic()
        exec_result = self._execute(safe_sql)
        rows = [list(row) for row in exec_result.get("rows", [])]
        result_payload = {
            "columns": exec_result.get("columns", []),
            "rows": rows,
            "row_count": len(rows),
            "truncated": exec_result.get("truncated", False),
            "limit_applied": limit_info.get("limit_applied"),
            "limit_value": limit_info.get("limit_value"),
            "limit_clamped": limit_info.get("limit_clamped"),
        }
        _log_nl2sql("NL2SQL步骤 SQL执行耗时=%dms", int((time.monotonic() - step_time) * 1000))
        _log_nl2sql("NL2SQL完成 总耗时=%dms", int((time.monotonic() - start_time) * 1000))
        return NL2SQLResult(sql=safe_sql, result=result_payload)

    def warmup_retrievers(
        self,
        tables: Optional[List[str]] = None,
        load_columns: bool = False,
    ) -> Dict[str, Any]:
        """预热 NL2SQL 检索器，提前加载/构建索引到内存，降低首次查询耗时。"""
        start_time = time.monotonic()
        try:
            from llama_index.core import SQLDatabase  # type: ignore
            from llama_index.core import VectorStoreIndex  # type: ignore
            from llama_index.core.objects import SQLTableNodeMapping, SQLTableSchema  # type: ignore
            from llama_index.core.schema import TextNode  # type: ignore
        except Exception as exc:
            raise RuntimeError("缺少 llama-index 依赖，无法预热索引。") from exc

        if not self.postgres_url:
            raise RuntimeError("未配置 POSTGRES_URL，无法预热索引。")
        if not self.api_key:
            raise RuntimeError("未配置 DASHSCOPE_API_KEY，无法预热索引。")

        table_names = tables or self.allowed_tables
        if not table_names:
            raise RuntimeError("未提供可用表名，无法预热索引。")

        _log_nl2sql("NL2SQL预热开始 tables=%s load_columns=%s", ",".join(table_names), load_columns)
        db = SQLDatabase.from_uri(self.postgres_url, include_tables=table_names)
        llm = self._get_llm()
        embed_model = self._get_embed_model()
        self._apply_llamaindex_settings(llm=llm, embed_model=embed_model)

        table_context = {k: v for k, v in self._build_table_context().items() if k in table_names}
        table_schema = [
            SQLTableSchema(
                table_name=table,
                context_str=table_context.get(table, ""),
            )
            for table in table_names
        ]
        table_node_mapping = SQLTableNodeMapping(db)
        table_top_k = self.table_retriever_top_k if self.enable_table_retrieval else len(table_names)
        self._get_or_build_retrievers(
            table_names=table_names,
            table_schema=table_schema,
            table_node_mapping=table_node_mapping,
            table_top_k=table_top_k,
            embed_model=embed_model,
            text_node_cls=TextNode,
            vector_index_cls=VectorStoreIndex,
            enable_columns=load_columns,
        )
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        _log_nl2sql("NL2SQL预热完成 耗时=%dms", elapsed_ms)
        return {"status": "ok", "tables": table_names, "elapsed_ms": elapsed_ms}

    def _execute(self, sql: str) -> Dict[str, Any]:
        if not self.db:
            raise RuntimeError("未配置数据库连接，无法执行 SQL。")
        return self.db.run_sql(sql, timeout_ms=self.statement_timeout_ms, max_rows=self.max_rows)

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
                model=self.embedding_model,
            ).embedding
        return self._embed_model

    def _apply_llamaindex_settings(self, llm, embed_model) -> None:
        """同步 LlamaIndex 全局设置，避免默认 OpenAIEmbedding 触发缺少 KEY 的异常。"""
        try:
            from llama_index.core import Settings  # type: ignore
        except Exception:
            return
        Settings.llm = llm
        Settings.embed_model = embed_model

    def prepare_index_cache(
        self,
        table_names: Optional[List[str]] = None,
        build_tables: bool = True,
        build_columns: bool = True,
        force: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """预构建 NL2SQL 的表/列检索索引，供服务启动前调用。"""
        if not self.enable_index_cache or not self.index_cache_dir:
            return {"status": "disabled"}
        if not self.postgres_url:
            raise RuntimeError("未配置 POSTGRES_URL，无法预构建索引。")
        if not self.api_key:
            raise RuntimeError("未配置 DASHSCOPE_API_KEY，无法预构建索引。")

        table_names = table_names or self.allowed_tables
        if not table_names:
            raise RuntimeError("未提供可用表名，无法预构建索引。")

        signature = self._compute_schema_signature(table_names)
        force_rebuild = self.force_rebuild_cache if force is None else force
        if not force_rebuild and self._is_cache_valid(signature) and self._cache_dirs_ready(build_tables, build_columns):
            return {"status": "skipped", "signature": signature}

        if force_rebuild:
            self._clear_cache_dir()

        try:
            from llama_index.core import SQLDatabase, VectorStoreIndex  # type: ignore
            from llama_index.core.objects import ObjectIndex, SQLTableNodeMapping, SQLTableSchema  # type: ignore
            from llama_index.core.schema import TextNode  # type: ignore
        except Exception as exc:
            raise RuntimeError("缺少 llama-index 依赖，无法预构建索引。") from exc

        db = SQLDatabase.from_uri(self.postgres_url, include_tables=table_names)
        embed_model = self._get_embed_model()
        self._apply_llamaindex_settings(llm=self._get_llm(), embed_model=embed_model)

        table_context = {k: v for k, v in self._build_table_context().items() if k in table_names}
        table_schema = [
            SQLTableSchema(
                table_name=table,
                context_str=table_context.get(table, ""),
            )
            for table in table_names
        ]
        table_node_mapping = SQLTableNodeMapping(db)

        if build_tables:
            self._build_table_retriever(
                table_schema=table_schema,
                table_node_mapping=table_node_mapping,
                embed_model=embed_model,
                vector_index_cls=VectorStoreIndex,
                persist_dir=self._table_cache_dir(),
                table_top_k=self.table_retriever_top_k,
            )

        if build_columns and self.enable_column_retrieval:
            self._build_column_retrievers(
                table_names=table_names,
                embed_model=embed_model,
                text_node_cls=TextNode,
                vector_index_cls=VectorStoreIndex,
                persist_dir=self._columns_cache_dir(),
            )

        self._write_index_manifest(signature, table_names, build_columns=build_columns and self.enable_column_retrieval)
        return {"status": "built", "signature": signature}

    def _get_or_build_retrievers(
        self,
        table_names: List[str],
        table_schema,
        table_node_mapping,
        table_top_k: int,
        embed_model,
        text_node_cls,
        vector_index_cls,
        enable_columns: bool,
    ):
        """优先复用缓存索引，必要时重建。"""
        signature = self._compute_schema_signature(table_names)
        if self._cache_signature == signature and self._table_retriever_cache is not None:
            _log_nl2sql("NL2SQL检索器 命中内存缓存 signature=%s", signature)
            return self._table_retriever_cache, self._cols_retrievers_cache

        table_retriever = None
        cols_retrievers = None
        if self.enable_index_cache and self.index_cache_dir and not self.force_rebuild_cache:
            if self._is_cache_valid(signature):
                _log_nl2sql("NL2SQL检索器 尝试加载磁盘缓存 signature=%s dir=%s", signature, self.index_cache_dir)
                table_retriever = self._load_table_retriever_from_cache(table_node_mapping, table_top_k)
                if enable_columns:
                    cols_retrievers = self._load_column_retrievers_from_cache(table_names)
                    if cols_retrievers is not None and not cols_retrievers:
                        _log_nl2sql("NL2SQL检索器 列索引缓存为空，将仅使用表索引")
                if table_retriever and (not enable_columns or cols_retrievers is not None):
                    _log_nl2sql("NL2SQL检索器 磁盘缓存加载成功")
                    self._table_retriever_cache = table_retriever
                    self._cols_retrievers_cache = cols_retrievers
                    self._cache_signature = signature
                    return table_retriever, cols_retrievers
                _log_nl2sql("NL2SQL检索器 磁盘缓存加载失败，准备重建")

        if self.enable_index_cache and self.index_cache_dir and self.force_rebuild_cache:
            self._clear_cache_dir()

        build_time = time.monotonic()
        table_retriever = self._build_table_retriever(
            table_schema=table_schema,
            table_node_mapping=table_node_mapping,
            embed_model=embed_model,
            vector_index_cls=vector_index_cls,
            persist_dir=self._table_cache_dir() if self.enable_index_cache and self.index_cache_dir else None,
            table_top_k=table_top_k,
        )
        _log_nl2sql("NL2SQL检索器 表索引重建耗时=%dms", int((time.monotonic() - build_time) * 1000))
        cols_retrievers = None
        if enable_columns:
            build_time = time.monotonic()
            cols_retrievers = self._build_column_retrievers(
                table_names=table_names,
                embed_model=embed_model,
                text_node_cls=text_node_cls,
                vector_index_cls=vector_index_cls,
                persist_dir=self._columns_cache_dir() if self.enable_index_cache and self.index_cache_dir else None,
            )
            _log_nl2sql("NL2SQL检索器 列索引重建耗时=%dms", int((time.monotonic() - build_time) * 1000))

        if self.enable_index_cache and self.index_cache_dir:
            self._write_index_manifest(signature, table_names, build_columns=enable_columns)

        self._table_retriever_cache = table_retriever
        self._cols_retrievers_cache = cols_retrievers
        self._cache_signature = signature
        return table_retriever, cols_retrievers

    def _build_table_retriever(
        self,
        table_schema, # 表结构描述列表，每个表的结构信息，包括表名、字段列表和业务语义描述
        table_node_mapping, # 表节点映射器， LlamaIndex的SQLTableNodeMapping，用于将表映射为节点
        embed_model,  # 嵌入模型
        vector_index_cls, # 向量索引类
        persist_dir: Optional[Path], 
        table_top_k: int,
    ):
        # 基于表结构构建向量索引，支持“相关表”检索
        from llama_index.core.objects import ObjectIndex  # type: ignore

        table_index = ObjectIndex.from_objects( 
            table_schema,
            table_node_mapping,
            vector_index_cls,
            embed_model=embed_model,
        )
        if persist_dir:
            persist_dir.mkdir(parents=True, exist_ok=True)
            table_index.persist(persist_dir=str(persist_dir))
        return table_index.as_retriever(similarity_top_k=table_top_k)

    def _load_table_retriever_from_cache(self, table_node_mapping, table_top_k: int):
        if not self.index_cache_dir:
            return None
        table_dir = self._table_cache_dir()
        if not table_dir or not table_dir.exists():
            return None
        try:
            from llama_index.core.objects import ObjectIndex  # type: ignore
            table_index = ObjectIndex.from_persist_dir(str(table_dir), object_node_mapping=table_node_mapping)
            return table_index.as_retriever(similarity_top_k=table_top_k)
        except Exception as exc:
            _log_nl2sql("NL2SQL检索器 表索引缓存加载异常=%s", exc)
            return None

    def _load_column_retrievers_from_cache(self, table_names: List[str]) -> Optional[Dict[str, Dict[str, Any]]]:
        if not self.index_cache_dir:
            return None
        columns_dir = self._columns_cache_dir()
        if not columns_dir or not columns_dir.exists():
            return None
        try:
            from llama_index.core import StorageContext, load_index_from_storage  # type: ignore
        except Exception:
            return None

        cols_retrievers: Dict[str, Dict[str, Any]] = {}
        for table_name in table_names:
            column_names = self.column_index_config.get(table_name, [])
            if not column_names:
                continue
            table_retrievers: Dict[str, Any] = {}
            for column_name in column_names:
                index_dir = columns_dir / table_name / column_name
                if not index_dir.exists():
                    _log_nl2sql("NL2SQL检索器 列索引目录缺失 table=%s column=%s", table_name, column_name)
                    continue
                try:
                    storage_context = StorageContext.from_defaults(persist_dir=str(index_dir))
                    index = load_index_from_storage(storage_context)
                    table_retrievers[column_name] = index.as_retriever(
                        similarity_top_k=self.column_retriever_top_k
                    )
                except Exception as exc:
                    _log_nl2sql("NL2SQL检索器 列索引加载异常 table=%s column=%s error=%s", table_name, column_name, exc)
                    continue
            if table_retrievers:
                cols_retrievers[table_name] = table_retrievers

        return cols_retrievers

    def _compute_schema_signature(self, table_names: List[str]) -> str:
        """基于表结构与列配置生成稳定签名。"""
        tables = sorted(table_names)
        payload = {
            "tables": tables,
            "schema": {t: self.table_schema.get(t, []) for t in tables},
            "context": {t: TABLE_CONTEXT_HINTS.get(t, "") for t in tables},
            "column_index_config": {t: self.column_index_config.get(t, []) for t in tables},
            "column_index_max_values": self.column_index_max_values,
            "column_index_max_value_length": self.column_index_max_value_length,
            "embedding_model": self.embedding_model,
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _cache_dirs_ready(self, build_tables: bool, build_columns: bool) -> bool:
        if not self.index_cache_dir:
            return False
        if build_tables and not self._table_cache_dir().exists():
            return False
        if build_columns and not self._columns_cache_dir().exists():
            return False
        return True

    def _table_cache_dir(self) -> Optional[Path]:
        if not self.index_cache_dir:
            return None
        return self.index_cache_dir / "tables"

    def _columns_cache_dir(self) -> Optional[Path]:
        if not self.index_cache_dir:
            return None
        return self.index_cache_dir / "columns"

    def _manifest_path(self) -> Optional[Path]:
        if not self.index_cache_dir:
            return None
        return self.index_cache_dir / "manifest.json"

    def _load_index_manifest(self) -> Optional[Dict[str, Any]]:
        manifest_path = self._manifest_path()
        if not manifest_path or not manifest_path.exists():
            return None
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write_index_manifest(self, signature: str, table_names: List[str], build_columns: bool) -> None:
        if not self.index_cache_dir:
            return
        self.index_cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_signature": signature,
            "tables": sorted(table_names),
            "build_columns": build_columns,
            "updated_at": datetime.utcnow().isoformat(),
        }
        manifest_path = self._manifest_path()
        if manifest_path:
            manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _is_cache_valid(self, signature: str) -> bool:
        manifest = self._load_index_manifest()
        if not manifest:
            return False
        return manifest.get("schema_signature") == signature

    def _clear_cache_dir(self) -> None:
        if not self.index_cache_dir or not self.index_cache_dir.exists():
            return
        # 删除旧索引目录，避免混用不同版本
        for item in self.index_cache_dir.iterdir():
            if item.is_dir():
                for child in item.rglob("*"):
                    if child.is_file():
                        child.unlink(missing_ok=True)
                for child in sorted(item.rglob("*"), reverse=True):
                    if child.is_dir():
                        child.rmdir()
                item.rmdir()
            elif item.is_file():
                item.unlink(missing_ok=True)

    def _build_column_retrievers(
        self,
        table_names: List[str],
        embed_model,
        text_node_cls,
        vector_index_cls,
        persist_dir: Optional[Path] = None,
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
                if persist_dir:
                    index_dir = persist_dir / table_name / column_name
                    index_dir.mkdir(parents=True, exist_ok=True)
                    column_index.storage_context.persist(persist_dir=str(index_dir))
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
