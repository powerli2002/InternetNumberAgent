from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from agent.models import MemoryItem
from .base import BaseMemory


class EpisodicMemory(BaseMemory):
    """情景记忆：SQLite 持久化 + 简单时间衰减检索。"""

    def __init__(self, sqlite_path: Path, capacity: int = 1000) -> None:
        self.sqlite_path = sqlite_path
        self.capacity = capacity
        self._init_db()

    def _init_db(self) -> None:
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

    def add(self, item: MemoryItem) -> None:
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

    def search(self, query: str, top_k: int = 5) -> List[MemoryItem]:
        """关键词 + 时间衰减综合评分。"""
        with sqlite3.connect(self.sqlite_path) as conn:
            rows = conn.execute(
                "SELECT content, memory_type, created_at, metadata FROM episodic_memory ORDER BY id DESC LIMIT ?",
                (self.capacity,),
            ).fetchall()

        now = datetime.utcnow()
        results: List[MemoryItem] = []
        for content, memory_type, created_at, metadata in rows:
            score = self._keyword_score(query, content)
            if score <= 0:
                continue
            created = datetime.fromisoformat(created_at)
            # 时间衰减：越新分数越高
            age_hours = max((now - created).total_seconds() / 3600, 1.0)
            decay = 1.0 / (1.0 + age_hours / 24.0)
            item = MemoryItem(
                content=content,
                memory_type=memory_type,
                created_at=created,
                metadata=json.loads(metadata) if metadata else {},
                score=score * decay,
            )
            results.append(item)
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    @staticmethod
    def _keyword_score(query: str, text: str) -> float:
        tokens = [t for t in query.lower().split() if t]
        if not tokens:
            return 0.0
        text_lower = text.lower()
        hit = sum(1 for t in tokens if t in text_lower)
        return hit / max(len(tokens), 1)
