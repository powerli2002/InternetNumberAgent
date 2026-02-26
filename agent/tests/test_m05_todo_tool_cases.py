from __future__ import annotations

from pathlib import Path

from agent.core.models import TodoItem
from agent.tools.todo_tool import TodoTool


def _build_todo_tool(tmp_path: Path, max_items: int = 10) -> TodoTool:
    """创建隔离的 TodoTool，避免影响项目中的 todo.json。"""
    return TodoTool(storage_path=tmp_path / "todo.json", max_items=max_items)


def test_todo_add_and_list_records(tmp_path: Path) -> None:
    """TodoTool 应支持批量新增并返回完整列表。"""
    tool = _build_todo_tool(tmp_path)
    items = [
        TodoItem(id="todo_nl2sql", title="核验 AS4134 IPv6 路由数量", intent="执行 NL2SQL 用例"),
        TodoItem(id="todo_rag", title="核验 RAG 检索一致性", intent="执行 RAG 用例"),
        TodoItem(id="todo_graph", title="核验 AS4837 图查询", intent="执行 Neo4j 用例"),
    ]
    tool.add_items(items)

    loaded = tool.list_items()
    assert [item.id for item in loaded] == ["todo_nl2sql", "todo_rag", "todo_graph"]


def test_todo_single_in_progress_constraint(tmp_path: Path) -> None:
    """同一时刻只允许一个任务为 in_progress。"""
    tool = _build_todo_tool(tmp_path)
    tool.add_items(
        [
            TodoItem(id="todo_1", title="任务1", intent="测试"),
            TodoItem(id="todo_2", title="任务2", intent="测试"),
        ]
    )

    assert tool.update_status("todo_1", "in_progress") is True
    assert tool.update_status("todo_2", "in_progress") is True

    statuses = {item.id: item.status for item in tool.list_items()}
    assert statuses["todo_1"] == "pending"
    assert statuses["todo_2"] == "in_progress"


def test_todo_update_status_returns_false_for_unknown_id(tmp_path: Path) -> None:
    """更新不存在任务应返回 False。"""
    tool = _build_todo_tool(tmp_path)
    tool.add_items([TodoItem(id="todo_exists", title="存在任务", intent="测试")])

    assert tool.update_status("todo_missing", "completed") is False
