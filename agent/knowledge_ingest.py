from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, List, Tuple

from agent.config import AgentConfig
from agent.tools.rag_tool import DashScopeEmbedding, DocumentChunk, RAGTool


def _load_docx_text(path: Path) -> str:
    # 使用 python-docx 解析 docx，确保文本完整可控
    try:
        from docx import Document as DocxDocument  # type: ignore
    except Exception as exc:
        raise RuntimeError("缺少 python-docx，无法解析 .docx 文件。") from exc

    doc = DocxDocument(str(path))
    lines = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    return "\n".join(lines)


def _load_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _iter_knowledge_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


def _load_documents(knowledge_dir: Path) -> List[Tuple[str, str, dict]]:
    allowed_exts = {".md", ".txt", ".docx"}
    documents: List[Tuple[str, str, dict]] = []

    for path in _iter_knowledge_files(knowledge_dir):
        ext = path.suffix.lower()
        if ext not in allowed_exts:
            raise RuntimeError(f"不支持的文件类型: {path}")

        if ext == ".docx":
            text = _load_docx_text(path)
        else:
            text = _load_text_file(path)

        if not text.strip():
            raise RuntimeError(f"文档内容为空: {path}")

        source = str(path.relative_to(knowledge_dir.parent))
        metadata = {"source": source, "file_name": path.name}
        documents.append((text, source, metadata))

    if not documents:
        raise RuntimeError(f"{knowledge_dir} 未找到可导入的知识文件。")

    return documents


def _split_documents(documents: List[Tuple[str, str, dict]], chunk_size: int, chunk_overlap: int) -> List[DocumentChunk]:
    try:
        from llama_index.core import Document  # type: ignore
        from llama_index.core.node_parser import SentenceSplitter  # type: ignore
    except Exception as exc:
        raise RuntimeError("缺少 llama-index 依赖，无法进行知识切分。") from exc

    llama_docs = [Document(text=text, metadata=metadata) for text, _, metadata in documents]
    splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    nodes = splitter.get_nodes_from_documents(llama_docs)

    chunks: List[DocumentChunk] = []
    for node in nodes:
        source = node.metadata.get("source")
        if not source:
            raise RuntimeError("切分节点缺少 source 元数据，无法写入向量库。")
        chunks.append(
            DocumentChunk(
                text=node.get_content(),
                source=source,
                metadata=node.metadata,
            )
        )
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="将 agent/knowledge 领域知识写入 Milvus")
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--path", default="agent/knowledge", help="知识目录路径")
    parser.add_argument("--collection", default=None, help="Milvus collection 名称")
    parser.add_argument("--chunk-size", type=int, default=800, help="分块大小")
    parser.add_argument("--chunk-overlap", type=int, default=100, help="分块重叠")
    parser.add_argument("--reset", action="store_true", help="写入前清空目标集合")
    args = parser.parse_args()

    root_dir = Path(args.root).resolve()
    knowledge_dir = (root_dir / args.path).resolve()
    if not knowledge_dir.exists():
        raise RuntimeError(f"知识目录不存在: {knowledge_dir}")

    config = AgentConfig.load(root_dir)
    if not config.dashscope_api_key:
        raise RuntimeError("缺少 DASHSCOPE_API_KEY，无法生成向量。")

    documents = _load_documents(knowledge_dir)
    chunks = _split_documents(documents, args.chunk_size, args.chunk_overlap)

    collection_name = args.collection or config.vector_collection

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
        embedding=DashScopeEmbedding(
            api_key=config.dashscope_api_key,
            base_url=config.dashscope_base_url,
            model=config.dashscope_embedding_model,
        ),
    )
    rag_tool.index_documents(chunks)

    print(f"已写入 {len(chunks)} 个知识切片到 Milvus 集合: {rag_tool.collection_name}")


if __name__ == "__main__":
    main()
