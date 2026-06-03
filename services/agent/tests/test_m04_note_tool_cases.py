from __future__ import annotations

from pathlib import Path

import pytest

from agent.tools.note_tool import NoteTool


NOTE_CASES = [
    {
        "case_id": "note_search_as4134",
        "title": "AS4134 分析记录",
        "content": "本笔记记录 AS4134 的组织和前缀信息。",
        "query": "AS4134",
        "expected_note_id": "note_as4134",
    },
    {
        "case_id": "note_search_case_insensitive",
        "title": "RPKI 安全摘要",
        "content": "rpki 用于路由起源验证。",
        "query": "RPKI",
        "expected_note_id": "note_rpki",
    },
    {
        "case_id": "note_search_title_hit",
        "title": "Neo4j 链路问题单",
        "content": "排查 AS4837 上下游链路。",
        "query": "链路",
        "expected_note_id": "note_neo4j",
    },
]


def _build_note_tool(tmp_path: Path) -> NoteTool:
    """创建隔离的 NoteTool，避免污染仓库状态。"""
    return NoteTool(tmp_path / "notes")


@pytest.mark.parametrize("case", NOTE_CASES, ids=[c["case_id"] for c in NOTE_CASES])
def test_note_search_records(case, tmp_path: Path) -> None:
    """NoteTool 检索应命中自然语言查询对应的标准笔记。"""
    tool = _build_note_tool(tmp_path)
    tool.create("note_as4134", "AS4134 分析记录", "本笔记记录 AS4134 的组织和前缀信息。")
    tool.create("note_rpki", "RPKI 安全摘要", "rpki 用于路由起源验证。")
    tool.create("note_neo4j", "Neo4j 链路问题单", "排查 AS4837 上下游链路。")

    results = tool.search(case["query"], limit=5)
    assert any(item.startswith(f"{case['expected_note_id']}:") for item in results)


def test_note_search_respects_limit(tmp_path: Path) -> None:
    """limit 参数应控制返回条数。"""
    tool = _build_note_tool(tmp_path)
    tool.create("note_1", "同主题一", "路由测试")
    tool.create("note_2", "同主题二", "路由测试")
    tool.create("note_3", "同主题三", "路由测试")

    results = tool.search("路由", limit=2)
    assert len(results) == 2
