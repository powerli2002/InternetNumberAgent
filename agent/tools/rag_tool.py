from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class DocumentChunk:
    """文档切片结构。"""

    text: str
    source: str
    metadata: dict


class EmbeddingProvider:
    """嵌入模型接口。"""

    def embed(self, texts: List[str]) -> List[List[float]]:
        # 输入批量文本，返回批量向量
        raise NotImplementedError

    def dimension(self) -> int:
        # 返回向量维度（用于建表）
        raise NotImplementedError


class DashScopeEmbedding(EmbeddingProvider):
    """使用阿里云百炼兼容 OpenAI Embedding 接口生成向量。"""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        try:
            from openai import OpenAI  # type: ignore
            from langsmith.wrappers import wrap_openai  # type: ignore
        except Exception as exc:
            raise RuntimeError("未安装 openai/langsmith SDK，无法调用百炼 Embedding。") from exc
        if not api_key:
            raise RuntimeError("缺少 DASHSCOPE_API_KEY，无法调用 Embedding。")
        self.client = wrap_openai(OpenAI(api_key=api_key, base_url=base_url))
        self.model = model
        self._dim: Optional[int] = None
        self._batch_size = 10

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        vectors: List[List[float]] = []
        # 百炼 Embedding 接口限制批大小，按批切分避免 400 错误
        for i in range(0, len(texts), self._batch_size):
            payload = texts[i : i + self._batch_size]
            response = self.client.embeddings.create(model=self.model, input=payload)
            vectors.extend([item.embedding for item in response.data])
        if vectors and self._dim is None:
            self._dim = len(vectors[0])
        return vectors

    def dimension(self) -> int:
        # 首次调用时通过探测文本获取向量维度
        if self._dim is None:
            sample = self.embed(["dimension probe"])
            self._dim = len(sample[0]) if sample else 0
        return self._dim or 0


class RAGTool:
    """基于 Milvus 的向量检索工具。"""

    def __init__(
        self,
        host: str,
        port: int,
        collection_name: str,
        embedding: EmbeddingProvider,
    ) -> None:
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self.embedding = embedding
        self.dim: Optional[int] = None
        self._collection = None

    def _connect(self) -> None:
        try:
            from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility  # type: ignore
        except Exception as exc:
            raise RuntimeError("未安装 pymilvus，无法连接 Milvus。") from exc

        # 建立与 Milvus 的连接，并确保 Collection 已加载
        connections.connect(host=self.host, port=str(self.port))

        if utility.has_collection(self.collection_name):
            self._collection = Collection(self.collection_name)
            self._collection.load()
            return
        self.dim = self.embedding.dimension()
        if not self.dim:
            raise RuntimeError("Embedding 维度为空，无法创建 Milvus Collection。")

        # 若集合不存在，则创建 schema + 索引
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.dim),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=512),
        ]
        schema = CollectionSchema(fields, description="fusionprocessing docs")
        self._collection = Collection(self.collection_name, schema=schema)
        self._collection.create_index("embedding", {"index_type": "IVF_FLAT", "metric_type": "COSINE", "params": {"nlist": 128}})
        self._collection.load()

    def index_documents(self, chunks: List[DocumentChunk]) -> None:
        if not chunks:
            return
        if self._collection is None:
            self._connect()
        # 按文本批量生成向量，并写入 Milvus
        texts = [c.text for c in chunks]
        embeddings = self.embedding.embed(texts)
        sources = [c.source for c in chunks]
        self._collection.insert([embeddings, texts, sources])
        self._collection.flush()

    def search(self, query: str, top_k: int = 5) -> List[DocumentChunk]:
        if self._collection is None:
            self._connect()
        # 查询向量化后进行近邻检索
        embeddings = self.embedding.embed([query])
        results = self._collection.search(
            data=embeddings,
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"nprobe": 10}},
            limit=top_k,
            output_fields=["text", "source"],
        )
        chunks: List[DocumentChunk] = []
        for hits in results:
            for hit in hits:
                chunks.append(
                    DocumentChunk(
                        text=hit.entity.get("text"),
                        source=hit.entity.get("source"),
                        metadata={"score": hit.score},
                    )
                )
        return chunks
