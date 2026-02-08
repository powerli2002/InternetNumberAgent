"""工具层公共导出（惰性加载，避免导入时循环依赖）。"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Dict, Tuple


_LAZY_EXPORTS: Dict[str, Tuple[str, str]] = {
    "NL2SQLTool": ("agent.tools.nl2sql_tool", "NL2SQLTool"),
    "RAGTool": ("agent.tools.rag_tool", "RAGTool"),
    "DashScopeEmbedding": ("agent.tools.rag_tool", "DashScopeEmbedding"),
    "NoteTool": ("agent.tools.note_tool", "NoteTool"),
    "TodoTool": ("agent.tools.todo_tool", "TodoTool"),
    "TaskTool": ("agent.tools.task_tool", "TaskTool"),
    "Neo4jQueryTool": ("agent.tools.neo4j_query_tool", "Neo4jQueryTool"),
}

__all__ = list(_LAZY_EXPORTS.keys())


def __getattr__(name: str) -> Any:
    """按需导出工具类，减少导入副作用并规避循环依赖。"""
    target = _LAZY_EXPORTS.get(name)
    if not target:
        raise AttributeError(f"module 'agent.tools' has no attribute '{name}'")
    module_name, attr_name = target
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
