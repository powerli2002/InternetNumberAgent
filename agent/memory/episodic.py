from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

from agent.models import MemoryItem
from .base import BaseMemory


class EpisodicMemory(BaseMemory):
    """情景记忆：优先使用 PostgreSQL 持久化，缺省回退到 SQLite。"""

    def __init__(
        self,
        sqlite_path: Optional[Path] = None,
        capacity: int = 1000,
        postgres_url: Optional[str] = None,
        table_name: str = "agent_episodic_memory",
    ) -> None:
        self.sqlite_path = sqlite_path
        self.capacity = capacity
        self.postgres_url = postgres_url
        self.table_name = table_name
        self._engine = None
        self._text = None
        self._use_postgres = bool(postgres_url)
        if not self._use_postgres and not self.sqlite_path:
            raise RuntimeError("未提供 postgres_url 或 sqlite_path，无法初始化情景记忆。")
        if not self._is_safe_table_name(self.table_name):
            raise ValueError("table_name 只能包含字母、数字和下划线。")
        self._init_db()

    def _init_db(self) -> None:
        if self._use_postgres:
            self._init_postgres()
        else:
            self._init_sqlite()

    def _init_sqlite(self) -> None:
        if not self.sqlite_path:
            raise RuntimeError("缺少 SQLite 路径，无法初始化情景记忆。")
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS episodic_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata TEXT
                )
                """
            )

    def _init_postgres(self) -> None:
        engine = self._get_engine()
        with engine.begin() as conn:
            conn.execute(
                self._text(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        id BIGSERIAL PRIMARY KEY,
                        content TEXT NOT NULL,
                        memory_type TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
                    );
                    """
                )
            )

    def _get_engine(self):
        if self._engine:
            return self._engine
        if not self.postgres_url:
            raise RuntimeError("缺少 POSTGRES_URL，无法初始化情景记忆。")
        try:
            from sqlalchemy import create_engine, text  # type: ignore
        except Exception as exc:
            raise RuntimeError("未安装 SQLAlchemy，无法连接 PostgreSQL。") from exc
        self._engine = create_engine(self.postgres_url)
        self._text = text
        return self._engine

    def add(self, item: MemoryItem) -> None:
        if self._use_postgres:
            self._add_postgres(item)
        else:
            self._add_sqlite(item)

    def _add_sqlite(self, item: MemoryItem) -> None:
        if not self.sqlite_path:
            raise RuntimeError("缺少 SQLite 路径，无法写入情景记忆。")
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                "INSERT INTO episodic_memory (content, memory_type, created_at, metadata) VALUES (?, ?, ?, ?)",
                (
                    item.content,
                    item.memory_type,
                    item.created_at.isoformat(),
                    json.dumps(item.metadata, ensure_ascii=False),
                ),
            )
            conn.execute(
                """
                DELETE FROM episodic_memory
                WHERE id NOT IN (
                    SELECT id FROM episodic_memory ORDER BY id DESC LIMIT ?
                )
                """,
                (self.capacity,),
            )

    def _add_postgres(self, item: MemoryItem) -> None:
        engine = self._get_engine()
        created_at = self._normalize_created_at(item.created_at)
        with engine.begin() as conn:
            conn.execute(
                self._text(
                    f"""
                    INSERT INTO {self.table_name} (content, memory_type, created_at, metadata)
                    VALUES (:content, :memory_type, :created_at, CAST(:metadata AS jsonb))
                    """
                ),
                {
                    "content": item.content,
                    "memory_type": item.memory_type,
                    "created_at": created_at,
                    "metadata": json.dumps(item.metadata, ensure_ascii=False),
                },
            )
            conn.execute(
                self._text(
                    f"""
                    DELETE FROM {self.table_name}
                    WHERE id NOT IN (
                        SELECT id FROM {self.table_name} ORDER BY id DESC LIMIT :limit
                    )
                    """
                ),
                {"limit": self.capacity},
            )

    def search(self, query: str, top_k: int = 5) -> List[MemoryItem]:
        """关键词 + 时间衰减综合评分。"""
        rows = self._fetch_rows()
        now = datetime.now(timezone.utc)
        results: List[MemoryItem] = []
        for content, memory_type, created_at, metadata in rows:
            score = self._keyword_score(query, content)
            if score <= 0:
                continue
            created = self._normalize_created_at(created_at)
            # 时间衰减：越新分数越高
            age_hours = max((now - created).total_seconds() / 3600, 1.0)
            decay = 1.0 / (1.0 + age_hours / 24.0)
            item = MemoryItem(
                content=content,
                memory_type=memory_type,
                created_at=created,
                metadata=self._normalize_metadata(metadata),
                score=score * decay,
            )
            results.append(item)
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    def _fetch_rows(self) -> List[Tuple[Any, ...]]:
        if self._use_postgres:
            return self._fetch_postgres_rows()
        return self._fetch_sqlite_rows()

    def _fetch_sqlite_rows(self) -> List[Tuple[Any, ...]]:
        if not self.sqlite_path:
            raise RuntimeError("缺少 SQLite 路径，无法检索情景记忆。")
        with sqlite3.connect(self.sqlite_path) as conn:
            return conn.execute(
                "SELECT content, memory_type, created_at, metadata FROM episodic_memory ORDER BY id DESC LIMIT ?",
                (self.capacity,),
            ).fetchall()

    def _fetch_postgres_rows(self) -> List[Tuple[Any, ...]]:
        engine = self._get_engine()
        with engine.begin() as conn:
            return conn.execute(
                self._text(
                    f"""
                    SELECT content, memory_type, created_at, metadata
                    FROM {self.table_name}
                    ORDER BY id DESC
                    LIMIT :limit
                    """
                ),
                {"limit": self.capacity},
            ).fetchall()

    @staticmethod
    def _normalize_metadata(metadata: Any) -> dict:
        if metadata is None:
            return {}
        if isinstance(metadata, dict):
            return metadata
        if isinstance(metadata, str):
            try:
                return json.loads(metadata)
            except json.JSONDecodeError:
                return {}
        try:
            return json.loads(metadata)
        except Exception:
            return {}

    @staticmethod
    def _normalize_created_at(value: Any) -> datetime:
        if isinstance(value, datetime):
            created = value
        else:
            created = datetime.fromisoformat(str(value))
        if created.tzinfo is None:
            return created.replace(tzinfo=timezone.utc)
        return created.astimezone(timezone.utc)

    @staticmethod
    def _keyword_score(query: str, text: str) -> float:
        tokens = [t for t in query.lower().split() if t]
        if not tokens:
            return 0.0
        text_lower = text.lower()
        hit = sum(1 for t in tokens if t in text_lower)
        return hit / max(len(tokens), 1)

    @staticmethod
    def _is_safe_table_name(name: str) -> bool:
        if not name:
            return False
        for ch in name:
            if not (ch.isalnum() or ch == "_"):
                return False
        return True
