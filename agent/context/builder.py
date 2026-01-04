from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from agent.models import ConversationTurn, EvidenceItem, MemoryItem


@dataclass
class ContextChunk:
    """上下文片段。"""

    title: str
    content: str
    score: float


class ContextBuilder:
    """基于 GSSC 的上下文构建器。"""

    def __init__(
        self,
        max_tokens: int = 4096,
        token_counter: Optional[Callable[[str], int]] = None,
    ) -> None:
        self.max_tokens = max_tokens
        self.token_counter = token_counter or self._default_token_counter

    def gather(
        self,
        system_prompt: str,
        user_query: str,
        history: List[ConversationTurn],
        memories: List[MemoryItem],
        evidences: List[EvidenceItem],
        notes: List[str],
    ) -> List[ContextChunk]:
        """Gather：收集系统、历史、记忆、证据、笔记。"""
        chunks = [
            ContextChunk(title="Role & Policy", content=system_prompt.strip(), score=1.0),
            ContextChunk(title="Task", content=user_query.strip(), score=1.0),
        ]

        for turn in history[-8:]:
            chunks.append(
                ContextChunk(
                    title=f"History-{turn.role}",
                    content=turn.content,
                    score=0.6,
                )
            )

        for mem in memories:
            chunks.append(
                ContextChunk(
                    title=f"Memory-{mem.memory_type}",
                    content=mem.content,
                    score=0.8 + mem.score,
                )
            )

        for evidence in evidences:
            chunks.append(
                ContextChunk(
                    title=f"Evidence-{evidence.source}",
                    content=evidence.content,
                    score=0.9 + evidence.score,
                )
            )

        for note in notes:
            chunks.append(ContextChunk(title="Note", content=note, score=0.5))

        return chunks

    def select(self, chunks: List[ContextChunk]) -> List[ContextChunk]:
        """Select：按评分排序，保留高价值片段。"""
        return sorted(chunks, key=lambda x: x.score, reverse=True)

    def structure(self, chunks: List[ContextChunk]) -> str:
        """Structure：按模板组织上下文。"""
        sections = {
            "Role & Policy": [],
            "Task": [],
            "Evidence": [],
            "Context": [],
            "Output": [],
        }
        for chunk in chunks:
            if chunk.title.startswith("Role"):
                sections["Role & Policy"].append(chunk.content)
            elif chunk.title.startswith("Task"):
                sections["Task"].append(chunk.content)
            elif chunk.title.startswith("Evidence"):
                sections["Evidence"].append(chunk.content)
            else:
                sections["Context"].append(chunk.content)

        context = []
        for name, items in sections.items():
            if not items:
                continue
            context.append(f"[{name}]\n" + "\n".join(items))
        return "\n\n".join(context)

    def compress(self, context: str) -> str:
        """Compress：超过 token 限制时进行截断。"""
        if self.token_counter(context) <= self.max_tokens:
            return context
        # 简化策略：保留开头与结尾
        head = context[: max(0, len(context) // 2)]
        tail = context[-max(0, len(context) // 4) :]
        compressed = head + "\n...\n" + tail
        return compressed

    def build(
        self,
        system_prompt: str,
        user_query: str,
        history: List[ConversationTurn],
        memories: List[MemoryItem],
        evidences: List[EvidenceItem],
        notes: List[str],
    ) -> str:
        """完整流水线：Gather -> Select -> Structure -> Compress。"""
        chunks = self.gather(system_prompt, user_query, history, memories, evidences, notes)
        selected = self.select(chunks)
        structured = self.structure(selected)
        return self.compress(structured)

    @staticmethod
    def _default_token_counter(text: str) -> int:
        """粗略 token 估算：按中文/英文字符长度估算。"""
        import tiktoken  # type: ignore

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
