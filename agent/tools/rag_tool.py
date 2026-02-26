"""
RAG 工具模块 - 检索增强生成

核心功能：
1. 文档向量索引构建和维护
2. 基于相似度的文档检索
3. 支持本地离线 bge 与 DashScope 两种嵌入
4. Milvus 向量数据库集成
5. 文档去重与多查询融合召回（MQE + RRF）
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import os
import re
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


class LocalBGEEmbedding(EmbeddingProvider):
    """本地离线 bge embedding，默认使用 BAAI/bge-m3。"""

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        device: str = "cpu",
        batch_size: int = 16,
        normalize: bool = True,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.batch_size = max(1, int(batch_size))
        self.normalize = normalize
        self._model = None
        self._dim = 0
        self._resolved_model_path: str | None = None

    def _resolve_model_path(self) -> str:
        if self._resolved_model_path:
            return self._resolved_model_path
        # 已是本地目录时直接复用，避免重复下载。
        if Path(self.model_name).exists():
            self._resolved_model_path = self.model_name
            return self._resolved_model_path
        # 兼容错误的 HF_ENDPOINT（如 "HF-Mirror" 无协议），统一规范为可用 URL。
        raw_hf_endpoint = (os.environ.get("HF_ENDPOINT") or "").strip()
        if raw_hf_endpoint:
            lower = raw_hf_endpoint.lower()
            if lower in {"hf-mirror", "hf_mirror", "hf-mirror.com"}:
                os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
            elif "://" not in raw_hf_endpoint:
                os.environ["HF_ENDPOINT"] = f"https://{raw_hf_endpoint.lstrip('/')}"
        # 对 HuggingFace 仓库名做一次本地快照下载，并忽略镜像常见异常文件。
        if "/" in self.model_name:
            try:
                from huggingface_hub import snapshot_download  # type: ignore

                self._resolved_model_path = snapshot_download(
                    repo_id=self.model_name,
                    ignore_patterns=[
                        "*.DS_Store",
                        "**/.DS_Store",
                        "*.onnx",
                        "*.onnx_data",
                        "openvino/*",
                    ],
                    resume_download=True,
                )
                return self._resolved_model_path
            except Exception:
                cached_snapshot = self._find_cached_snapshot()
                if cached_snapshot:
                    self._resolved_model_path = cached_snapshot
                    return self._resolved_model_path
                # 下载失败时回退到 HuggingFaceEmbedding 默认加载逻辑，保留原始报错信息。
                pass
        self._resolved_model_path = self.model_name
        return self._resolved_model_path

    def _find_cached_snapshot(self) -> str | None:
        """
        从本地 HuggingFace 缓存中查找模型快照目录。

        设计目的：
        - 当镜像地址异常或离线时，若本机已缓存模型，则直接复用；
        - 避免再次触发 HuggingFaceEmbedding 的在线下载逻辑。
        """
        repo = self.model_name.strip().replace("/", "--")
        if not repo:
            return None
        hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
        snapshots_dir = hf_home / "hub" / f"models--{repo}" / "snapshots"
        if not snapshots_dir.exists():
            return None
        candidates: List[Path] = []
        for item in snapshots_dir.iterdir():
            if not item.is_dir():
                continue
            if (item / "modules.json").exists() or (item / "config.json").exists():
                candidates.append(item)
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return str(candidates[0])

    def _ensure_model(self):
        if self._model is not None:
            return
        try:
            from llama_index.embeddings.huggingface import HuggingFaceEmbedding  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "缺少 llama-index-embeddings-huggingface，无法使用本地 bge embedding。"
                "请先安装相关依赖。"
            ) from exc

        model_ref = self._resolve_model_path()
        # 统一使用 HuggingFaceEmbedding，减少不同模块间 embedding 行为差异。
        kwargs: Dict[str, Any] = {
            "model_name": model_ref,
            "device": self.device,
            "embed_batch_size": self.batch_size,
            "normalize": self.normalize,
            "show_progress_bar": False,
        }
        if str(self.device).lower().startswith("cuda"):
            # 限制最大长度，避免超长文本在 GPU 场景下触发显存放大。
            kwargs["max_length"] = 512
        self._model = HuggingFaceEmbedding(**kwargs)

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        self._ensure_model()
        assert self._model is not None
        vectors = self._model.get_text_embedding_batch(texts)
        outputs: List[List[float]] = []
        for vector in vectors:
            outputs.append([float(x) for x in vector])
        if outputs:
            self._dim = len(outputs[0])
        return outputs

    def dimension(self) -> int:
        self._ensure_model()
        if self._dim > 0:
            return self._dim
        sample = self.embed(["dimension probe"])
        dim = len(sample[0]) if sample else 0
        if not dim:
            raise RuntimeError("无法探测本地 embedding 维度。")
        self._dim = dim
        return self._dim


def build_rag_embedding(config: Any) -> EmbeddingProvider:
    """按配置构建 RAG embedding，默认本地离线 bge。"""
    backend = str(getattr(config, "rag_embedding_backend", "local_bge")).strip().lower()
    if backend in {"local_bge", "bge", "local"}:
        return LocalBGEEmbedding(
            model_name=str(getattr(config, "rag_embedding_model", "BAAI/bge-m3")),
            device=str(getattr(config, "rag_embedding_device", "cpu")),
            batch_size=int(getattr(config, "rag_embedding_batch_size", 16)),
            normalize=bool(getattr(config, "rag_embedding_normalize", True)),
        )
    if backend in {"dashscope", "online"}:
        api_key = str(getattr(config, "dashscope_api_key", "") or "")
        base_url = str(getattr(config, "dashscope_base_url", ""))
        model = str(getattr(config, "dashscope_embedding_model", "text-embedding-v3"))
        return DashScopeEmbedding(api_key=api_key, base_url=base_url, model=model)
    raise RuntimeError(f"不支持的 RAG_EMBEDDING_BACKEND: {backend}")


class RAGTool:
    """
    检索增强生成工具

    基于 Milvus 向量数据库的文档检索工具，支持文档索引构建和相似度搜索。
    默认启用 MQE（多查询扩展）+ RRF（倒数排名融合）召回，提升复杂问法下的召回稳定性。
    """

    def __init__(
        self,
        host: str,
        port: int,
        collection_name: str,
        embedding: EmbeddingProvider,
        enable_mqe: bool = True,
        mqe_max_queries: int = 4,
        candidate_multiplier: int = 4,
        rrf_k: int = 60,
    ) -> None:
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self.embedding = embedding
        self.dim = 0
        self._collection = None
        self.enable_mqe = enable_mqe
        self.mqe_max_queries = max(1, int(mqe_max_queries))
        self.candidate_multiplier = max(1, int(candidate_multiplier))
        self.rrf_k = max(1, int(rrf_k))

    def _connect(self):
        try:
            from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility  # type: ignore
        except Exception as exc:
            raise RuntimeError("未安装 pymilvus，无法连接 Milvus。") from exc

        # 建立与 Milvus 的连接，并确保 Collection 已加载
        connections.connect(host=self.host, port=str(self.port))

        if utility.has_collection(self.collection_name):
            collection = Collection(self.collection_name)
            existing_dim = self._collection_dim(collection)
            model_dim = self.embedding.dimension()
            if existing_dim and model_dim and existing_dim != model_dim:
                raise RuntimeError(
                    f"Milvus 集合 {self.collection_name} 维度为 {existing_dim}，"
                    f"当前 embedding 维度为 {model_dim}，请使用 --reset 重新构建索引。"
                )
            self.dim = existing_dim or model_dim
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
        collection.create_index(
            "embedding",
            {
                "index_type": "HNSW",
                "metric_type": "COSINE",
                "params": {"M": 32, "efConstruction": 200},
            },
        )
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
        cleaned_query = query.strip()
        if not cleaned_query:
            return []
        self._collection = self._connect()
        top_k = max(1, int(top_k))

        if not self.enable_mqe:
            return self._single_search(cleaned_query, top_k)
        return self._mqe_rrf_search(cleaned_query, top_k)

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

    def _collection_dim(self, collection) -> int:
        # 兼容不同 pymilvus 版本读取向量维度
        try:
            for field in collection.schema.fields:
                if getattr(field, "name", "") != "embedding":
                    continue
                params = getattr(field, "params", {}) or {}
                value = params.get("dim")
                if value is not None:
                    return int(value)
        except Exception:
            return 0
        return 0

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

    def _single_search(self, query: str, top_k: int) -> List[DocumentChunk]:
        rows = self._search_rows(query, limit=top_k)
        chunks: List[DocumentChunk] = []
        for row in rows:
            chunks.append(
                DocumentChunk(
                    text=row["text"],
                    source=row["source"],
                    metadata={
                        "score": row["score"],
                        "rank": row["rank"],
                        "query": query,
                    },
                )
            )
        return chunks

    def _mqe_rrf_search(self, query: str, top_k: int) -> List[DocumentChunk]:
        expanded_queries = self._expand_queries(query)
        per_query_limit = max(top_k, min(100, top_k * self.candidate_multiplier))

        fused: Dict[str, Dict[str, Any]] = {}
        for variant in expanded_queries:
            rows = self._search_rows(variant, limit=per_query_limit)
            for row in rows:
                key = hashlib.sha256(f"{row['source']}\n{row['text']}".encode("utf-8")).hexdigest()
                rank = int(row["rank"])
                raw_score = float(row["score"])
                # RRF 为主，向量原始分数为辅，兼顾稳定性与可解释性
                fused_score = 1.0 / (self.rrf_k + rank) + (max(raw_score, 0.0) * 0.05)

                if key not in fused:
                    fused[key] = {
                        "text": row["text"],
                        "source": row["source"],
                        "best_score": raw_score,
                        "best_rank": rank,
                        "fused_score": fused_score,
                        "matched_queries": [variant],
                    }
                    continue

                record = fused[key]
                record["fused_score"] += fused_score
                record["best_score"] = max(float(record["best_score"]), raw_score)
                record["best_rank"] = min(int(record["best_rank"]), rank)
                matched = record["matched_queries"]
                if variant not in matched:
                    matched.append(variant)

        ranked = sorted(
            fused.values(),
            key=lambda item: (float(item["fused_score"]), float(item["best_score"])),
            reverse=True,
        )

        chunks: List[DocumentChunk] = []
        for row in ranked[:top_k]:
            chunks.append(
                DocumentChunk(
                    text=str(row["text"]),
                    source=str(row["source"]),
                    metadata={
                        "score": float(row["best_score"]),
                        "rank": int(row["best_rank"]),
                        "fused_score": float(row["fused_score"]),
                        "matched_queries": list(row["matched_queries"]),
                        "strategy": "mqe_rrf",
                    },
                )
            )
        return chunks

    def _search_rows(self, query: str, limit: int) -> List[Dict[str, Any]]:
        assert self._collection is not None
        embeddings = self.embedding.embed([query])
        results = self._collection.search(
            data=embeddings,
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"ef": 128}},
            limit=max(1, int(limit)),
            output_fields=["text", "source"],
        )
        rows: List[Dict[str, Any]] = []
        for hits in results:
            for idx, hit in enumerate(hits, start=1):
                text = str(hit.entity.get("text") or "")
                source = str(hit.entity.get("source") or "")
                if not text:
                    continue
                rows.append(
                    {
                        "text": text,
                        "source": source,
                        "score": float(hit.score),
                        "rank": idx,
                    }
                )
        return rows

    def _expand_queries(self, query: str) -> List[str]:
        """MQE：基于规则做轻量扩展，避免额外依赖在线 LLM。"""
        normalized = re.sub(r"\s+", " ", query).strip()
        variants: List[str] = [normalized]

        punctuation_cleaned = re.sub(r"[，,。！？；;、:：()（）\[\]{}'\"`]+", " ", normalized)
        punctuation_cleaned = re.sub(r"\s+", " ", punctuation_cleaned).strip()
        if punctuation_cleaned and punctuation_cleaned != normalized:
            variants.append(punctuation_cleaned)

        tokens = [token for token in re.split(r"[\s,，。！？；;、]+", punctuation_cleaned or normalized) if len(token) >= 2]
        if len(tokens) > 1:
            variants.append(" ".join(tokens[:6]))
            key_terms = sorted(tokens, key=len, reverse=True)[:3]
            if key_terms:
                variants.append(" ".join(key_terms))

        # 针对互联网号码资源场景的常见术语做等价扩展
        synonyms = {
            "ASN": ["AS号", "自治系统号"],
            "AS": ["自治系统", "自治域"],
            "BGP": ["边界网关协议", "路由"],
            "前缀": ["IP前缀", "网段"],
            "RDAP": ["注册数据访问协议"],
            "WHOIS": ["注册信息"],
            "劫持": ["路由劫持", "前缀劫持"],
        }
        for term, expansions in synonyms.items():
            if term not in normalized:
                continue
            for expansion in expansions:
                variants.append(normalized.replace(term, expansion))

        deduped: List[str] = []
        seen: Set[str] = set()
        for item in variants:
            cleaned = item.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            deduped.append(cleaned)
            if len(deduped) >= self.mqe_max_queries:
                break
        return deduped
