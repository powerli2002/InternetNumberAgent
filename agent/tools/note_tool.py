from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional


class NoteTool:
    """结构化笔记工具，负责创建、读取、更新与检索。"""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.index_path = self.workspace / "notes_index.json"
        if not self.index_path.exists():
            self._write_index({})

    def _read_index(self) -> Dict[str, Dict]:
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_index(self, data: Dict[str, Dict]) -> None:
        self.index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def create(self, note_id: str, title: str, content: str, tags: Optional[List[str]] = None) -> Path:
        note_path = self.workspace / f"{note_id}.md"
        payload = f"# {title}\n\n{content.strip()}\n"
        note_path.write_text(payload, encoding="utf-8")

        index = self._read_index()
        index[note_id] = {"title": title, "tags": tags or [], "path": str(note_path)}
        self._write_index(index)
        return note_path

    def read(self, note_id: str) -> Optional[str]:
        index = self._read_index()
        meta = index.get(note_id)
        if not meta:
            return None
        path = Path(meta["path"])
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def update(self, note_id: str, content: str) -> Optional[Path]:
        index = self._read_index()
        meta = index.get(note_id)
        if not meta:
            return None
        path = Path(meta["path"])
        if not path.exists():
            return None
        path.write_text(content, encoding="utf-8")
        return path

    def list_notes(self) -> Dict[str, Dict]:
        return self._read_index()

    def search(self, keyword: str, limit: int = 5) -> List[str]:
        """简单全文检索：匹配标题或正文。"""
        results: List[str] = []
        index = self._read_index()
        keyword_lower = keyword.lower()
        for note_id, meta in index.items():
            title = meta.get("title", "")
            path = Path(meta.get("path", ""))
            if keyword_lower in title.lower():
                results.append(f"{note_id}: {title}")
            elif path.exists():
                content = path.read_text(encoding="utf-8")
                if keyword_lower in content.lower():
                    results.append(f"{note_id}: {title}")
            if len(results) >= limit:
                break
        return results
