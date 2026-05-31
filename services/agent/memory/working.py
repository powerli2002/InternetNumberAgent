from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import List, Optional

from agent.core.models import MemoryItem
from .base import BaseMemory


class WorkingMemory(BaseMemory):
    """工作记忆：支持内存与可选 SQLite 持久化。"""

    def __init__(self, capacity: int = 200, sqlite_path: Optional[Path] = None) -> None:
        self.capacity = capacity
        self.sqlite_path = sqlite_path
        self._items: List[MemoryItem] = []
        if self.sqlite_path:
            self._init_db()

    def _init_db(self) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS working_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata TEXT
                )
                """
            )

    def add(self, item: MemoryItem) -> None:
        self._items.append(item)
        if len(self._items) > self.capacity:
            self._items = self._items[-self.capacity :]
        if self.sqlite_path:
            with sqlite3.connect(self.sqlite_path) as conn:
                conn.execute(
                    "INSERT INTO working_memory (content, memory_type, created_at, metadata) VALUES (?, ?, ?, ?)",
                    (
                        item.content,
                        item.memory_type,
                        item.created_at.isoformat(),
                        json.dumps(item.metadata, ensure_ascii=False),
                    ),
                )

    def search(self, query: str, top_k: int = 5) -> List[MemoryItem]:
        """使用关键词匹配检索，按匹配度与新近性排序。"""
        scores: List[MemoryItem] = []
        for item in self._items:
            score = self._keyword_score(query, item.content)
            if score <= 0:
                continue
            item.score = score
            scores.append(item)
        scores.sort(key=lambda x: x.score, reverse=True)
        return scores[:top_k]

    @staticmethod
    def _keyword_score(query: str, text: str) -> float:
        query_tokens = [t for t in query.lower().split() if t]
        if not query_tokens:
            return 0.0
        text_lower = text.lower()
        hit = sum(1 for t in query_tokens if t in text_lower)
        return hit / max(len(query_tokens), 1)
