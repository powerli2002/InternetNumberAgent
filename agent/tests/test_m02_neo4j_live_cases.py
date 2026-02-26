from __future__ import annotations

from typing import Any, Dict

import pytest


NEO4J_CASES = [
    {
        "case_id": "neo4j_as4134_v4_upstream_count",
        "question": "AS4134 的 IPv4 上游 AS 数量是多少？",
        "cypher": "MATCH (a:AS {asn:4134})-[:V4_UPSTREAM]->(up:AS) RETURN count(DISTINCT up) AS value LIMIT 1",
    },
    {
        "case_id": "neo4j_as4837_v4_upstream_count",
        "question": "AS4837 的 IPv4 上游 AS 数量是多少？",
        "cypher": "MATCH (a:AS {asn:4837})-[:V4_UPSTREAM]->(up:AS) RETURN count(DISTINCT up) AS value LIMIT 1",
    },
    {
        "case_id": "neo4j_as4837_org_name",
        "question": "AS4837 归属的组织名称是什么？",
        "cypher": "MATCH (a:AS {asn:4837})-[:BELONGS_TO]->(o:Org) RETURN o.org_name AS value LIMIT 1",
    },
]


def _extract_first_value(rows_payload: Any) -> Any:
    """从 Neo4j 工具结果行中提取字段 value。"""
    if not isinstance(rows_payload, list) or not rows_payload:
        raise AssertionError("neo4j_query 返回 rows 为空。")
    row = rows_payload[0]
    if not isinstance(row, dict) or "value" not in row:
        raise AssertionError("neo4j_query 首行缺少 value 字段。")
    return row["value"]


@pytest.mark.live
@pytest.mark.parametrize("case", NEO4J_CASES, ids=[c["case_id"] for c in NEO4J_CASES])
def test_neo4j_cypher_result_matches_direct_graph_standard_answer(case, mcp_client, neo4j_scalar) -> None:
    """图查询用例：MCP 工具结果必须与 Neo4j 直查标准答案一致。"""
    expected_value = neo4j_scalar(case["cypher"], field="value")

    payload = mcp_client.call_tool(
        "neo4j_query",
        {
            "cypher": case["cypher"],
            "trace_id": f"test-{case['case_id']}",
        },
    )

    assert isinstance(payload, dict)
    assert isinstance(payload.get("cypher"), str) and payload["cypher"].strip()

    actual_value = _extract_first_value(payload.get("rows"))
    assert actual_value == expected_value
