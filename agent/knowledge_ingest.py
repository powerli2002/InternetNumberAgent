from __future__ import annotations

import argparse
from pathlib import Path

from agent.core.config import AgentConfig
from agent.tools.rag_ingest_pipeline import MarkdownConverter, build_markdown_chunks, load_knowledge_documents
from agent.tools.rag_tool import RAGTool, build_rag_embedding


def main() -> None:
    parser = argparse.ArgumentParser(description="将 agent/knowledge 领域知识写入 Milvus")
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--path", default="agent/knowledge", help="知识目录路径")
    parser.add_argument("--collection", default=None, help="Milvus collection 名称")
    parser.add_argument("--chunk-size", type=int, default=900, help="分块大小")
    parser.add_argument("--chunk-overlap", type=int, default=150, help="分块重叠")
    parser.add_argument("--reset", action="store_true", help="写入前清空目标集合")
    parser.add_argument(
        "--allow-fallback-converter",
        action="store_true",
        help="允许在缺少 markitdown 时回退到文本读取（默认关闭，推荐保持关闭）",
    )
    args = parser.parse_args()

    root_dir = Path(args.root).resolve()
    knowledge_dir = (root_dir / args.path).resolve()
    if not knowledge_dir.exists():
        raise RuntimeError(f"知识目录不存在: {knowledge_dir}")

    config = AgentConfig.load(root_dir)
    collection_name = args.collection or config.vector_collection

    converter = MarkdownConverter(require_markitdown=not args.allow_fallback_converter)
    documents = load_knowledge_documents(knowledge_dir, converter)
    chunks = build_markdown_chunks(documents, chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap)
    if not chunks:
        raise RuntimeError("未生成可写入的文档切片，请检查源文档内容。")

    if args.reset:
        try:
            from pymilvus import connections, utility  # type: ignore
        except Exception as exc:
            raise RuntimeError("缺少 pymilvus，无法清理集合。") from exc
        connections.connect(host=config.milvus_host, port=str(config.milvus_port))
        if utility.has_collection(collection_name):
            utility.drop_collection(collection_name)

    rag_tool = RAGTool(
        host=config.milvus_host,
        port=config.milvus_port,
        collection_name=collection_name,
        embedding=build_rag_embedding(config),
        enable_mqe=config.rag_enable_mqe,
        mqe_max_queries=config.rag_mqe_max_queries,
        candidate_multiplier=config.rag_candidate_multiplier,
        rrf_k=config.rag_rrf_k,
    )
    stats = rag_tool.index_documents(chunks)

    print(
        "Milvus 写入完成 "
        f"collection={rag_tool.collection_name} "
        f"docs={len(documents)} "
        f"chunks={len(chunks)} "
        f"input={stats.get('input', 0)} "
        f"batch_unique={stats.get('batch_unique', 0)} "
        f"inserted={stats.get('inserted', 0)} "
        f"skipped={stats.get('skipped', 0)}"
    )


if __name__ == "__main__":
    main()
