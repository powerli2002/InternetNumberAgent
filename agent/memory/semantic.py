from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from agent.models import MemoryItem
from .base import BaseMemory


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
        self._init_driver()

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
        if not self._driver:
            raise RuntimeError("Neo4j 未初始化，无法写入语义记忆。")
        with self._driver.session() as session:
            session.run(
                """
                MERGE (c:Concept {name: $name})
                SET c.description = $description,
                    c.updated_at = datetime(),
                    c.metadata = $metadata
                """,
                name=item.metadata.get("concept", item.content[:50]),
                description=item.content,
                metadata=item.metadata,
            )

    def add_concept(self, record: SemanticRecord) -> None:
        if not self._driver:
            raise RuntimeError("Neo4j 未初始化，无法写入语义记忆。")
        metadata = record.metadata or {}
        with self._driver.session() as session:
            session.run(
                """
                MERGE (c:Concept {name: $name})
                SET c.description = $description,
                    c.metadata = $metadata
                """,
                name=record.concept,
                description=record.description,
                metadata=metadata,
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
        if not self._driver:
            raise RuntimeError("Neo4j 未初始化，无法检索语义记忆。")
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (c:Concept)
                WHERE toLower(c.name) CONTAINS toLower($query)
                   OR toLower(c.description) CONTAINS toLower($query)
                RETURN c.name AS name, c.description AS description, c.metadata AS metadata
                LIMIT $limit
                """,
                {"query": query, "limit": top_k},
            )
            items: List[MemoryItem] = []
            for record in result:
                items.append(
                    MemoryItem(
                        content=record["description"] or "",
                        memory_type="semantic",
                        metadata={"concept": record["name"], "metadata": record.get("metadata") or {}},
                        score=1.0,
                    )
                )
            return items
