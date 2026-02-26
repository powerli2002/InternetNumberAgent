"""
独立 Text2SQL Demo 脚本。

目标：
1. 输入自然语言问题，输出 SQL。
2. 独立完成 Prompt 组装、表/列检索、SQL 安全校验与执行校验。
3. 默认连接项目当前 PostgreSQL（读取 conf/.env + conf/config.yaml）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# 项目根目录：用于定位 conf/ 与本地数据目录。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 默认本地离线 embedding 模型路径（已验证可用）。
DEFAULT_LOCAL_BGE_MODEL = "/root/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181"
# Demo 默认 Milvus 连接参数（代码内显式配置，不依赖环境变量）。
DEFAULT_MILVUS_HOST = "10.99.8.28"
DEFAULT_MILVUS_PORT = 19530
INDEX_MANIFEST_PATH = PROJECT_ROOT / "agent" / "demo" / "output" / "text2sql_index_manifest.json"

# 直接运行脚本时补齐项目根路径，保证 `from agent...` 可用。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 直接复用主工程配置与 schema 常量，减少 demo 侧路径加载样板代码。
from agent.core.config import AgentConfig
from agent.core.schema import COLUMN_REVIEW_COMMENTS, TABLE_CONTEXT_HINTS, TABLE_REVIEW_COMMENTS, TABLE_SCHEMA

# SQL 生成主提示词：强调字段约束、标识符大小写与输出格式。
TEXT_TO_SQL_PROMPT = """Given an input question, first create a syntactically correct {dialect} query to run, then look at the results of the query and return the answer.
You can order the results by a relevant column to return the most interesting examples in the database.

Never query for all the columns from a specific table, only ask for a few relevant columns given the question.
Pay attention to use only the table and column names that you can see in the schema description.
Be careful to not query for columns that do not exist.
Pay attention to which column is in which table.
Also, qualify column names with table aliases when needed.

Important identifier rules for PostgreSQL:
1) Unquoted identifiers are folded to lowercase.
2) If a table/column name in schema contains uppercase letters or special characters, you MUST wrap it in double quotes exactly as shown in schema.
3) When using aliases, keep quoting, e.g. a."v6Prefixes", a."v6Upstream", a."v6Downstream".
4) Never change identifier spelling or letter case.

You are required to use the following format, each taking one line:
Question: Question here
SQLQuery: SQL Query to run
SQLResult: Result of the SQLQuery
Answer: Final answer here

Only use tables listed below.
{schema}

