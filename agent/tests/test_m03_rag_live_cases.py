from __future__ import annotations

import pytest


RAG_CASES = [
    {
        "case_id": "rag_rpki_role",
        "question": "RPKI 的作用是什么？",
    },
    {
        "case_id": "rag_bgp_hijack_detection",
        "question": "BGP hijack 如何检测？",
    },
    {
        "case_id": "rag_as_relationship_inference",
        "question": "AS 商业关系推断有哪些常见类型？",
    },
]


def _normalize_chunk_pairs(chunks, limit: int = 3):
    """把检索结果归一化为可比较的 (source, text_prefix) 列表。"""
    pairs = []
    for chunk in chunks[:limit]:
        source = str(chunk.source)
        text_prefix = str(chunk.text).replace("\n", " ").strip()[:120]
        pairs.append((source, text_prefix))
    return pairs


def _normalize_mcp_pairs(chunks, limit: int = 3):
    """把 MCP rag_search 结果归一化为可比较的 (source, text_prefix) 列表。"""
    pairs = []
    for chunk in chunks[:limit]:
        source = str(chunk.get("source", ""))
        text_prefix = str(chunk.get("text", "")).replace("\n", " ").strip()[:120]
        pairs.append((source, text_prefix))
    return pairs


def _short_error(exc: Exception) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text[:300]


@pytest.fixture(scope="module")
def rag_live_ready(rag_tool_local, mcp_client) -> None:
    """RAG live 就绪探测：环境不满足时跳过本模块测试。"""
    probe_query = "RPKI 是什么"
    try:
        direct_chunks = rag_tool_local.search(probe_query, top_k=1)
    except Exception as exc:  # pragma: no cover - 仅用于 live 环境探测
        pytest.skip(f"RAG 未就绪（直连 Milvus 失败）: {_short_error(exc)}")
    if not direct_chunks:
        pytest.skip("RAG 未就绪（Milvus 无可检索文档）。")

    try:
        mcp_payload = mcp_client.call_tool(
            "rag_search",
            {
                "query": probe_query,
                "top_k": 1,
                "trace_id": "test-rag-live-ready",
            },
        )
    except Exception as exc:  # pragma: no cover - 仅用于 live 环境探测
        pytest.skip(f"RAG 未就绪（MCP rag_search 失败）: {_short_error(exc)}")

    chunks = mcp_payload.get("chunks") if isinstance(mcp_payload, dict) else None
    if not isinstance(chunks, list) or not chunks:
        pytest.skip("RAG 未就绪（MCP rag_search 未返回有效 chunks）。")


@pytest.mark.live
@pytest.mark.parametrize("case", RAG_CASES, ids=[c["case_id"] for c in RAG_CASES])
def test_rag_natural_language_against_direct_milvus_baseline(
    case: dict[str, str],
    rag_tool_local,
    mcp_client,
    rag_live_ready,
) -> None:
    """RAG 用例：MCP rag_search 结果应与直连 Milvus 基线保持一致。"""
    del rag_live_ready  # 仅触发模块级就绪探测
    direct_chunks = rag_tool_local.search(case["question"], top_k=3)
    assert direct_chunks, "直连 Milvus 未返回结果。"

    mcp_payload = mcp_client.call_tool(
        "rag_search",
        {
            "query": case["question"],
            "top_k": 3,
            "trace_id": f"test-{case['case_id']}",
        },
    )
    assert isinstance(mcp_payload, dict)
    mcp_chunks = mcp_payload.get("chunks")
    assert isinstance(mcp_chunks, list) and mcp_chunks, "MCP rag_search 未返回结果。"

    direct_pairs = _normalize_chunk_pairs(direct_chunks)
    mcp_pairs = _normalize_mcp_pairs(mcp_chunks)
    assert mcp_pairs == direct_pairs


@pytest.mark.live
def test_rag_empty_query_returns_empty_chunks(mcp_client, rag_live_ready) -> None:
    """空查询应返回空结果，避免无意义召回。"""
    del rag_live_ready  # 仅触发模块级就绪探测
    payload = mcp_client.call_tool(
        "rag_search",
        {
            "query": "   ",
            "top_k": 3,
            "trace_id": "test-rag-empty-query",
        },
    )
    assert isinstance(payload, dict)
    assert payload.get("chunks") == []
