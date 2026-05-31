"""Neo4j 只读查询工具，支持 Cypher 安全守卫。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class CypherGuard:
    """Cypher 安全守卫：只允许只读查询并强制 LIMIT。"""

    _BLOCKED_KEYWORDS = {
        "create",
        "merge",
        "delete",
        "detach",
        "set",
        "drop",
        "call",
        "load",
        "csv",
        "apoc",
        "remove",
        "foreach",
        "periodic",
        "profile",
        "explain",
    }

    def __init__(self, max_rows: int = 200, max_cypher_length: int = 4000) -> None:
        self.max_rows = max(1, int(max_rows))
        self.max_cypher_length = max(256, int(max_cypher_length))

    def sanitize(self, cypher: str) -> Dict[str, Any]:
        """校验并补齐 Cypher，返回规范化结果。"""
        if not cypher:
            raise ValueError("Cypher 为空")
        cleaned = cypher.strip().rstrip(";")
        if len(cleaned) > self.max_cypher_length:
            raise ValueError("Cypher 超出长度限制")
        lowered = cleaned.lower()
        # 只允许 MATCH / OPTIONAL MATCH / WITH 开头
        if not re.match(r"^\s*(match|optional\s+match|with)\b", lowered):
            raise ValueError("仅允许 MATCH/OPTIONAL MATCH/WITH 开头的只读查询")
        for keyword in self._BLOCKED_KEYWORDS:
            if re.search(rf"\b{re.escape(keyword)}\b", lowered):
                raise ValueError(f"Cypher 包含禁止关键字: {keyword}")
        cleaned = self._repair_return_where_order(cleaned)
        limit_info = self._normalize_limit(cleaned)
        return limit_info

    def _repair_return_where_order(self, cypher: str) -> str:
        lines = [line.rstrip() for line in cypher.splitlines() if line.strip()]
        if not lines:
            return cypher

        def _starts_with(line: str, keyword: str) -> bool:
            return line.lstrip().lower().startswith(keyword)

        return_indexes = [
            idx for idx, line in enumerate(lines) if _starts_with(line, "return ")
        ]
        if not return_indexes:
            return cypher

        first_return_idx = return_indexes[0]
        where_idx = next(
            (
                idx
                for idx, line in enumerate(
                    lines[first_return_idx + 1 :], start=first_return_idx + 1
                )
                if _starts_with(line, "where ")
            ),
            None,
        )
        if where_idx is None:
            return cypher

        projection = lines[first_return_idx].lstrip()[len("RETURN ") :].strip()
        if not projection:
            return cypher

        later_return_idx = next(
            (
                idx
                for idx, line in enumerate(lines[where_idx + 1 :], start=where_idx + 1)
                if _starts_with(line, "return ")
            ),
            None,
        )

        lines[first_return_idx] = f"WITH {projection}"
        if later_return_idx is None:
            insert_at = next(
                (
                    idx
                    for idx, line in enumerate(
                        lines[where_idx + 1 :], start=where_idx + 1
                    )
                    if _starts_with(line, "limit ")
                ),
                len(lines),
            )
            lines.insert(insert_at, f"RETURN {projection}")
        return "\n".join(lines)

    def _normalize_limit(self, cypher: str) -> Dict[str, Any]:
        match = re.search(r"\blimit\s+(\d+)", cypher, re.IGNORECASE)
        limit_applied = False
        limit_value = None
        limit_clamped = False
        cleaned = cypher
        if match:
            limit_value = int(match.group(1))
            if limit_value > self.max_rows:
                limit_clamped = True
                limit_value = self.max_rows
                cleaned = re.sub(
                    r"\blimit\s+\d+",
                    f"LIMIT {limit_value}",
                    cypher,
                    flags=re.IGNORECASE,
                )
        else:
            limit_applied = True
            limit_value = self.max_rows
            cleaned = f"{cypher} LIMIT {limit_value}"
        return {
            "cypher": cleaned,
            "limit_applied": limit_applied,
            "limit_value": limit_value,
            "limit_clamped": limit_clamped,
        }


class Neo4jQueryTool:
    """Neo4j 只读查询工具。"""

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        max_rows: int = 200,
        max_cypher_length: int = 4000,
    ) -> None:
        self.uri = uri
        self.user = user
        self.password = password
        self.max_rows = max_rows
        self.max_cypher_length = max_cypher_length
        try:
            from neo4j import GraphDatabase  # type: ignore
        except Exception as exc:
            raise RuntimeError("未安装 neo4j 驱动，无法执行图谱查询。") from exc
        self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))

    def query(self, cypher: str, max_rows: Optional[int] = None) -> Dict[str, Any]:
        guard = CypherGuard(
            max_rows=max_rows or self.max_rows, max_cypher_length=self.max_cypher_length
        )
        info = guard.sanitize(cypher)
        safe_cypher = info["cypher"]
        rows: List[Dict[str, Any]] = []
        truncated = False
        with self._driver.session() as session:
            result = session.run(safe_cypher)
            for idx, record in enumerate(result):
                if idx >= guard.max_rows:
                    truncated = True
                    break
                rows.append(record.data())
        columns = list(rows[0].keys()) if rows else []
        return {
            "cypher": safe_cypher,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "limit_applied": info.get("limit_applied"),
            "limit_value": info.get("limit_value"),
            "limit_clamped": info.get("limit_clamped"),
        }