Question: {query_str}
SQLQuery: """


def build_text2sql_embedding(
    backend: str,
    api_key: str,
    base_url: str,
    model: str,
    device: str = "cpu",
    batch_size: int = 16,
    normalize: bool = True,
):
    """按配置构建 Text2SQL embedding，仅支持本地离线 bge。"""
    backend_value = (backend or "local_bge").strip().lower()
    if backend_value not in {"local_bge", "bge", "local"}:
        raise RuntimeError(f"Text2SQL Demo 仅支持本地 embedding，当前后端不受支持: {backend_value}")
    try:
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding  # type: ignore
    except Exception as exc:
        raise RuntimeError("缺少 llama-index-embeddings-huggingface 依赖，无法初始化本地 embedding。") from exc
    return HuggingFaceEmbedding(
        model_name=model or DEFAULT_LOCAL_BGE_MODEL,
        device=device,
        embed_batch_size=max(1, int(batch_size)),
        normalize=bool(normalize),
    )


def build_text2sql_llm(api_key: str, base_url: str, model: str):
    """使用项目内 DashScope LlamaIndex 适配器构建 LLM。"""
    if not api_key:
        raise RuntimeError("缺少 DASHSCOPE_API_KEY，无法调用 LLM。")
    try:
        from agent.tools.nl2sql_tool import DashScopeLlamaLLM
    except Exception as exc:
        raise RuntimeError("缺少 DashScopeLlamaLLM 依赖，无法初始化 LLM。") from exc
    return DashScopeLlamaLLM(
        api_key=api_key,
        base_url=base_url,
        model=model,
    ).llm


class DatabaseClient:
    """数据库执行器：统一连接与查询执行。"""

    def __init__(self, postgres_url: str) -> None:
        try:
            from sqlalchemy import create_engine  # type: ignore
        except Exception as exc:
            raise RuntimeError("缺少 SQLAlchemy，无法连接 PostgreSQL。") from exc
        # 只创建一个 engine，内部连接池由 SQLAlchemy 管理。
        self._engine = create_engine(postgres_url)

    def get_engine(self):
        return self._engine

    def run_sql(self, sql: str, timeout_ms: int, max_rows: int) -> Dict[str, Any]:
        # 在只读链路里执行 SQL，同时通过 statement_timeout 防止慢查询卡死。
        with self._engine.connect() as conn:
            from sqlalchemy import text as sql_text  # type: ignore

            # SET LOCAL 只对当前事务/语句生效，不污染全局连接配置。
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
            result = conn.execute(sql_text(sql))  # type: ignore
            columns = list(result.keys())
            # 多取 1 行用于判断是否截断，避免额外 count(*) 查询。
            rows = result.fetchmany(max_rows + 1)
            truncated = len(rows) > max_rows
            if truncated:
                rows = rows[:max_rows]
            return {"columns": columns, "rows": rows, "truncated": truncated}


class SQLGuard:
    """SQL 安全守卫：限制只读、表白名单和结果规模。"""

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
    _BLOCKED_FUNCTIONS = {"pg_sleep", "pg_terminate_backend", "pg_cancel_backend"}

    def __init__(self, allowed_tables: List[str], max_rows: int, max_sql_length: int, allow_subquery: bool) -> None:
        self.allowed_tables = {name.lower() for name in allowed_tables}
        self.max_rows = max_rows
        self.max_sql_length = max_sql_length
        self.allow_subquery = allow_subquery

    def sanitize(self, sql: str) -> Tuple[str, Dict[str, Any]]:
        # 步骤1：基础清洗和空值校验。
        raw_sql = (sql or "").strip()
        if not raw_sql:
            raise RuntimeError("生成 SQL 为空。")

        cleaned = self._strip_comments(raw_sql).strip().rstrip(";").strip()
        if not cleaned:
            raise RuntimeError("SQL 为空或仅包含注释。")
        if ";" in cleaned:
            raise RuntimeError("仅允许单条 SQL。")
        if len(cleaned) > self.max_sql_length:
            raise RuntimeError("SQL 长度超限。")

        # 步骤2：语义限制，仅允许 SELECT / WITH 开头。
        sql_no_strings = self._strip_string_literals(cleaned)
        if not re.match(r"^(select|with)\b", sql_no_strings, flags=re.IGNORECASE):
            raise RuntimeError("仅允许 SELECT/CTE 语句。")

        # 步骤3：关键字与危险函数黑名单。
        for keyword in self._BLOCKED_KEYWORDS:
            if re.search(rf"\b{re.escape(keyword)}\b", sql_no_strings, flags=re.IGNORECASE):
                raise RuntimeError(f"SQL 包含禁用关键字: {keyword}")
        for func in self._BLOCKED_FUNCTIONS:
            if re.search(rf"\b{re.escape(func)}\b", sql_no_strings, flags=re.IGNORECASE):
                raise RuntimeError(f"SQL 包含禁用函数: {func}")

        # 步骤4：表白名单，杜绝越权查询非核心表。
        for table in self._extract_tables(sql_no_strings):
            if table.lower() not in self.allowed_tables:
                raise RuntimeError(f"SQL 引用了未授权表: {table}")

        # 步骤5：统一 LIMIT 收敛，避免返回过大结果集。
        return self._enforce_limit(cleaned)

    def _strip_comments(self, sql: str) -> str:
        sql = re.sub(r"--.*", "", sql)
        sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
        return sql

    def _strip_string_literals(self, sql: str) -> str:
        return re.sub(r"'(?:''|[^'])*'", "''", sql)

    def _extract_tables(self, sql: str) -> List[str]:
        # 默认禁止子查询，简化权限边界与 SQL 解析复杂度。
        if not self.allow_subquery and re.search(r"\b(from|join)\s+\(", sql, flags=re.IGNORECASE):
            raise RuntimeError("当前策略禁止子查询。")
        pattern = re.compile(r'\b(from|join)\s+(?:only\s+)?(["\w\.]+)', re.IGNORECASE)
        tables: List[str] = []
        for match in pattern.finditer(sql):
            token = match.group(2).strip('"')
            if "." in token:
                token = token.split(".")[-1]
            if token:
                tables.append(token.lower())
        return tables

    def _enforce_limit(self, sql: str) -> Tuple[str, Dict[str, Any]]:
        if self.max_rows <= 0:
            raise RuntimeError("max_rows 必须大于 0。")

        limit_matches = list(re.finditer(r"\blimit\s+(\d+)", sql, flags=re.IGNORECASE))
        limit_value = self.max_rows
        limit_clamped = False
        if limit_matches:
            # 已有 LIMIT 时执行“上限钳制”，防止模型给出过大数值。
            last_match = limit_matches[-1]
            current = int(last_match.group(1))
            limit_value = min(current, self.max_rows)
            if current > self.max_rows:
                sql = sql[: last_match.start(1)] + str(self.max_rows) + sql[last_match.end(1) :]
                limit_clamped = True
        else:
            # 无 LIMIT 时强制追加，保证 demo 输出稳定可控。
            sql = f"{sql} LIMIT {self.max_rows}"
            limit_clamped = True

        return sql, {
            "limit_applied": True,
            "limit_value": limit_value,
            "limit_clamped": limit_clamped,
        }


@dataclass
class Text2SQLSettings:
    """Demo 引擎参数。"""

    postgres_url: str
    api_key: str
    base_url: str
    llm_model: str
    embedding_backend: str
    embedding_model: str
    allowed_tables: List[str]
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str = "nl2sql_index"
    embedding_device: str = "cuda"
    embedding_batch_size: int = 2
    embedding_normalize: bool = True
    print_llama_context: bool = True
    enable_table_retrieval: bool = True
    enable_column_retrieval: bool = True
    table_retriever_top_k: int = 4
    column_retriever_top_k: int = 3
    column_index_max_values: int = 200
    column_index_max_value_length: int = 128
    max_rows: int = 200
    statement_timeout_ms: int = 15000
    max_sql_length: int = 4000
    allow_subquery: bool = False


@dataclass
class RetrievalDebugInfo:
    """单次检索观测结果。"""

    table_scores: List[Tuple[str, float]]
    selected_tables: List[str]
    column_hits: Dict[str, List[Tuple[str, float]]]


@dataclass
class IndexBuildInfo:
    """索引构建与复用信息。"""

    build_seconds: float
    reused_memory: bool
    reused_milvus: bool


class Text2SQLEngine:
    """独立 Text2SQL 引擎：可直接用于离线 demo 评测。"""

    TABLE_PARTITION = "nl2sql_tables"
    COLUMN_PARTITION = "nl2sql_columns"

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

    def __init__(self, settings: Text2SQLSettings) -> None:
        self.settings = settings
        # DB 客户端用于两处：SQL 执行校验 + 列值抽样构建列检索索引。
        self.db = DatabaseClient(settings.postgres_url)
        self.milvus_host = str(settings.milvus_host or "localhost")
        self.milvus_port = int(settings.milvus_port or 19530)
        self.milvus_collection = str(settings.milvus_collection or "nl2sql_index")
        self._embedding_dim = 0
        self._manifest_path = INDEX_MANIFEST_PATH
        self._table_retriever_cache: Dict[Tuple[str, ...], Any] = {}
        self._column_retriever_cache: Dict[Tuple[str, ...], Any] = {}
        self._last_trace: Dict[str, Any] = {}
        # 仅保留 schema 中真实存在的表，避免配置漂移造成异常。
        self.allowed_tables = [t for t in settings.allowed_tables if t in TABLE_SCHEMA]
        self.table_schema = {t: TABLE_SCHEMA[t] for t in self.allowed_tables}

        llm = build_text2sql_llm(
            api_key=settings.api_key,
            base_url=settings.base_url,
            model=settings.llm_model,
        )
        embedding_start = time.perf_counter()
        embed_model = build_text2sql_embedding(
            backend=settings.embedding_backend,
            api_key=settings.api_key,
            base_url=settings.base_url,
            model=settings.embedding_model,
            device=settings.embedding_device,
            batch_size=settings.embedding_batch_size,
            normalize=settings.embedding_normalize,
        )
        embedding_seconds = time.perf_counter() - embedding_start

        try:
            from llama_index.core import Settings  # type: ignore
        except Exception as exc:
            raise RuntimeError("缺少 llama-index 依赖，无法初始化 Settings。") from exc
        # LlamaIndex 全局 Settings：后续 NLSQLRetriever 将直接读取这里的模型。
        Settings.llm = llm
        Settings.embed_model = embed_model
        self._llm = llm
        self._embed_model = embed_model
        print(f"[text2sql-demo] 计时: embedding_init_s={embedding_seconds:.3f} backend={settings.embedding_backend}")

    def text_to_sql(
        self,
        question: str,
        tables: Optional[List[str]] = None,
        enable_column_retrieval: Optional[bool] = None,
        execute_sql: bool = True,
    ) -> str:
        """输入自然语言，返回 SQL；可选执行 SQL 做可执行性校验。"""
        # 核心执行流程：
        # 1) 构建 SQLDatabase 与表上下文；
        # 2) 构建表检索器（可选列检索器）；
        # 3) 调用 NLSQLRetriever 生成 SQL；
        # 4) SQLGuard 安全收敛；
        # 5) 可选执行 SQL 验证可运行性。
        try:
            from llama_index.core import SQLDatabase, VectorStoreIndex  # type: ignore
            from llama_index.core.prompts import PromptTemplate  # type: ignore
            from llama_index.core.schema import QueryBundle, TextNode  # type: ignore
            from llama_index.core.indices.struct_store.sql_retriever import NLSQLRetriever  # type: ignore
        except Exception as exc:
            raise RuntimeError("缺少 llama-index 依赖，无法执行 Text2SQL。") from exc

        question = (question or "").strip()
        if not question:
            raise RuntimeError("问题不能为空。")

        table_names = tables or self.allowed_tables
        table_names = [name for name in table_names if name in self.table_schema]
        if not table_names:
            raise RuntimeError("可用表为空，无法生成 SQL。")
        # 调用参数优先级：显式入参 > settings 默认值。
        use_columns = self.settings.enable_column_retrieval if enable_column_retrieval is None else enable_column_retrieval

        # SQLDatabase 负责读取 PostgreSQL schema 并提供 SQL 执行接口给检索器。
        sql_db = SQLDatabase.from_uri(self.settings.postgres_url, include_tables=table_names)
        # 表上下文构建与检索参数说明：
        # 1) table_context：由 _build_table_context 生成，包含字段列表 + 表注释 + 字段注释；
        # 2) 表检索使用单独向量索引，先检索再透传 selected_tables 给 NLSQLRetriever；
        # 3) 通过缓存与 Milvus 分区实现“首次构建、后续复用”。
        table_context = {k: v for k, v in self._build_table_context().items() if k in table_names}
        table_top_k = self.settings.table_retriever_top_k if self.settings.enable_table_retrieval else len(table_names)
        table_top_k = max(1, min(table_top_k, len(table_names)))
        table_retriever, table_build_info = self._build_table_retriever(
            table_names=table_names,
            table_context=table_context,
            text_node_cls=TextNode,
            vector_index_cls=VectorStoreIndex,
            top_k=table_top_k,
        )
        print(
            "[text2sql-demo] 计时: table_index_build_s="
            f"{table_build_info.build_seconds:.3f} memory_reuse={table_build_info.reused_memory} "
            f"milvus_reuse={table_build_info.reused_milvus}"
        )
        cols_retrievers = None
        column_build_info = IndexBuildInfo(build_seconds=0.0, reused_memory=False, reused_milvus=False)
        if use_columns:
            # 列检索解决“列值匹配”（例如国家、组织名）提升 SQL 精度。
            cols_retrievers, column_build_info = self._build_column_retrievers(
                table_names=table_names,
                text_node_cls=TextNode,
                vector_index_cls=VectorStoreIndex,
            )
            print(
                "[text2sql-demo] 计时: column_index_build_s="
                f"{column_build_info.build_seconds:.3f} memory_reuse={column_build_info.reused_memory} "
                f"milvus_reuse={column_build_info.reused_milvus}"
            )
        # 先执行一次真实检索并缓存命中，后续 SQL 生成直接复用，避免“为了打印再查一遍”。
        debug_info = self._collect_selected_candidates(question, table_retriever, cols_retrievers)
        selected_tables = debug_info.selected_tables
        if not selected_tables:
            raise RuntimeError("表检索未命中任何候选表。")
        selected_context = {name: table_context[name] for name in selected_tables if name in table_context}

        if self.settings.print_llama_context:
            # 输出本次真实命中的表/列，便于分析检索效果。
            self._print_selected_candidates(debug_info)

        # sql_only=True 要求 retriever 返回 SQL 文本而非自然语言答案。# LlamaIndex 文本到 SQL 功能被封装在一个查询引擎中
        retriever_kwargs: Dict[str, Any] = {
            "sql_database": sql_db,
            "llm": self._llm,
            "text_to_sql_prompt": PromptTemplate(TEXT_TO_SQL_PROMPT),
            "tables": selected_tables,
            "context_query_kwargs": selected_context,
            "sql_only": True,
            "verbose": False,
        }
        if use_columns and cols_retrievers:
            retriever_kwargs["cols_retrievers"] = cols_retrievers
        retriever = NLSQLRetriever(
            **retriever_kwargs,
        )
        if self.settings.print_llama_context:
            # 打印 LlamaIndex 在本次查询中拼装的 schema/table_desc_str（即发送给 LLM 的表结构上下文）。
            query_bundle = QueryBundle(question)
            table_desc_str = retriever._get_table_context(query_bundle)  # type: ignore[attr-defined]
            # print("[text2sql-demo] LlamaIndex table context begin")
            # print(table_desc_str)
            # print("[text2sql-demo] LlamaIndex table context end")
        else:
            query_bundle = QueryBundle(question)
            table_desc_str = retriever._get_table_context(query_bundle)  # type: ignore[attr-defined]
        _, metadata = retriever.retrieve_with_metadata(question)
        # 严格要求 SQL 从 metadata.result 返回，不再做节点文本兜底。
        if not isinstance(metadata, dict):
            raise RuntimeError("NLSQLRetriever 返回 metadata 格式错误。")
        sql_query = str(metadata.get("result") or "").strip()
        if not sql_query:
            raise RuntimeError("NLSQLRetriever 未返回 SQL 结果。")

        guard = SQLGuard(
            allowed_tables=table_names,
            max_rows=self.settings.max_rows,
            max_sql_length=self.settings.max_sql_length,
            allow_subquery=self.settings.allow_subquery,
        )
        safe_sql, _ = guard.sanitize(sql_query or "")

        # Demo 默认执行一次 SQL 验证可执行性；但对外仍只输出 SQL。
        if execute_sql:
            self.db.run_sql(
                sql=safe_sql,
                timeout_ms=self.settings.statement_timeout_ms,
                max_rows=self.settings.max_rows,
            )
        self._last_trace = {
            "question": question,
            "table_scores": debug_info.table_scores,
            "selected_tables": debug_info.selected_tables,
            "column_hits": debug_info.column_hits,
            "table_context": table_desc_str,
            "generated_sql": safe_sql,
        }
        return safe_sql

    def last_trace(self) -> Dict[str, Any]:
        """返回最近一次 text_to_sql 的调试轨迹。"""
        return dict(self._last_trace)

    def _build_table_context(self) -> Dict[str, str]:
        # 将结构化 schema 信息压成字符串，作为每张表的 context_str。
        context: Dict[str, str] = {}
        for table_name, columns in self.table_schema.items():
            # 字段全集必须保留，否则模型会凭空臆造字段。
            parts = [f"字段: {', '.join(columns)}"]

            table_comment = TABLE_REVIEW_COMMENTS.get(table_name, "")
            if table_comment:
                parts.append(f"表说明: {table_comment}")

            hint = TABLE_CONTEXT_HINTS.get(table_name, "")
            if hint:
                parts.append(f"字段约定: {hint}")

            column_comments = COLUMN_REVIEW_COMMENTS.get(table_name, {})
            if column_comments:
                items: List[str] = []
                for column in columns:
                    comment = column_comments.get(column, "")
                    if comment:
                        items.append(f"{column}: {comment}")
                if items:
                    # 控制每表注释数量，避免 prompt 过长导致生成不稳定。
                    parts.append(f"字段释义: {'；'.join(items[:24])}")

            context[table_name] = "。".join(parts)
        return context

    def _milvus_uri(self) -> str:
        # 统一转换为 MilvusClient 可识别的 URI。
        return f"http://{self.milvus_host}:{self.milvus_port}"

    def _resolve_embedding_dim(self, embed_model) -> int:
        # 通过一次实际 embedding 推断维度，避免多分支兼容逻辑。
        if self._embedding_dim > 0:
            return self._embedding_dim
        sample = embed_model.get_text_embedding("dimension")
        if not sample:
            raise RuntimeError("embedding 维度推断失败，返回向量为空。")
        self._embedding_dim = len(sample)
        return self._embedding_dim

    def _ensure_milvus_partition(self, partition_name: str) -> None:
        try:
            from pymilvus import Collection, connections, utility  # type: ignore
        except Exception as exc:
            raise RuntimeError("缺少 pymilvus，无法创建 Milvus partition。") from exc
        connections.connect(host=self.milvus_host, port=str(self.milvus_port))
        if not utility.has_collection(self.milvus_collection):
            raise RuntimeError(f"Milvus collection 不存在: {self.milvus_collection}")
        collection = Collection(self.milvus_collection)
        if not collection.has_partition(partition_name):
            collection.create_partition(partition_name)

    def _create_milvus_vector_store(self, embed_model):
        # 通过 LlamaIndex MilvusVectorStore 接入，保留向量检索一致性。
        try:
            from llama_index.vector_stores.milvus import MilvusVectorStore  # type: ignore
        except Exception as exc:
            raise RuntimeError("缺少 llama-index-vector-stores-milvus 依赖，无法使用 Milvus 索引。") from exc
        dim = self._resolve_embedding_dim(embed_model)
        return MilvusVectorStore(
            uri=self._milvus_uri(),
            collection_name=self.milvus_collection,
            dim=dim,
            overwrite=False,
            use_async_client=False,
        )

    def _milvus_query_kwargs(self, partition_name: str) -> Dict[str, Any]:
        return {"milvus_partition_names": [partition_name]} if partition_name else {}

    def _build_table_retriever(
        self,
        table_names: List[str],
        table_context: Dict[str, str],
        text_node_cls,
        vector_index_cls,
        top_k: int,
    ) -> Tuple[Any, IndexBuildInfo]:
        # 表索引：首次写入 Milvus，后续优先复用内存，再复用 Milvus 分区。
        try:
            from llama_index.core.storage.storage_context import StorageContext  # type: ignore
            from llama_index.core.vector_stores.types import MetadataFilter, MetadataFilters  # type: ignore
        except Exception as exc:
            raise RuntimeError("缺少 llama-index 依赖，无法构建表索引。") from exc
        cache_key = tuple(sorted(table_names))
        if cache_key in self._table_retriever_cache:
            return self._table_retriever_cache[cache_key], IndexBuildInfo(0.0, True, False)

        build_start = time.perf_counter()
        vector_store = self._create_milvus_vector_store(self._embed_model)
        self._ensure_milvus_partition(self.TABLE_PARTITION)
        query_kwargs = self._milvus_query_kwargs(self.TABLE_PARTITION)

        signature = self._build_signature(
            kind="table",
            table_names=table_names,
            extra={
                "table_top_k": top_k,
                "table_context": {k: table_context.get(k, "") for k in sorted(table_names)},
                "embedding_backend": self.settings.embedding_backend,
                "embedding_model": self.settings.embedding_model,
            },
        )
        manifest = self._load_index_manifest()
        manifest_item = manifest.get("table", {})
        reuse_milvus = (
            manifest_item.get("signature") == signature
            and self._partition_entity_count(self.TABLE_PARTITION) >= len(table_names)
        )

        if reuse_milvus:
            table_index = vector_index_cls.from_vector_store(
                vector_store=vector_store,
                embed_model=self._embed_model,
            )
        else:
            storage_context = StorageContext.from_defaults(vector_store=vector_store)
            nodes = []
            for table_name in table_names:
                payload = f"表名: {table_name}\n{table_context.get(table_name, '')}"
                nodes.append(
                    text_node_cls(
                        id_=f"table::{table_name}",
                        text=payload,
                        metadata={"name": table_name, "kind": "table"},
                    )
                )
            table_index = vector_index_cls(
                nodes,
                embed_model=self._embed_model,
                storage_context=storage_context,
                milvus_partition_name=self.TABLE_PARTITION,
            )
            manifest["table"] = {
                "signature": signature,
                "entity_count": len(nodes),
            }
            self._save_index_manifest(manifest)

        table_filters = MetadataFilters(filters=[MetadataFilter(key="kind", value="table")])
        table_retriever = table_index.as_retriever(
            similarity_top_k=top_k,
            filters=table_filters,
            **query_kwargs,
        )
        self._table_retriever_cache[cache_key] = table_retriever
        elapsed = time.perf_counter() - build_start
        return table_retriever, IndexBuildInfo(elapsed, False, reuse_milvus)

    def _build_column_retrievers(
        self,
        table_names: List[str],
        text_node_cls,
        vector_index_cls,
    ) -> Tuple[Dict[str, Dict[str, Any]], IndexBuildInfo]:
        # 列索引：首次写入 Milvus，后续优先复用内存，再复用 Milvus 分区。
        try:
            from llama_index.core.storage.storage_context import StorageContext  # type: ignore
            from llama_index.core.vector_stores.types import MetadataFilter, MetadataFilters  # type: ignore
        except Exception as exc:
            raise RuntimeError("缺少 SQLAlchemy，无法构建列检索器。") from exc

        cache_key = tuple(sorted(table_names))
        if cache_key in self._column_retriever_cache:
            cached = self._column_retriever_cache[cache_key]
            return cached, IndexBuildInfo(0.0, True, False)

        build_start = time.perf_counter()
        vector_store = self._create_milvus_vector_store(self._embed_model)
        self._ensure_milvus_partition(self.COLUMN_PARTITION)
        query_kwargs = self._milvus_query_kwargs(self.COLUMN_PARTITION)

        signature = self._build_signature(
            kind="column",
            table_names=table_names,
            extra={
                "column_index_config": {k: self.COLUMN_INDEX_CONFIG.get(k, []) for k in sorted(table_names)},
                "column_index_max_values": self.settings.column_index_max_values,
                "column_index_max_value_length": self.settings.column_index_max_value_length,
                "embedding_backend": self.settings.embedding_backend,
                "embedding_model": self.settings.embedding_model,
            },
        )
        manifest = self._load_index_manifest()
        manifest_item = manifest.get("column", {})
        reuse_milvus = (
            manifest_item.get("signature") == signature
            and int(manifest_item.get("entity_count") or 0) > 0
            and self._partition_entity_count(self.COLUMN_PARTITION) >= int(manifest_item.get("entity_count") or 0)
        )

        if reuse_milvus:
            column_index = vector_index_cls.from_vector_store(
                vector_store=vector_store,
                embed_model=self._embed_model,
            )
            cols_retrievers: Dict[str, Dict[str, Any]] = {}
            for table_name in table_names:
                column_names = self.COLUMN_INDEX_CONFIG.get(table_name, [])
                if not column_names:
                    raise RuntimeError(f"列索引配置缺失: {table_name}")
                valid_columns = [name for name in column_names if name in self.table_schema.get(table_name, [])]
                if not valid_columns:
                    raise RuntimeError(f"列索引配置与表结构不一致: {table_name}")
                table_retrievers: Dict[str, Any] = {}
                for column_name in valid_columns:
                    filters = MetadataFilters(
                        filters=[
                            MetadataFilter(key="table", value=table_name),
                            MetadataFilter(key="column", value=column_name),
                        ]
                    )
                    table_retrievers[column_name] = column_index.as_retriever(
                        similarity_top_k=self.settings.column_retriever_top_k,
                        filters=filters,
                        **query_kwargs,
                    )
                if table_retrievers:
                    cols_retrievers[table_name] = table_retrievers
            if not cols_retrievers:
                raise RuntimeError("列检索器构建失败：Milvus 复用模式未生成任何列检索器。")
            self._column_retriever_cache[cache_key] = cols_retrievers
            elapsed = time.perf_counter() - build_start
            return cols_retrievers, IndexBuildInfo(elapsed, False, True)
        else:
            try:
                from sqlalchemy import MetaData, Table, select  # type: ignore
            except Exception as exc:
                raise RuntimeError("缺少 SQLAlchemy，无法构建列检索器。") from exc
            metadata = MetaData()
            engine = self.db.get_engine()
            cols_retrievers: Dict[str, Dict[str, Any]] = {}
            all_nodes: List[Any] = []

            for table_name in table_names:
                column_names = self.COLUMN_INDEX_CONFIG.get(table_name, [])
                if not column_names:
                    raise RuntimeError(f"列索引配置缺失: {table_name}")
                try:
                    table = Table(table_name, metadata, autoload_with=engine)
                except Exception as exc:
                    raise RuntimeError(f"加载表结构失败: {table_name}") from exc
                table_retrievers: Dict[str, Any] = {}
                for column_name in column_names:
                    if column_name not in table.c:
                        raise RuntimeError(f"列索引配置与数据库字段不一致: {table_name}.{column_name}")
                    column = table.c[column_name]
                    stmt = select(column).distinct().limit(self.settings.column_index_max_values)
                    values = self._fetch_distinct_values(engine, stmt)
                    nodes = self._build_column_nodes(
                        values=values,
                        text_node_cls=text_node_cls,
                        meta={"table": table_name, "column": column_name},
                    )
                    if not nodes:
                        continue
                    all_nodes.extend(nodes)
                    table_retrievers[column_name] = None
                if table_retrievers:
                    cols_retrievers[table_name] = table_retrievers

            if not cols_retrievers or not all_nodes:
                raise RuntimeError("列检索器构建失败：未生成任何可索引列值。")

            storage_context = StorageContext.from_defaults(vector_store=vector_store)
            column_index = vector_index_cls(
                all_nodes,
                embed_model=self._embed_model,
                storage_context=storage_context,
                milvus_partition_name=self.COLUMN_PARTITION,
            )
            manifest["column"] = {
                "signature": signature,
                "entity_count": len(all_nodes),
            }
            self._save_index_manifest(manifest)
            for table_name, table_retrievers in cols_retrievers.items():
                for column_name in list(table_retrievers.keys()):
                    filters = MetadataFilters(
                        filters=[
                            MetadataFilter(key="table", value=table_name),
                            MetadataFilter(key="column", value=column_name),
                        ]
                    )
                    table_retrievers[column_name] = column_index.as_retriever(
                        similarity_top_k=self.settings.column_retriever_top_k,
                        filters=filters,
                        **query_kwargs,
                    )

            self._column_retriever_cache[cache_key] = cols_retrievers
            elapsed = time.perf_counter() - build_start
            return cols_retrievers, IndexBuildInfo(elapsed, False, False)

    def _build_signature(self, kind: str, table_names: List[str], extra: Dict[str, Any]) -> str:
        payload = {
            "kind": kind,
            "table_names": sorted(table_names),
            "extra": extra,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _load_index_manifest(self) -> Dict[str, Any]:
        if not self._manifest_path.exists():
            return {}
        try:
            return json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"索引 manifest 解析失败: {self._manifest_path}") from exc

    def _save_index_manifest(self, data: Dict[str, Any]) -> None:
        self._manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self._manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _partition_entity_count(self, partition_name: str) -> int:
        try:
            from pymilvus import Collection, connections, utility  # type: ignore
        except Exception as exc:
            raise RuntimeError("缺少 pymilvus，无法统计 Milvus partition 实体数量。") from exc
        connections.connect(host=self.milvus_host, port=str(self.milvus_port))
        if not utility.has_collection(self.milvus_collection):
            raise RuntimeError(f"Milvus collection 不存在: {self.milvus_collection}")
        collection = Collection(self.milvus_collection)
        for partition in collection.partitions:
            if partition.name == partition_name:
                return int(partition.num_entities)
        return 0

    def _collect_selected_candidates(self, question: str, table_retriever, cols_retrievers) -> RetrievalDebugInfo:
        # 在主链路前执行一次检索，后续逻辑直接复用这次结果，避免重复检索。
        from llama_index.core.schema import QueryBundle  # type: ignore

        if not question:
            raise RuntimeError("问题不能为空。")

        # 将自然语言问题封装为标准查询对象，供表检索与列检索复用。
        query_bundle = QueryBundle(question)
        # 记录表候选及其相关性分数，格式: [(table_name, score), ...]。
        table_scores: List[Tuple[str, float]] = []
        nodes = table_retriever.retrieve(query_bundle)
        for node in nodes:
            # 严格要求表名来自节点元数据的 name 字段。
            name = str(node.node.metadata["name"]).strip()
            if not name:
                raise RuntimeError("表检索结果缺少表名。")
            # 使用检索返回分数，不做默认值回退。
            score = float(node.score)
            table_scores.append((name, score))

        # 按检索顺序做表名去重，保留首个命中对应的优先级。
        seen = set()
        selected_tables: List[str] = []
        for name, _ in table_scores:
            if name in seen:
                continue
            seen.add(name)
            selected_tables.append(name)

        # 保存每张表的列候选命中，格式: {table: [(column, best_score), ...]}。
        column_hits_by_table: Dict[str, List[Tuple[str, float]]] = {}
        if cols_retrievers and selected_tables:
            # 仅在已选中的表内执行列检索，不做“未命中时全表扫描”兜底。
            selected_set = set(selected_tables)
            for table_name, table_retrievers in cols_retrievers.items():
                if table_name not in selected_set:
                    continue
                column_hits: List[Tuple[str, float]] = []
                for column_name, retriever in table_retrievers.items():
                    # 执行列值向量检索，命中结果用于估计该列与问题的相关性。
                    nodes = retriever.retrieve(query_bundle)
                    if not nodes:
                        # 未命中则不纳入候选列。
                        continue
                    # 以该列命中结果中的最高分作为列级相关性代表分数。
                    best_score = max(float(node.score) for node in nodes)
                    column_hits.append((column_name, best_score))
                if not column_hits:
                    # 当前表没有任何列命中时，不写入调试结果。
                    continue
                # 按分数从高到低排序，便于后续打印与排查。
                column_hits.sort(key=lambda item: item[1], reverse=True)
                column_hits_by_table[table_name] = column_hits
        # 统一返回表级与列级候选信息，供后续打印和链路复用。
        return RetrievalDebugInfo(
            table_scores=table_scores,
            selected_tables=selected_tables,
            column_hits=column_hits_by_table,
        )

    def _print_selected_candidates(self, debug_info: RetrievalDebugInfo) -> None:
        # 打印真实命中候选（来自单次检索结果缓存）。
        if debug_info.selected_tables:
            scored_tables = ", ".join([f"{name}(score={score:.4f})" for name, score in debug_info.table_scores])
            if scored_tables:
                print("[text2sql-demo] 选中表(含分数): " + scored_tables)
            else:
                print("[text2sql-demo] 选中表: " + ", ".join(debug_info.selected_tables))
        if not debug_info.column_hits:
            return
        for table_name, column_hits in debug_info.column_hits.items():
            column_list = [f"{name}(score={score:.4f})" for name, score in column_hits]
            print(f"[text2sql-demo] 选中列(含分数): {table_name} -> {', '.join(column_list)}")

    def _fetch_distinct_values(self, engine, stmt) -> List[Any]:
        # 单独封装数据库访问，便于后续替换为采样策略或缓存策略。
        with engine.connect() as conn:
            result = conn.execute(stmt)  # type: ignore
            return [row[0] for row in result.fetchall()]

    def _build_column_nodes(self, values: List[Any], text_node_cls, meta: Dict[str, str]) -> List[Any]:
        # 把原始值转成向量节点，并做去重/限长过滤，提升检索质量。
        nodes = []
        seen = set()
        table_name = str(meta.get("table", ""))
        column_name = str(meta.get("column", ""))
        for value in values:
            text = self._normalize_value(value)
            if not text:
                continue
            if len(text) > self.settings.column_index_max_value_length:
                continue
            if text in seen:
                continue
            seen.add(text)
            node_id = hashlib.sha256(f"{table_name}::{column_name}::{text}".encode("utf-8")).hexdigest()
            nodes.append(text_node_cls(id_=f"col::{node_id}", text=text, metadata=meta))
        return nodes

    def _normalize_value(self, value: Any) -> Optional[str]:
        # 标准化规则：空值过滤，容器拼接，dict 序列化，其他转字符串。
        if value is None:
            return None
        if isinstance(value, (list, tuple, set)):
            parts = [str(item).strip() for item in value if item is not None and str(item).strip()]
            return ", ".join(parts) if parts else None
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        text = str(value).strip()
        return text or None


def _resolve_tables(raw_tables: Optional[str], allowed_tables: List[str]) -> List[str]:
    # --tables 指定时做白名单裁剪，防止传入不存在或越权表名。
    if not raw_tables:
        return allowed_tables
    selected = [name.strip() for name in raw_tables.split(",") if name.strip()]
    return [name for name in selected if name in allowed_tables]


def build_arg_parser() -> argparse.ArgumentParser:
    # CLI 仅暴露评测所需参数，避免 demo 脚本过于复杂。
    parser = argparse.ArgumentParser(description="独立 Text2SQL Demo：输入自然语言，输出 SQL。")
    parser.add_argument(
        "question",
        nargs="?",
        default="",
        help="自然语言问题（可选；未提供时可从 stdin 读取，最终默认: 统计美国的AS数量）。",
    )
    parser.add_argument("--tables", default="", help="限定表名，逗号分隔；默认全部核心表。")
    parser.add_argument("--postgres-url", default="", help="覆盖 PostgreSQL 连接串。")
    parser.add_argument("--api-key", default="", help="覆盖百炼 API Key。")
    parser.add_argument("--milvus-host", default=DEFAULT_MILVUS_HOST, help=f"Milvus 主机（默认 {DEFAULT_MILVUS_HOST}）。")
    parser.add_argument("--milvus-port", type=int, default=DEFAULT_MILVUS_PORT, help=f"Milvus 端口（默认 {DEFAULT_MILVUS_PORT}）。")
    parser.add_argument("--base-url", default="https://dashscope.aliyuncs.com/compatible-mode/v1", help="覆盖百炼兼容 API Base URL。")
    parser.add_argument("--model", default="qwen-turbo", help="覆盖 LLM 模型名。")
    parser.add_argument(
        "--embedding-backend",
        choices=["local_bge"],
        default="local_bge",
        help="embedding 后端（固定 local_bge，不支持百炼 embedding）。",
    )
    parser.add_argument(
        "--embedding-model",
        default=DEFAULT_LOCAL_BGE_MODEL,
        help=f"覆盖 embedding 模型名或本地目录（默认 {DEFAULT_LOCAL_BGE_MODEL}）。",
    )
    parser.add_argument(
        "--embedding-device",
        choices=["cuda"],
        default="cuda",
        help="本地 embedding 推理设备（固定 cuda）。",
    )
    parser.add_argument(
        "--embedding-batch-size",
        type=int,
        default=2,
        help="本地 embedding 批大小（默认 2）。",
    )
    parser.add_argument(
        "--disable-embedding-normalize",
        action="store_true",
        help="关闭本地 embedding 归一化。",
    )
    parser.add_argument(
        "--print-llama-context",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="打印表/列命中与 LlamaIndex 发送给大模型的上下文（输出到 stdout）。",
    )
    parser.add_argument(
        "--disable-column-retrieval",
        action="store_true",
        help="关闭列检索，仅使用表检索。",
    )
    parser.add_argument(
        "--no-exec",
        action="store_true",
        help="仅生成 SQL，不执行数据库校验。",
    )
    return parser


def main() -> int:
    # 1) 解析命令行参数；
    # 2) 加载项目配置并合并环境变量覆盖；
    # 3) 构建引擎并执行 text_to_sql；
    # 4) 标准输出 SQL（评测系统可直接采集）。
    parser = build_arg_parser()
    args = parser.parse_args()

    # 复用 AgentConfig，保证 demo 默认连接与线上服务一致。
    cfg = AgentConfig.load(project_root=PROJECT_ROOT)

    # 支持命令行覆盖，方便离线评测切换不同数据库/模型。
    # 按要求仅使用代码参数/配置文件，不读取环境变量兜底。
    postgres_url = args.postgres_url or cfg.postgres_url or ""
    api_key = args.api_key or cfg.dashscope_api_key or ""
    base_url = args.base_url
    llm_model = args.model
    embedding_backend = args.embedding_backend
    embedding_model = args.embedding_model
    embedding_device = args.embedding_device
    embedding_batch_size = args.embedding_batch_size
    embedding_normalize = not args.disable_embedding_normalize

    if not postgres_url:
        raise RuntimeError("未找到 POSTGRES_URL，无法连接 PostgreSQL。")
    if not api_key:
        raise RuntimeError("未找到 DASHSCOPE_API_KEY，无法调用 LLM。")

    # 默认使用核心 16 表，也可通过 --tables 显式子集评测。
    allowed_tables = list(cfg.allowed_tables) if cfg.allowed_tables else list(TABLE_SCHEMA.keys())
    table_names = _resolve_tables(args.tables, allowed_tables)
    if not table_names:
        raise RuntimeError("可用表为空，请检查 --tables 参数。")

    settings = Text2SQLSettings(
        postgres_url=postgres_url,
        api_key=api_key,
        base_url=base_url,
        llm_model=llm_model,
        embedding_backend=embedding_backend,
        embedding_model=embedding_model,
        embedding_device=embedding_device,
        embedding_batch_size=max(1, int(embedding_batch_size)),
        embedding_normalize=embedding_normalize,
        print_llama_context=args.print_llama_context,
        allowed_tables=table_names,
        milvus_host=str(args.milvus_host or DEFAULT_MILVUS_HOST),
        milvus_port=int(args.milvus_port or DEFAULT_MILVUS_PORT),
        milvus_collection=cfg.nl2sql_vector_collection,
        enable_column_retrieval=not args.disable_column_retrieval,
        max_rows=cfg.nl2sql_max_rows,
        statement_timeout_ms=cfg.nl2sql_statement_timeout_ms,
        max_sql_length=cfg.nl2sql_max_sql_length,
        allow_subquery=cfg.nl2sql_allow_subquery,
    )

    engine = Text2SQLEngine(settings=settings)
    question = (args.question or "").strip()
    if not question and not sys.stdin.isatty():
        question = sys.stdin.read().strip()
    if not question:
        question = "统计美国的AS数量"
    sql = engine.text_to_sql(
        question=question,
        tables=table_names,
        enable_column_retrieval=not args.disable_column_retrieval,
        execute_sql=not args.no_exec,
    )
    # 按当前调试约定：stdout 会输出中间信息，最后一行输出 SQL。
    print(sql)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[text2sql-demo] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
