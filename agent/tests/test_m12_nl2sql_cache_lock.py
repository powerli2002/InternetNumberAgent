from __future__ import annotations

import threading
import time

from agent.tools.nl2sql_tool import NL2SQLTool


def test_get_or_build_retrievers_builds_once_per_signature() -> None:
    """同一 signature 的并发请求应只触发一次真实重建。"""
    tool = object.__new__(NL2SQLTool)
    tool.enable_index_cache = True
    tool.force_rebuild_cache = False
    tool._table_retriever_cache = None
    tool._cols_retrievers_cache = None
    tool._cache_signature = None
    tool._cache_build_locks = {}
    tool._cache_build_locks_guard = threading.Lock()

    build_started = threading.Event()
    build_count = 0
    build_count_lock = threading.Lock()

    def _compute_schema_signature(_table_names):
        return "sig-1"

    def _is_cache_valid(_signature):
        return False

    def _milvus_cache_ready(_build_tables, _build_columns):
        return False

    def _load_table_retriever_from_milvus(**_kwargs):
        return None

    def _load_column_retrievers_from_milvus(**_kwargs):
        return None

    def _clear_cache_dir():
        return None

    def _drop_milvus_partition(_partition_name):
        return None

    def _write_index_manifest(_signature, _table_names, build_columns):
        assert build_columns is False

    def _build_table_retriever(**_kwargs):
        nonlocal build_count
        with build_count_lock:
            build_count += 1
        build_started.set()
        time.sleep(0.05)
        return "table-retriever"

    def _build_column_retrievers(**_kwargs):
        raise AssertionError("本用例不应构建列索引")

    tool._compute_schema_signature = _compute_schema_signature  # type: ignore[method-assign]
    tool._is_cache_valid = _is_cache_valid  # type: ignore[method-assign]
    tool._milvus_cache_ready = _milvus_cache_ready  # type: ignore[method-assign]
    tool._load_table_retriever_from_milvus = _load_table_retriever_from_milvus  # type: ignore[method-assign]
    tool._load_column_retrievers_from_milvus = _load_column_retrievers_from_milvus  # type: ignore[method-assign]
    tool._clear_cache_dir = _clear_cache_dir  # type: ignore[method-assign]
    tool._drop_milvus_partition = _drop_milvus_partition  # type: ignore[method-assign]
    tool._write_index_manifest = _write_index_manifest  # type: ignore[method-assign]
    tool._build_table_retriever = _build_table_retriever  # type: ignore[method-assign]
    tool._build_column_retrievers = _build_column_retrievers  # type: ignore[method-assign]

    results: list[tuple[object, object]] = []

    def _run() -> None:
        results.append(
            tool._get_or_build_retrievers(
                table_names=["as_entity"],
                table_schema=["schema"],
                table_node_mapping="mapping",
                table_top_k=4,
                embed_model="embed",
                text_node_cls="TextNode",
                vector_index_cls="VectorStoreIndex",
                enable_columns=False,
            )
        )

    thread_one = threading.Thread(target=_run)
    thread_two = threading.Thread(target=_run)
    thread_one.start()
    assert build_started.wait(timeout=1), "首个线程未进入构建阶段"
    thread_two.start()
    thread_one.join()
    thread_two.join()

    assert build_count == 1
    assert results == [("table-retriever", None), ("table-retriever", None)]
    assert tool._cache_signature == "sig-1"
