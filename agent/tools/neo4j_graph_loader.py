#!/usr/bin/env python3
"""兼容入口：已迁移到 `agent.scripts.neo4j_graph_loader`。"""

from __future__ import annotations

from agent.scripts.neo4j_graph_loader import main as _new_main


def main() -> None:
    """兼容旧命令入口，转调新脚本实现。"""
    print("[DEPRECATED] `agent.tools.neo4j_graph_loader` 已迁移，请改用 `agent.scripts.neo4j_graph_loader`。")
    _new_main()


if __name__ == "__main__":
    main()
