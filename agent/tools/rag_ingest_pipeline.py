"""RAG 入库流水线：统一 Markdown 转换与结构化分块。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Dict, Iterable, List, Sequence, Tuple

from agent.tools.rag_tool import DocumentChunk

_SUPPORTED_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".docx",
    ".doc",
    ".pdf",
    ".html",
    ".htm",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".xlsx",
    ".xls",
    ".pptx",
    ".ppt",
}

_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass
class MarkdownDocument:
    """统一转换后的 Markdown 文档结构。"""

    text: str
    source: str
    metadata: Dict[str, str]


class MarkdownConverter:
    """使用 MarkItDown 将任意文档统一转换为 Markdown。"""

    def __init__(self, require_markitdown: bool = True) -> None:
        self.require_markitdown = require_markitdown
        self._converter = None
        self._markitdown_import_error: Exception | None = None
        try:
            from markitdown import MarkItDown  # type: ignore

            self._converter = MarkItDown()
        except Exception as exc:  # pragma: no cover - 依赖缺失时走兜底分支
            self._markitdown_import_error = exc

        if self.require_markitdown and self._converter is None:
            raise RuntimeError(
                "缺少 markitdown，无法执行统一 Markdown 转换。"
                "请先执行: pip install markitdown"
            ) from self._markitdown_import_error

    def convert(self, path: Path) -> str:
        """将单个文件转换为 Markdown 文本。"""
        if self._converter is not None:
            try:
                result = self._converter.convert(str(path))
                markdown = self._extract_markdown(result)
                if markdown.strip():
                    return markdown
            except Exception as exc:
                if self.require_markitdown:
                    raise RuntimeError(f"MarkItDown 转换失败: {path}") from exc

        # 兜底策略：文本类文件直接读取，确保最小可用性
        ext = path.suffix.lower()
        if ext in {".md", ".markdown", ".txt", ".csv", ".json", ".yaml", ".yml", ".xml", ".html", ".htm"}:
            return _read_text_file(path)
        if ext == ".docx":
            return _load_docx_text(path)
        raise RuntimeError(
            f"无法将文件转换为 Markdown: {path}。"
            "请确认已安装 markitdown，或将文件转为 .md/.txt 后重试。"
        )

    @staticmethod
    def _extract_markdown(result: object) -> str:
        """兼容不同版本 MarkItDown 返回对象。"""
        if isinstance(result, str):
            return result
        for attr in ("text_content", "markdown", "content", "text"):
            value = getattr(result, attr, None)
            if isinstance(value, str) and value.strip():
                return value
        return str(result or "")


def iter_knowledge_files(root: Path) -> Iterable[Path]:
    """遍历知识目录中的可处理文件。"""
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in _SUPPORTED_EXTENSIONS:
            yield path


def load_knowledge_documents(knowledge_dir: Path, converter: MarkdownConverter) -> List[MarkdownDocument]:
    """读取并转换知识目录下的文档。"""
    documents: List[MarkdownDocument] = []
    for path in iter_knowledge_files(knowledge_dir):
        markdown_text = converter.convert(path).strip()
        if not markdown_text:
            continue
        source = str(path.relative_to(knowledge_dir.parent))
        documents.append(
            MarkdownDocument(
                text=markdown_text,
                source=source,
                metadata={
                    "source": source,
                    "file_name": path.name,
                    "ext": path.suffix.lower(),
                },
            )
        )

    if not documents:
        raise RuntimeError(f"{knowledge_dir} 未找到可导入的知识文件。")
    return documents


def build_markdown_chunks(
    documents: Sequence[MarkdownDocument],
    chunk_size: int,
    chunk_overlap: int,
) -> List[DocumentChunk]:
    """基于 Markdown 标题结构进行智能分块。"""
    if chunk_size <= 0:
        raise RuntimeError("chunk_size 必须为正整数。")
    if chunk_overlap < 0:
        raise RuntimeError("chunk_overlap 不能为负数。")
    if chunk_overlap >= chunk_size:
        raise RuntimeError("chunk_overlap 必须小于 chunk_size。")

    all_chunks: List[DocumentChunk] = []
    for doc in documents:
        sections = _split_markdown_sections(doc.text)
        for section_idx, (section_path, section_text) in enumerate(sections):
            blocks = _split_semantic_blocks(section_text)
            if not blocks:
                continue
            chunks = _chunk_blocks(blocks, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            for chunk_idx, chunk_text in enumerate(chunks):
                normalized = chunk_text.strip()
                if len(normalized) < 20:
                    continue
                metadata = dict(doc.metadata)
                metadata.update(
                    {
                        "section_path": section_path,
                        "section_index": str(section_idx),
                        "chunk_index": str(chunk_idx),
                        "chunk_chars": str(len(normalized)),
                    }
                )
                all_chunks.append(
                    DocumentChunk(
                        text=normalized,
                        source=doc.source,
                        metadata=metadata,
                    )
                )

    return all_chunks


def _split_markdown_sections(markdown: str) -> List[Tuple[str, str]]:
    """按 Markdown 标题层级切分，保留结构上下文。"""
    lines = markdown.splitlines()
    if not lines:
        return []

    sections: List[Tuple[str, str]] = []
    heading_stack: List[str] = []
    current_lines: List[str] = []
    current_path = "导言"

    def flush_current() -> None:
        text = "\n".join(current_lines).strip()
        if text:
            sections.append((current_path, text))

    for line in lines:
        match = _HEADING_PATTERN.match(line)
        if not match:
            current_lines.append(line)
            continue

        flush_current()
        current_lines = [line]

        level = len(match.group(1))
        title = match.group(2).strip()
        heading_stack = heading_stack[: max(0, level - 1)]
        heading_stack.append(title)
        current_path = " / ".join(heading_stack)

    flush_current()
    if not sections and markdown.strip():
        sections.append(("正文", markdown.strip()))
    return sections


def _split_semantic_blocks(section_text: str) -> List[str]:
    """将 section 拆成段落/代码块，保证语义边界。"""
    blocks: List[str] = []
    buffer: List[str] = []
    in_code_block = False

    for line in section_text.splitlines():
        stripped = line.strip()
        is_code_fence = stripped.startswith("```")

        if is_code_fence:
            if in_code_block:
                buffer.append(line)
                block = "\n".join(buffer).strip()
                if block:
                    blocks.append(block)
                buffer = []
                in_code_block = False
                continue

            if buffer:
                block = "\n".join(buffer).strip()
                if block:
                    blocks.append(block)
                buffer = []
            buffer.append(line)
            in_code_block = True
            continue

        if in_code_block:
            buffer.append(line)
            continue

        if not stripped:
            if buffer:
                block = "\n".join(buffer).strip()
                if block:
                    blocks.append(block)
                buffer = []
            continue

        buffer.append(line)

    if buffer:
        block = "\n".join(buffer).strip()
        if block:
            blocks.append(block)

    return blocks


def _chunk_blocks(blocks: Sequence[str], chunk_size: int, chunk_overlap: int) -> List[str]:
    """将语义块拼装为 chunk，超长块回退到硬切分。"""
    chunks: List[str] = []
    current_blocks: List[str] = []

    def flush_current() -> None:
        nonlocal current_blocks
        text = "\n\n".join(current_blocks).strip()
        if text:
            chunks.append(text)
        current_blocks = _tail_overlap_blocks(current_blocks, overlap_chars=chunk_overlap)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        if len(block) > chunk_size:
            if current_blocks:
                flush_current()
                current_blocks = []
            chunks.extend(_hard_split_text(block, chunk_size=chunk_size, chunk_overlap=chunk_overlap))
            continue

        candidate_blocks = current_blocks + [block]
        candidate_text = "\n\n".join(candidate_blocks)
        if len(candidate_text) <= chunk_size:
            current_blocks = candidate_blocks
            continue

        flush_current()
        candidate_after_flush = current_blocks + [block]
        if len("\n\n".join(candidate_after_flush)) <= chunk_size:
            current_blocks = candidate_after_flush
        else:
            current_blocks = [block]

    if current_blocks:
        text = "\n\n".join(current_blocks).strip()
        if text:
            chunks.append(text)

    return chunks


def _tail_overlap_blocks(blocks: Sequence[str], overlap_chars: int) -> List[str]:
    """从末尾抽取重叠窗口，减少跨 chunk 信息损失。"""
    if overlap_chars <= 0:
        return []

    selected: List[str] = []
    total = 0
    for block in reversed(blocks):
        block_len = len(block)
        projected = total + block_len + (2 if selected else 0)
        if projected > overlap_chars and selected:
            break
        selected.insert(0, block)
        total = projected
        if total >= overlap_chars:
            break
    return selected


def _hard_split_text(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    """超长单块的兜底切分。"""
    if len(text) <= chunk_size:
        return [text]

    step = max(1, chunk_size - chunk_overlap)
    parts: List[str] = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(text_len, start + chunk_size)
        part = text[start:end].strip()
        if part:
            parts.append(part)
        if end >= text_len:
            break
        start += step
    return parts


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _load_docx_text(path: Path) -> str:
    """无 MarkItDown 时，docx 走轻量兜底解析。"""
    try:
        from docx import Document as DocxDocument  # type: ignore
    except Exception as exc:
        raise RuntimeError("缺少 python-docx，无法解析 .docx 文件。") from exc

    doc = DocxDocument(str(path))
    lines = [paragraph.text.strip() for paragraph in doc.paragraphs if paragraph.text and paragraph.text.strip()]
    return "\n".join(lines)
