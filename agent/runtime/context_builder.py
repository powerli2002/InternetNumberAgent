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
from typing import Any, Callable, Dict, List, Optional, Tuple

from agent.core.llm import LLMClient, LLMMessage
from agent.core.models import ConversationTurn, EvidenceItem, MemoryItem
from agent.core.prompts import CONTEXT_COMPRESS_PROMPT


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
        llm_client: Optional[LLMClient] = None,
        compress_mode: str = "hybrid",
        compress_target_ratio: float = 0.7,
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
        self.llm_client = llm_client
        self.compress_mode = compress_mode if compress_mode in {"llm", "truncate", "hybrid"} else "hybrid"
        self.compress_target_ratio = min(0.95, max(0.3, float(compress_target_ratio)))

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
        """Compress：超限后按模式进行 LLM/截断压缩。"""
        if self.token_counter(context) <= self.max_tokens:
            return context
        if self.compress_mode == "truncate":
            return self._truncate_compress(context)

        if self.compress_mode in {"llm", "hybrid"}:
            compressed = self._llm_compress(context)
            if compressed:
                if self.token_counter(compressed) <= self.max_tokens:
                    return compressed
                # LLM 输出仍超限时，做一次截断收敛。
                return self._truncate_compress(compressed)

        # LLM 压缩失败或关闭时，回退截断策略保证可用性。
        return self._truncate_compress(context)

    def _llm_compress(self, context: str) -> Optional[str]:
        """调用 LLM 压缩上下文，失败时返回 None。"""
        if not self.llm_client:
            return None
        target_tokens = max(256, int(self.max_tokens * self.compress_target_ratio))
        prompt = CONTEXT_COMPRESS_PROMPT.format(
            target_ratio=f"{self.compress_target_ratio:.2f}",
            target_tokens=target_tokens,
        )
        try:
            compressed = self.llm_client.chat(
                [
                    LLMMessage(role="system", content=prompt),
                    LLMMessage(role="user", content=context),
                ],
                temperature=0.0,
            )
        except Exception:
            return None
        output = (compressed or "").strip()
        return output or None

    def _truncate_compress(self, context: str) -> str:
        """头尾保留截断策略，作为压缩兜底。"""
        text = context or ""
        if not text:
            return text
        compressed = text
        for _ in range(4):
            if self.token_counter(compressed) <= self.max_tokens:
                return compressed
            head = compressed[: max(160, len(compressed) // 2)]
            tail = compressed[-max(120, len(compressed) // 4) :]
            compressed = head + "\n...\n" + tail
        if self.token_counter(compressed) <= self.max_tokens:
            return compressed
        ratio = max(0.1, self.max_tokens / max(1, self.token_counter(compressed)))
        keep_chars = max(32, int(len(compressed) * ratio))
        final_text = compressed[:keep_chars]
        while self.token_counter(final_text) > self.max_tokens and keep_chars > 16:
            keep_chars = max(16, int(keep_chars * 0.8))
            final_text = compressed[:keep_chars]
        return final_text

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
        context, _trace_payload = self.build_with_trace(
            system_prompt=system_prompt,
            user_query=user_query,
            history=history,
            memories=memories,
            evidences=evidences,
            notes=notes,
        )
        return context

    def build_with_trace(
        self,
        system_prompt: str,
        user_query: str,
        history: List[ConversationTurn],
        memories: List[MemoryItem],
        evidences: List[EvidenceItem],
        notes: List[str],
    ) -> Tuple[str, Dict[str, Any]]:
        """完整流水线 + 追踪信息：用于记录压缩前后上下文与统计指标。"""
        # GSSC 流水线说明：
        # 1) Gather：收集系统/任务/历史/记忆/证据/笔记
        # 2) Select：按评分排序，优先保留高价值片段
        # 3) Structure：分区组织，减少模型上下文混乱
        # 4) Compress：超长时裁剪，确保不超过 token 限制
        chunks = self.gather(system_prompt, user_query, history, memories, evidences, notes)
        selected = self.select(chunks)
        structured = self.structure(selected)
        before_tokens = self.token_counter(structured)
        compressed = self.compress(structured)
        after_tokens = self.token_counter(compressed)

        trace_payload: Dict[str, Any] = {
            "chunk_stats": self._build_chunk_stats(chunks, selected),
            "token_stats": {
                "before_compress": before_tokens,
                "after_compress": after_tokens,
                "max_tokens": self.max_tokens,
                "compression_applied": bool(after_tokens < before_tokens),
            },
            "compress_config": {
                "mode": self.compress_mode,
                "target_ratio": self.compress_target_ratio,
            },
            # 由上游节点统一截断后写入追踪，避免在构建器内引入追踪策略。
            "context_before_compress": structured,
            "context_after_compress": compressed,
        }
        return compressed, trace_payload

    @staticmethod
    def _build_chunk_stats(chunks: List[ContextChunk], selected: List[ContextChunk]) -> Dict[str, Any]:
        """汇总上下文分块统计，便于追踪模型输入构成。"""
        def _classify(title: str) -> str:
            if title.startswith("Role"):
                return "Role & Policy"
            if title.startswith("Task"):
                return "Task"
            if title.startswith("Evidence"):
                return "Evidence"
            return "Context"

        by_section = {
            "Role & Policy": 0,
            "Task": 0,
            "Evidence": 0,
            "Context": 0,
        }
        for chunk in selected:
            by_section[_classify(chunk.title)] += 1

        return {
            "gathered_total": len(chunks),
            "selected_total": len(selected),
            "selected_by_section": by_section,
        }

    @staticmethod
    def _default_token_counter(text: str) -> int:
        """粗略 token 估算：按中文/英文字符长度估算。"""
        import tiktoken  # type: ignore

        # 仅用于粗略估算，不保证与模型精确一致
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
