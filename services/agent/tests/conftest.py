from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any, Dict, List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.core.config import AgentConfig
from agent.services.mcp.client import MCPToolClient


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def pytest_collection_modifyitems(config: pytest.Config, items: List[pytest.Item]) -> None:
    """未开启 live 模式时跳过所有 live 测试。"""
    # 默认开启 live：未显式设置时按 FUSION_RUN_LIVE=1 处理。
    if _is_truthy(os.getenv("FUSION_RUN_LIVE", "1")):
        return

    skip_live = pytest.mark.skip(reason="FUSION_RUN_LIVE=0，跳过 live 测试。")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(scope="session")
def agent_config() -> AgentConfig:
    """加载统一配置，供测试复用。"""
    # agent 现位于 services/agent/，由 load() 自行向上推导仓库根定位 conf/
    return AgentConfig.load()


@pytest.fixture(scope="session")
def mcp_client(agent_config: AgentConfig) -> MCPToolClient:
    """MCP 客户端夹具。"""
    timeout_seconds = max(30, int(agent_config.mcp_timeout_seconds))
    return MCPToolClient(
        server_url=agent_config.mcp_server_url,
        timeout_seconds=timeout_seconds,
    )


@pytest.fixture(scope="session")
def postgres_engine(agent_config: AgentConfig):
    """PostgreSQL 引擎夹具。"""
    if not agent_config.postgres_url:
        raise RuntimeError("POSTGRES_URL 为空，无法执行数据库测试。")
    from sqlalchemy import create_engine  # type: ignore

    engine = create_engine(agent_config.postgres_url)
    return engine


@pytest.fixture(scope="session")
def sql_scalar(postgres_engine):
    """执行 SQL 并返回第一行第一列。"""
    from sqlalchemy import text  # type: ignore

    def _run(sql: str, params: Dict[str, Any] | None = None) -> Any:
        with postgres_engine.connect() as conn:
            return conn.execute(text(sql), params or {}).scalar()

    return _run


@pytest.fixture(scope="session")
def neo4j_driver(agent_config: AgentConfig):
    """Neo4j 驱动夹具。"""
    from neo4j import GraphDatabase  # type: ignore

    driver = GraphDatabase.driver(
        agent_config.neo4j_uri,
        auth=(agent_config.neo4j_user, agent_config.neo4j_password),
    )
    yield driver
    driver.close()


@pytest.fixture(scope="session")
def neo4j_scalar(neo4j_driver):
    """执行 Cypher 并返回单值字段。"""

    def _run(cypher: str, field: str = "value") -> Any:
        with neo4j_driver.session() as session:
            record = session.run(cypher).single()
            if record is None:
                raise RuntimeError(f"Cypher 未返回结果: {cypher}")
            return record[field]

    return _run


@pytest.fixture(scope="session")
def rag_tool_local(agent_config: AgentConfig):
    """本地 RAG 工具夹具，用于直连 Milvus 生成标准答案。"""
    from agent.tools.rag_tool import RAGTool, build_rag_embedding

    return RAGTool(
        host=agent_config.milvus_host,
        port=agent_config.milvus_port,
        collection_name=agent_config.vector_collection,
        embedding=build_rag_embedding(agent_config),
        enable_mqe=agent_config.rag_enable_mqe,
        mqe_max_queries=agent_config.rag_mqe_max_queries,
        candidate_multiplier=agent_config.rag_candidate_multiplier,
        rrf_k=agent_config.rag_rrf_k,
    )
