from __future__ import annotations

from typing import Any, Dict

import pytest


NL2SQL_CASES = [
    {
        "case_id": "nl2sql_as4134_ipv6_routes",
        "question": "在 ipv6_bgp_entity 表中，bgp=4134 的路由数量是多少？",
        "tables": ["ipv6_bgp_entity"],
        "expected_sql": "SELECT COUNT(*) FROM ipv6_bgp_entity WHERE bgp = 4134",
    },
    {
        "case_id": "nl2sql_as4134_ipv4_routes",
        "question": "在 ip_bgp_entity 表中，bgp=4134 的路由数量是多少？",
        "tables": ["ip_bgp_entity"],
        "expected_sql": "SELECT COUNT(*) FROM ip_bgp_entity WHERE bgp = 4134",
    },
    {
        "case_id": "nl2sql_as4837_org_name",
        "question": "AS4837 的组织名称是什么？",
        "tables": ["as_entity"],
        "expected_sql": "SELECT org_name FROM as_entity WHERE asn = 4837",
    },
]


def _extract_first_scalar(result_payload: Dict[str, Any]) -> Any:
    """从 NL2SQL 工具返回结构中提取首个标量结果。"""
    rows = result_payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise AssertionError("NL2SQL 返回缺少 rows 或 rows 为空。")
    first_row = rows[0]
    if not isinstance(first_row, list) or not first_row:
        raise AssertionError("NL2SQL 返回首行格式错误。")
    return first_row[0]


@pytest.mark.live
@pytest.mark.parametrize("case", NL2SQL_CASES, ids=[c["case_id"] for c in NL2SQL_CASES])
def test_nl2sql_natural_language_against_db_standard_answer(case, mcp_client, sql_scalar) -> None:
    """自然语言 NL2SQL 用例：结果必须与数据库直查标准答案一致。"""
    expected_value = sql_scalar(case["expected_sql"])

    payload = mcp_client.call_tool(
        "nl2sql_query",
        {
            "question": case["question"],
            "tables": case["tables"],
            "trace_id": f"test-{case['case_id']}",
        },
    )

    assert isinstance(payload, dict)
    assert isinstance(payload.get("sql"), str) and payload["sql"].strip()
    result = payload.get("result")
    assert isinstance(result, dict)

    actual_value = _extract_first_scalar(result)
    assert actual_value == expected_value
