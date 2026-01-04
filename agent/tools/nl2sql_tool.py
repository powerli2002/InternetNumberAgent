from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from llama_index.core.bridge.pydantic import PrivateAttr

from agent.schema import TABLE_SCHEMA


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

                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt}],
                    stream=False,
                )
                text = response.choices[0].message.content or ""
                return CompletionResponse(text=text, raw=response)

            def stream_complete(self, prompt: str, formatted: bool = False, **kwargs):  # type: ignore[override]
                from llama_index.core.base.llms.types import CompletionResponse  # type: ignore

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
        self._engine = create_engine(self.postgres_url)
        return self._engine

    def run_sql(self, sql: str) -> List[Tuple]:
        engine = self._get_engine()
        with engine.connect() as conn:
            from sqlalchemy import text as sql_text  # type: ignore

            result = conn.execute(sql_text(sql))  # type: ignore
            return result.fetchall()


class NL2SQLTool:
    """自然语言转 SQL 并执行。"""

    def __init__(
        self,
        postgres_url: str,
        allowed_tables: Optional[List[str]] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "qwen3-max-preview",
    ) -> None:
        self.postgres_url = postgres_url
        self.allowed_tables = allowed_tables or []
        self.db = DatabaseClient(postgres_url) if postgres_url else None
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.table_schema = {k: v for k, v in TABLE_SCHEMA.items() if not self.allowed_tables or k in self.allowed_tables}

    def query(self, question: str, tables: Optional[List[str]] = None) -> NL2SQLResult:
        """使用 LlamaIndex NL2SQL 生成查询并执行。"""
        try:
            from llama_index.core import SQLDatabase  # type: ignore
            from llama_index.core.query_engine import NLSQLTableQueryEngine  # type: ignore
        except Exception as exc:
            raise RuntimeError("缺少 llama-index 依赖，无法执行 NL2SQL。") from exc

        if not self.postgres_url:
            raise RuntimeError("未配置 POSTGRES_URL，无法执行 NL2SQL。")
        if not self.api_key:
            raise RuntimeError("未配置 DASHSCOPE_API_KEY，无法执行 NL2SQL。")

        db = SQLDatabase.from_uri(self.postgres_url, include_tables=tables or self.allowed_tables)
        llm = DashScopeLlamaLLM(
            api_key=self.api_key,
            base_url=self.base_url or "",
            model=self.model,
        ).llm
        embed_model = DashScopeLlamaEmbedding(
            api_key=self.api_key,
            base_url=self.base_url or "",
            model="text-embedding-v3",
        ).embedding
        engine = NLSQLTableQueryEngine(
            sql_database=db,
            llm=llm,
            tables=tables or self.allowed_tables,
            context_query_kwargs=self._build_table_context(),
            embed_model=embed_model,
            verbose=False,
        )
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
            context[table] = f"字段: {', '.join(columns)}"
        return context
