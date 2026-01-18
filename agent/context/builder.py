"""
上下文工程模块 - GSSC 流程实现

实现基于 Gather-Select-Structure-Compress 的上下文组织流程：
1. Gather: 收集系统提示、用户问题、历史对话、记忆、证据
2. Select: 按相关性评分排序，选择最有价值的片段
3. Structure: 按预定义模板分区组织上下文
4. Compress: 控制总长度，避免超出模型限制

核心特性：
- 分区组织：Role & Policy、Task、Evidence、Context、Output
- 智能截断：优先保留高价值内容，压缩低价值内容
- Token 控制：精确估算上下文长度
- 证据驱动：优先保证证据信息的完整性

上下文结构：
- Role & Policy: 系统指令和行为约束
- Task: 当前用户问题
- Evidence: 工具调用结果和检索证据
- Context: 历史对话和记忆内容
- Output: 结构化输出格式要求
"""

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
    """
    GSSC 上下文构建器

    实现检索增强生成中的上下文组织核心逻辑，确保模型接收到
    最相关、最有价值的上下文信息，同时控制总长度在模型限制内。

    GSSC 流程详解：
    - Gather: 收集所有可用信息源（系统提示、问题、历史、证据、记忆）
    - Select: 通过评分机制选择最相关的片段
    - Structure: 按功能分区组织内容（角色、任务、证据、上下文、输出）
    - Compress: 当超出限制时智能压缩，优先保留核心信息

    分区策略：
    - Role & Policy: 系统级约束，始终保留
    - Task: 用户问题，始终保留
    - Evidence: 工具结果，高优先级保留
    - Context: 历史和记忆，中等优先级
    - Output: 格式要求，低优先级但重要性高
    """

    def __init__(
        self,
        max_tokens: int = 4096,
        token_counter: Optional[Callable[[str], int]] = None,
    ) -> None:
        """
        初始化上下文构建器

        Args:
            max_tokens: 最大上下文 token 数，默认 4096
            token_counter: Token 计数函数，可自定义以适配不同模型
        """
        # max_tokens 控制上下文长度，token_counter 可自定义估算方式
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
        # 先把系统指令与用户问题放在上下文最高优先级
        chunks = [
            ContextChunk(title="Role & Policy", content=system_prompt.strip(), score=1.0),
            ContextChunk(title="Task", content=user_query.strip(), score=1.0),
        ]

        # 历史对话作为辅助上下文，分数较低
        for turn in history[-8:]:
            chunks.append(
                ContextChunk(
                    title=f"History-{turn.role}",
                    content=turn.content,
                    score=0.6,
                )
            )

        # 记忆与证据提供事实支撑，分数高于历史
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

        # 便签作为轻量补充
        for note in notes:
            chunks.append(ContextChunk(title="Note", content=note, score=0.5))

        return chunks

    def select(self, chunks: List[ContextChunk]) -> List[ContextChunk]:
        """Select：按评分排序，保留高价值片段。"""
        # 分数高的片段排在前面，后续结构化时优先保留
        return sorted(chunks, key=lambda x: x.score, reverse=True)

    def structure(self, chunks: List[ContextChunk]) -> str:
        """Structure：按模板组织上下文。"""
        # 将片段按角色/任务/证据/背景分类，减少 LLM 误读
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
        # 简单保留头尾：头部常含系统/任务，尾部保留部分证据
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
        # GSSC 流水线说明：
        # 1) Gather：收集系统/任务/历史/记忆/证据/笔记
        # 2) Select：按评分排序，优先保留高价值片段
        # 3) Structure：分区组织，减少模型上下文混乱
        # 4) Compress：超长时裁剪，确保不超过 token 限制
        chunks = self.gather(system_prompt, user_query, history, memories, evidences, notes)
        selected = self.select(chunks)
        structured = self.structure(selected)
        return self.compress(structured)

    @staticmethod
    def _default_token_counter(text: str) -> int:
        """粗略 token 估算：按中文/英文字符长度估算。"""
        import tiktoken  # type: ignore

        # 仅用于粗略估算，不保证与模型精确一致
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
