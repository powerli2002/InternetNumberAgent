from __future__ import annotations

import pytest


@pytest.mark.live
def test_mcp_health_ok(mcp_client) -> None:
    """MCP 健康检查应返回 status=ok。"""
    payload = mcp_client.call_tool("health")
    assert isinstance(payload, dict)
    assert payload.get("status") == "ok"


@pytest.mark.live
def test_mcp_required_tools_present(mcp_client) -> None:
    """工具目录必须包含核心工具集合。"""
    tools = mcp_client.list_tools_sync(refresh=True)
    names = {
        str(item.get("name", "")).strip()
        for item in tools
        if isinstance(item, dict)
    }
    required = {
        "health",
        "nl2sql_query",
        "rag_search",
        "neo4j_query",
        "neo4j_llamaindex_query",
        "note_search",
        "todo_add",
        "todo_list",
    }
    missing = sorted(required - names)
    assert not missing, f"缺少 MCP 工具: {missing}"


@pytest.mark.live
def test_mcp_note_search_returns_structured_payload(mcp_client) -> None:
    """note_search 返回结构需稳定，便于后续编排使用。"""
    payload = mcp_client.call_tool(
        "note_search",
        {
            "query": "__not_exists_keyword_20260225__",
            "limit": 3,
            "trace_id": "test-note-search-shape",
        },
    )
    assert isinstance(payload, dict)
    assert "notes" in payload
    assert isinstance(payload["notes"], list)
