from __future__ import annotations

from agent.tools.nl2sql_tool import NL2SQLTool


def _build_tool_for_unit() -> NL2SQLTool:
    """绕过重型初始化，仅测试纯函数路径。"""
    return NL2SQLTool.__new__(NL2SQLTool)


def test_normalize_query_mode_enum() -> None:
    """query_mode 仅允许四个枚举值。"""
    tool = _build_tool_for_unit()
    assert tool._normalize_query_mode("count") == "COUNT"
    assert tool._normalize_query_mode("GROUP_BY") == "GROUP_BY"
    assert tool._normalize_query_mode("exists") == "EXISTS"
    assert tool._normalize_query_mode("other") == "OTHER"
    assert tool._normalize_query_mode("aggregate_required") == "OTHER"


def test_compose_query_mode_guided_question_contains_directive() -> None:
    """问题文本应附带规划器提供的 QUERY_MODE 指令。"""
    tool = _build_tool_for_unit()
    guided = tool._compose_query_mode_guided_question(
        question="请对 AS9808 和 AS56046 做归属一致性审计",
        query_mode="COUNT",
    )
    assert "[QUERY_MODE=COUNT]" in guided


def test_repair_array_metric_sql_for_count_uses_sum_cardinality() -> None:
    """数组指标统计被误写成 COUNT(*) 时，应修正为数组长度求和。"""
    repaired = NL2SQLTool._repair_array_metric_sql(
        question="统计中国的 AS 的 IPv4 宣告数量",
        query_mode="COUNT",
        sql="SELECT COUNT(*) FROM as_entity WHERE as_country = 'CN' AND cardinality(v4prefixes) > 0 LIMIT 200",
        table_names=["as_entity"],
    )

    assert repaired is not None
    assert "SUM(cardinality(v4prefixes))" in repaired
    assert "as_country = 'CN'" in repaired
    assert "v4prefixes IS NOT NULL" in repaired


def test_repair_array_metric_sql_skips_when_select_already_uses_array_metric() -> None:
    """若 SELECT 子句已经按数组指标聚合，不应再次改写。"""
    repaired = NL2SQLTool._repair_array_metric_sql(
        question="统计中国的 AS 的 IPv4 宣告数量",
        query_mode="COUNT",
        sql="SELECT COALESCE(SUM(cardinality(v4prefixes)), 0) AS ipv4_count FROM as_entity WHERE as_country = 'CN' AND v4prefixes IS NOT NULL",
        table_names=["as_entity"],
    )

    assert repaired is None
