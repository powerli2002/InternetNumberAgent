"""
RAG 工具模块 - 检索增强生成

核心功能：
1. 文档向量索引构建和维护
2. 基于相似度的文档检索
3. 支持阿里云百炼嵌入模型
4. Milvus 向量数据库集成
5. 文档分块和元数据管理

工作流程：
1. 文档预处理：将文档切分为适当大小的块
2. 向量嵌入：使用嵌入模型生成文档向量
3. 索引构建：在 Milvus 中创建向量集合
4. 相似检索：基于查询向量找到相关文档片段
5. 结果返回：包含文档内容、来源和相似度分数

检索策略：
- 余弦相似度计算
- 支持 Top-K 返回
- 元数据过滤和排序
- 自动集合创建和管理
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Dict, List, Set


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
        self._batch_size = 10
        self._dim = 0

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        vectors: List[List[float]] = []
        # 百炼 Embedding 接口限制批大小，按批切分避免 400 错误
        for i in range(0, len(texts), self._batch_size):
            payload = texts[i : i + self._batch_size]
            response = self.client.embeddings.create(model=self.model, input=payload)
            vectors.extend([item.embedding for item in response.data])
        if vectors:
            self._dim = len(vectors[0])
        return vectors

    def dimension(self) -> int:
        if self._dim > 0:
            return self._dim
        sample = self.embed(["dimension probe"])
        dim = len(sample[0]) if sample else 0
        if not dim:
            raise RuntimeError("无法探测 Embedding 维度。")
        self._dim = dim
        return self._dim


class RAGTool:
    """
    检索增强生成工具

    基于 Milvus 向量数据库的文档检索工具，支持文档索引构建和相似度搜索。
    主要用于从项目文档、知识库中检索相关信息片段，为问答提供上下文支持。

    核心特性：
    - 自动集合管理：创建和维护向量集合
    - 批量索引构建：支持大量文档的高效索引
    - 相似度检索：基于余弦相似度的 Top-K 搜索
    - 元数据关联：保留文档来源和上下文信息
    - 嵌入模型集成：支持多种嵌入模型切换

    使用场景：
    - 项目文档问答
    - 知识库检索
    - 上下文增强
    - 解释性问题回答
    """

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
        self.dim = 0
        self._collection = None

    def _connect(self):
        try:
            from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility  # type: ignore
        except Exception as exc:
            raise RuntimeError("未安装 pymilvus，无法连接 Milvus。") from exc

        # 建立与 Milvus 的连接，并确保 Collection 已加载
        connections.connect(host=self.host, port=str(self.port))

        if utility.has_collection(self.collection_name):
            collection = Collection(self.collection_name)
            collection.load()
            return collection
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
        collection = Collection(self.collection_name, schema=schema)
        collection.create_index("embedding", {"index_type": "IVF_FLAT", "metric_type": "COSINE", "params": {"nlist": 128}})
        collection.load()
        return collection

    def index_documents(self, chunks: List[DocumentChunk]) -> Dict[str, int]:
        """
        写入文档切片到 Milvus，并在写入前做增量去重。

        去重策略：
        1) 批内去重：同一批次中相同 source+text 的切片只保留一份；
        2) 存量去重：查询同 source 的历史切片，按 source+text 哈希过滤已存在项。
        """
        if not chunks:
            return {"input": 0, "batch_unique": 0, "existing": 0, "inserted": 0, "skipped": 0}
        self._collection = self._connect()

        input_count = len(chunks)
        unique_chunks = self._deduplicate_batch(chunks)
        existing_hashes = self._load_existing_hashes_by_sources([c.source for c in unique_chunks])
        new_chunks = [c for c in unique_chunks if self._chunk_hash(c) not in existing_hashes]

        if not new_chunks:
            return {
                "input": input_count,
                "batch_unique": len(unique_chunks),
                "existing": len(existing_hashes),
                "inserted": 0,
                "skipped": input_count,
            }

        # 仅对新增切片做向量化并写入 Milvus
        texts = [c.text for c in new_chunks]
        embeddings = self.embedding.embed(texts)
        sources = [c.source for c in new_chunks]
        self._collection.insert([embeddings, texts, sources])
        self._collection.flush()
        inserted = len(new_chunks)
        return {
            "input": input_count,
            "batch_unique": len(unique_chunks),
            "existing": len(existing_hashes),
            "inserted": inserted,
            "skipped": input_count - inserted,
        }

    def search(self, query: str, top_k: int = 5) -> List[DocumentChunk]:
        self._collection = self._connect()
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

    @staticmethod
    def _chunk_hash(chunk: DocumentChunk) -> str:
        # 使用 source + text 生成稳定哈希，作为去重键
        payload = f"{chunk.source}\n{chunk.text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _deduplicate_batch(self, chunks: List[DocumentChunk]) -> List[DocumentChunk]:
        # 批内去重，避免同一批次重复插入
        seen: Set[str] = set()
        unique: List[DocumentChunk] = []
        for chunk in chunks:
            key = self._chunk_hash(chunk)
            if key in seen:
                continue
            seen.add(key)
            unique.append(chunk)
        return unique

    def _load_existing_hashes_by_sources(self, sources: List[str]) -> Set[str]:
        # 仅按本批次涉及 source 拉取历史切片，控制查询范围
        if not sources:
            return set()
        assert self._collection is not None
        unique_sources = sorted({s for s in sources if s})
        existing_hashes: Set[str] = set()
        for source in unique_sources:
            existing_hashes.update(self._load_hashes_for_source(source))
        return existing_hashes

    def _load_hashes_for_source(self, source: str) -> Set[str]:
        """
        分页查询某个 source 的历史切片并计算哈希。

        说明：
        - 使用 offset 分页，避免一次性拉取过大结果；
        - 若 Milvus 版本不支持 offset 参数，则退化为单次查询。
        """
        assert self._collection is not None
        escaped_source = source.replace("\\", "\\\\").replace('"', '\\"')
        expr = f'source == "{escaped_source}"'
        hashes: Set[str] = set()
        page_size = 1024
        offset = 0

        while True:
            try:
                rows: List[Dict[str, Any]] = self._collection.query(
                    expr=expr,
                    output_fields=["text", "source"],
                    limit=page_size,
                    offset=offset,
                )
            except TypeError:
                # 兼容旧版 pymilvus（无 offset 参数）
                rows = self._collection.query(
                    expr=expr,
                    output_fields=["text", "source"],
                    limit=16384,
                )
                for row in rows:
                    text = str(row.get("text") or "")
                    src = str(row.get("source") or source)
                    hashes.add(hashlib.sha256(f"{src}\n{text}".encode("utf-8")).hexdigest())
                return hashes

            if not rows:
                break

            for row in rows:
                text = str(row.get("text") or "")
                src = str(row.get("source") or source)
                hashes.add(hashlib.sha256(f"{src}\n{text}".encode("utf-8")).hexdigest())

            if len(rows) < page_size:
                break
            offset += len(rows)

        return hashes
