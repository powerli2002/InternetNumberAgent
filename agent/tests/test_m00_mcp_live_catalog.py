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
        "neo4j_llamaindex_query",
        "note_search",
        "todo_add",
        "todo_list",
    }
    missing = sorted(required - names)
    assert not missing, f"缺少 MCP 工具: {missing}"
    assert "neo4j_query" not in names, "neo4j_query 不应再对外暴露。"


@pytest.mark.live
def test_mcp_neo4j_query_is_not_exposed(mcp_client) -> None:
    """外部调用 neo4j_query 应报工具不存在。"""
    with pytest.raises(Exception):
        mcp_client.call_tool(
            "neo4j_query",
            {
                "cypher": "MATCH (n) RETURN count(n) AS value LIMIT 1",
                "trace_id": "test-neo4j-query-removed",
            },
        )


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
