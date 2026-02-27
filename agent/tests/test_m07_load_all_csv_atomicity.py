from __future__ import annotations

import pytest


pytestmark = [
    pytest.mark.live,
    pytest.mark.skip(reason="需要专用双库测试环境与故障注入配置。"),
]


def test_dual_import_success_updates_both_stores() -> None:
    """场景1：PG 与 Neo4j 同时成功，双库都更新。"""


def test_dual_import_neo4j_retry_then_success() -> None:
    """场景2：Neo4j 首次失败、重试成功，最终提交。"""


def test_dual_import_neo4j_retry_exhausted_rolls_back_pg() -> None:
    """场景3：Neo4j 连续失败，PG 回滚到旧快照。"""


def test_dual_import_requires_prepared_transaction_support() -> None:
    """场景4：max_prepared_transactions=0 时，流程应直接失败退出。"""
