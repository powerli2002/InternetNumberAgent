from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from agent.core.models import TodoItem


class TodoTool:
    """TodoWrite 工具：创建与更新待办事项列表。"""

    def __init__(self, storage_path: Optional[Path] = None, max_items: int = 10) -> None:
        self.storage_path = storage_path
        self.max_items = max_items
        self._items: List[TodoItem] = []
        if self.storage_path and self.storage_path.exists():
            self._load()

    def _load(self) -> None:
        data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        self._items = [
            TodoItem(
                id=item["id"],
                title=item["title"],
                intent=item.get("intent", ""),
                status=item.get("status", "pending"),
                created_at=datetime.fromisoformat(item["created_at"]),
                updated_at=datetime.fromisoformat(item["updated_at"]),
            )
            for item in data
        ]

    def _save(self) -> None:
        if not self.storage_path:
            return
        payload = [
            {
                "id": item.id,
                "title": item.title,
                "intent": item.intent,
                "status": item.status,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
            }
            for item in self._items
        ]
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_items(self) -> List[TodoItem]:
        return list(self._items)

    def add_items(self, items: List[TodoItem]) -> None:
        """新增待办，保持列表长度限制。"""
        self._items.extend(items)
        self._items = self._items[: self.max_items]
        self._save()

    def update_status(self, item_id: str, status: str) -> bool:
        """更新状态，并确保只有一个 in_progress。"""
        updated = False
        if status == "in_progress":
            for item in self._items:
                if item.status == "in_progress":
                    item.status = "pending"
                    item.updated_at = datetime.utcnow()
        for item in self._items:
            if item.id == item_id:
                item.status = status
                item.updated_at = datetime.utcnow()
                updated = True
        if updated:
            self._save()
        return updated

    def to_dict(self) -> List[Dict]:
        return [
            {
                "id": item.id,
                "title": item.title,
                "intent": item.intent,
                "status": item.status,
            }
            for item in self._items
        ]
