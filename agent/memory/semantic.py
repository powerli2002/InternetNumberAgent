from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agent.core.models import MemoryItem
from .base import BaseMemory
from fusiondata.src.utils.logging_manager import logger


@dataclass
class SemanticRecord:
    """语义记忆节点结构。"""

    concept: str
    description: str
    vector: Optional[list] = None
    metadata: dict = None


class SemanticMemory(BaseMemory):
    """语义记忆：优先使用 Neo4j，支持向量索引（若 Neo4j 版本可用）。"""

    def __init__(self, uri: str, user: str, password: str, embedding_dim: Optional[int] = None) -> None:
        self.uri = uri
        self.user = user
        self.password = password
        self.embedding_dim = embedding_dim
        self._driver = None
        self._enabled = True
        try:
            self._init_driver()
        except Exception as exc:
            # 语义记忆降级为可用但无后端，避免主流程因 Neo4j 不可用而失败
            self._enabled = False
            self._driver = None
            logger.warning("SemanticMemory 初始化失败，已降级为 no-op: %s", exc)

    def _init_driver(self) -> None:
        try:
            from neo4j import GraphDatabase  # type: ignore
        except Exception as exc:
            raise RuntimeError("未安装 neo4j 驱动，无法启用语义记忆。") from exc
        self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        with self._driver.session() as session:
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Concept) REQUIRE c.name IS UNIQUE")
            if self.embedding_dim:
                session.run(
                    """
                    CREATE VECTOR INDEX concept_embedding_index IF NOT EXISTS
                    FOR (c:Concept) ON (c.embedding)
                    OPTIONS {indexConfig: {`vector.dimensions`: $dim, `vector.similarity_function`: "cosine"}}
                    """,
                    dim=self.embedding_dim,
                )

    def add(self, item: MemoryItem) -> None:
        if not self._enabled or not self._driver:
            return
        metadata = item.metadata if isinstance(item.metadata, dict) else {}
        payload = self._build_metadata_payload(metadata)
        with self._driver.session() as session:
            session.run(
                """
                MERGE (c:Concept {name: $name})
                SET c.description = $description,
                    c.updated_at = datetime(),
                    c.metadata_json = $metadata_json,
                    c.source = $source,
                    c.category = $category,
                    c.importance = $importance,
                    c.tags = $tags
                """,
                name=metadata.get("concept", item.content[:50]),
                description=item.content,
                **payload,
            )

    def add_concept(self, record: SemanticRecord) -> None:
        if not self._enabled or not self._driver:
            return
        payload = self._build_metadata_payload(record.metadata if isinstance(record.metadata, dict) else {})
        with self._driver.session() as session:
            session.run(
                """
                MERGE (c:Concept {name: $name})
                SET c.description = $description,
                    c.updated_at = datetime(),
                    c.metadata_json = $metadata_json,
                    c.source = $source,
                    c.category = $category,
                    c.importance = $importance,
                    c.tags = $tags
                """,
                name=record.concept,
                description=record.description,
                **payload,
            )
            if record.vector is not None:
                session.run(
                    """
                    MATCH (c:Concept {name: $name})
                    SET c.embedding = $embedding
                    """,
                    name=record.concept,
                    embedding=record.vector,
                )

    def search(self, query: str, top_k: int = 5) -> List[MemoryItem]:
        if not self._enabled or not self._driver:
            return []
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (c:Concept)
                WHERE toLower(c.name) CONTAINS toLower($query)
                   OR toLower(c.description) CONTAINS toLower($query)
                RETURN c.name AS name,
                       c.description AS description,
                       coalesce(c.metadata_json, '{}') AS metadata_json,
                       coalesce(c.source, '') AS source,
                       coalesce(c.category, '') AS category,
                       c.importance AS importance,
                       coalesce(c.tags, []) AS tags
                LIMIT $limit
                """,
                {"query": query, "limit": top_k},
            )
            items: List[MemoryItem] = []
            for record in result:
                metadata = self._parse_metadata(record)
                items.append(
                    MemoryItem(
                        content=record["description"] or "",
                        memory_type="semantic",
                        metadata={"concept": record["name"], "metadata": metadata},
                        score=1.0,
                    )
                )
            return items

    @staticmethod
    def _build_metadata_payload(metadata: Dict[str, Any]) -> Dict[str, Any]:
        # Neo4j 属性不支持 map，统一落为可索引字段 + JSON 字符串
        data = metadata if isinstance(metadata, dict) else {}
        try:
            metadata_json = json.dumps(data, ensure_ascii=False)
        except Exception:
            metadata_json = "{}"
        source = str(data.get("source", "")).strip()
        category = str(data.get("category", "")).strip()
        importance_raw = data.get("importance")
        importance = None
        if importance_raw is not None:
            try:
                importance = float(importance_raw)
            except (TypeError, ValueError):
                importance = None
        tags_raw = data.get("tags")
        tags: List[str] = []
        if isinstance(tags_raw, list):
            tags = [str(tag).strip() for tag in tags_raw if str(tag).strip()]
        return {
            "metadata_json": metadata_json,
            "source": source,
            "category": category,
            "importance": importance,
            "tags": tags,
        }

    @staticmethod
    def _parse_metadata(record: Any) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {}
        raw_json = record.get("metadata_json") if hasattr(record, "get") else None
        if isinstance(raw_json, str) and raw_json.strip():
            try:
                loaded = json.loads(raw_json)
                if isinstance(loaded, dict):
                    metadata = loaded
            except Exception:
                metadata = {}
        source = record.get("source") if hasattr(record, "get") else None
        category = record.get("category") if hasattr(record, "get") else None
        importance = record.get("importance") if hasattr(record, "get") else None
        tags = record.get("tags") if hasattr(record, "get") else None
        if isinstance(source, str) and source.strip():
            metadata.setdefault("source", source.strip())
        if isinstance(category, str) and category.strip():
            metadata.setdefault("category", category.strip())
        if importance is not None:
            metadata.setdefault("importance", importance)
        if isinstance(tags, list) and tags:
            metadata.setdefault("tags", tags)
        return metadata
