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
