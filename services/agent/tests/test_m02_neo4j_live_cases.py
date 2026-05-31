from __future__ import annotations

import pytest


NEO4J_CASES = [
    {
        "case_id": "neo4j_llamaindex_as4134_v4_upstream_count",
        "question": "AS4134 的 IPv4 上游 AS 数量是多少？",
    },
    {
        "case_id": "neo4j_llamaindex_as4837_org_name",
        "question": "AS4837 归属的组织名称是什么？",
    },
]


@pytest.fixture(scope="module")
def _require_graph_llamaindex_tool(mcp_client):
    """依赖缺失时跳过图查询 live 用例。"""
    health = mcp_client.call_tool("health")
    capabilities = health.get("capabilities") if isinstance(health, dict) else {}
    enabled = bool(capabilities.get("neo4j_llamaindex_enabled")) if isinstance(capabilities, dict) else False
    if not enabled:
        issues = health.get("issues") if isinstance(health, dict) else {}
        reason = issues.get("neo4j_llamaindex") if isinstance(issues, dict) else "unknown"
        pytest.skip(f"neo4j_llamaindex_query 不可用，跳过图查询 live 测试：{reason}")
    return True


@pytest.mark.live
@pytest.mark.parametrize("case", NEO4J_CASES, ids=[c["case_id"] for c in NEO4J_CASES])
def test_neo4j_llamaindex_query_returns_stable_shape(case, mcp_client, _require_graph_llamaindex_tool) -> None:
    """图查询用例：仅验证 MCP 返回结构稳定。"""
    payload = mcp_client.call_tool(
        "neo4j_llamaindex_query",
        {
            "question": case["question"],
            "trace_id": f"test-{case['case_id']}",
            "max_rows": 50,
        },
    )

    assert isinstance(payload, dict)
    assert isinstance(payload.get("question"), str) and payload["question"].strip()
    assert isinstance(payload.get("schema"), str)
    assert isinstance(payload.get("cypher"), str) and payload["cypher"].strip()
    assert isinstance(payload.get("rows"), list)
    assert isinstance(payload.get("row_count"), int)
    assert payload.get("row_count") == len(payload.get("rows"))
