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
from functools import lru_cache
from pathlib import Path
import re
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
        compress_mode: str = "llm",
        compress_target_ratio: float = 0.7,
        compress_temperature: float = 0.0,
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
        # 压缩策略已固定为 LLM；保留参数仅为兼容既有调用点。
        self.compress_mode = "llm"
        self.compress_target_ratio = min(0.95, max(0.3, float(compress_target_ratio)))
        self.compress_temperature = float(compress_temperature)

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
            ContextChunk(
                title="Role & Policy", content=system_prompt.strip(), score=1.0
            ),
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
        """统一使用 LLM 压缩；若单次输入超窗则先分块再多次调用 LLM。"""
        text = (context or "").strip()
        if not text:
            return text
        if not self.llm_client:
            raise RuntimeError("缺少 llm_client，无法执行统一 LLM 上下文压缩。")
        return self._compress_context_tree(text, self.max_tokens)

    def _compress_context_tree(
        self, context: str, target_tokens: int, depth: int = 0
    ) -> str:
        """按 Evidence / Other 分桶递归压缩，直到收敛到目标预算。"""
        text = (context or "").strip()
        if not text:
            return text
        if depth > 6:
            raise RuntimeError("上下文 LLM 压缩递归超过限制，未能收敛。")

        evidence_context, other_context, evidence_first = (
            self._extract_evidence_context(text)
        )
        if evidence_context and other_context:
            targets = self._allocate_target_tokens(
                [evidence_context, other_context], target_tokens
            )
            compressed_evidence = self._compress_with_llm(
                evidence_context, targets[0], depth + 1
            )
            compressed_other = self._compress_with_llm(
                other_context, targets[1], depth + 1
            )
            compressed = self._join_compressed_parts(
                evidence_context=compressed_evidence,
                other_context=compressed_other,
                evidence_first=evidence_first,
            )
        else:
            compressed = self._compress_with_llm(text, target_tokens, depth + 1)

        compressed_tokens = self.token_counter(compressed)
        if compressed_tokens <= max(1, int(target_tokens)):
            return compressed
        if compressed_tokens >= self.token_counter(text):
            raise RuntimeError("LLM 压缩未能收敛到目标长度。")
        return self._compress_context_tree(compressed, target_tokens, depth + 1)

    def _compress_with_llm(
        self, context: str, target_tokens: int, depth: int = 0
    ) -> str:
        """对单段文本执行 LLM 压缩；超出单次输入预算时分块递归压缩。"""
        text = (context or "").strip()
        if not text:
            return text
        if depth > 8:
            raise RuntimeError("单段上下文 LLM 压缩递归超过限制，未能收敛。")

        safe_target = max(1, int(target_tokens))
        current_tokens = self.token_counter(text)
        input_budget = self._llm_input_budget()
        if current_tokens > input_budget:
            chunks = self._split_into_llm_chunks(text, input_budget)
            compressed = self._compress_chunk_sequence(chunks, safe_target, depth + 1)
            compressed_tokens = self.token_counter(compressed)
            if compressed_tokens <= safe_target:
                return compressed
            if compressed_tokens >= current_tokens:
                raise RuntimeError("分块 LLM 压缩未能收敛到目标长度。")
            return self._compress_with_llm(compressed, safe_target, depth + 1)

        compressed = self._llm_compress(text, safe_target)
        compressed_tokens = self.token_counter(compressed)
        if compressed_tokens <= safe_target:
            return compressed
        if compressed_tokens >= current_tokens:
            chunks = self._split_into_llm_chunks(
                text, max(1, min(input_budget, safe_target))
            )
            if len(chunks) <= 1:
                raise RuntimeError("LLM 压缩未能收敛到目标长度。")
            compressed = self._compress_chunk_sequence(chunks, safe_target, depth + 1)
            if self.token_counter(compressed) <= safe_target:
                return compressed
            if self.token_counter(compressed) >= current_tokens:
                raise RuntimeError("分块 LLM 压缩未能收敛到目标长度。")
        return self._compress_with_llm(compressed, safe_target, depth + 1)

    def _compress_chunk_sequence(
        self, chunks: List[str], target_tokens: int, depth: int
    ) -> str:
        """按目标预算压缩分块序列，再按原顺序拼接。"""
        if not chunks:
            return ""
        chunk_targets = self._allocate_target_tokens(chunks, target_tokens)
        compressed_chunks: List[str] = []
        for chunk, chunk_target in zip(chunks, chunk_targets):
            compressed_chunks.append(
                self._compress_with_llm(chunk, chunk_target, depth + 1)
            )
        merged = "\n\n".join(
            item.strip() for item in compressed_chunks if item and item.strip()
        ).strip()
        if not merged:
            raise RuntimeError("LLM 分块压缩返回空结果。")
        return merged

    def _llm_input_budget(self) -> int:
        """单次 LLM 压缩请求的最大输入预算，预留系统提示词空间。"""
        return max(64, int(self.max_tokens * 0.8))

    def _llm_compress(self, context: str, target_tokens: int) -> str:
        """调用 LLM 压缩单段上下文；失败时直接抛错，不做截断回退。"""
        if not self.llm_client:
            raise RuntimeError("缺少 llm_client，无法执行统一 LLM 上下文压缩。")
        source_tokens = max(1, self.token_counter(context))
        safe_target = max(1, int(target_tokens))
        target_ratio = min(
            self.compress_target_ratio, max(0.05, safe_target / source_tokens)
        )
        prompt = CONTEXT_COMPRESS_PROMPT.format(
            target_ratio=f"{target_ratio:.2f}",
            target_tokens=safe_target,
        )
        compressed = self.llm_client.chat(
            [
                LLMMessage(role="system", content=prompt),
                LLMMessage(role="user", content=context),
            ],
            temperature=self.compress_temperature,
        )
        output = (compressed or "").strip()
        if not output:
            return context  # 如果压缩失败，返回原始上下文
        return output

    def _allocate_target_tokens(
        self, parts: List[str], total_target_tokens: int
    ) -> List[int]:
        """按原始 token 占比给各段分配压缩目标预算。"""
        if not parts:
            return []
        safe_total = max(1, int(total_target_tokens))
        weights = [max(1, self.token_counter(part)) for part in parts]
        weight_sum = sum(weights)
        targets = [max(1, int(safe_total * weight / weight_sum)) for weight in weights]
        allocated = sum(targets)

        if allocated < safe_total:
            order = sorted(
                range(len(weights)), key=lambda idx: weights[idx], reverse=True
            )
            cursor = 0
            while allocated < safe_total and order:
                targets[order[cursor % len(order)]] += 1
                allocated += 1
                cursor += 1
        elif allocated > safe_total:
            order = sorted(
                range(len(targets)), key=lambda idx: targets[idx], reverse=True
            )
            cursor = 0
            guard = 0
            while allocated > safe_total and order and guard < len(order) * safe_total:
                idx = order[cursor % len(order)]
                if targets[idx] > 1:
                    targets[idx] -= 1
                    allocated -= 1
                cursor += 1
                guard += 1
        return targets

    def _extract_evidence_context(self, context: str) -> Tuple[str, str, bool]:
        """从结构化上下文中拆出 Evidence 与 Other 两个桶，并记录原始桶顺序。"""
        text = (context or "").strip()
        if not text:
            return "", "", False

        header_pattern = re.compile(r"(?m)^\[(?P<name>[^\n\]]+)\]\s*$")
        matches = list(header_pattern.finditer(text))
        if not matches:
            return "", text, False

        evidence_blocks: List[str] = []
        other_blocks: List[str] = []
        first_bucket: Optional[str] = None
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            block = text[start:end].strip()
            if not block:
                continue
            bucket = (
                "evidence" if match.group("name").strip() == "Evidence" else "other"
            )
            if first_bucket is None:
                first_bucket = bucket
            if bucket == "evidence":
                evidence_blocks.append(block)
            else:
                other_blocks.append(block)

        return (
            "\n\n".join(evidence_blocks).strip(),
            "\n\n".join(other_blocks).strip(),
            first_bucket == "evidence",
        )

    def _join_compressed_parts(
        self, evidence_context: str, other_context: str, evidence_first: bool
    ) -> str:
        """按原始桶顺序把压缩后的两部分重新拼回单段上下文。"""
        ordered_parts = (
            [evidence_context, other_context]
            if evidence_first
            else [other_context, evidence_context]
        )
        return "\n\n".join(
            part.strip() for part in ordered_parts if part and part.strip()
        ).strip()

    def _split_into_llm_chunks(self, text: str, input_budget: int) -> List[str]:
        """先按段落拆块；段落仍超预算时直接按固定 token 窗口继续切小。"""
        paragraph_blocks = [
            block.strip()
            for block in re.split(r"\n{2,}", text.strip())
            if block.strip()
        ]
        if not paragraph_blocks:
            return [text.strip()]

        # 单块输入预算固定使用 0.8 * 当前上下文窗口，不再按更细粒度的行切分。
        chunk_limit = max(1, min(int(input_budget), self._llm_input_budget()))
        blocks: List[str] = []
        for block in paragraph_blocks:
            if self.token_counter(block) <= chunk_limit:
                blocks.append(block)
                continue
            blocks.extend(self._split_by_fixed_window(block, chunk_limit))
        return blocks or [text.strip()]

    def _split_by_fixed_window(self, text: str, chunk_limit: int) -> List[str]:
        """按固定 token 窗口切块，确保每块都可发给 LLM。"""
        content = (text or "").strip()
        if not content:
            return []
        safe_limit = max(1, int(chunk_limit))
        chunks: List[str] = []
        remaining = content
        while remaining:
            if self.token_counter(remaining) <= safe_limit:
                chunks.append(remaining.strip())
                break
            prefix = self._fit_prefix_to_token_limit(remaining, safe_limit)
            if not prefix:
                raise RuntimeError("固定窗口切分失败：无法为当前块找到可用前缀。")
            chunks.append(prefix.strip())
            remaining = remaining[len(prefix) :].lstrip()
        return [chunk for chunk in chunks if chunk]

    def _fit_prefix_to_token_limit(self, text: str, token_limit: int) -> str:
        """通过二分查找找到不超过 token_limit 的最长前缀。"""
        if not text:
            return ""
        if self.token_counter(text) <= token_limit:
            return text
        left = 1
        right = len(text)
        best = ""
        while left <= right:
            middle = (left + right) // 2
            candidate = text[:middle]
            if self.token_counter(candidate) <= token_limit:
                best = candidate
                left = middle + 1
            else:
                right = middle - 1
        if best:
            return best
        return text[:1]

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
        chunks = self.gather(
            system_prompt, user_query, history, memories, evidences, notes
        )
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
    def _build_chunk_stats(
        chunks: List[ContextChunk], selected: List[ContextChunk]
    ) -> Dict[str, Any]:
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
    @lru_cache(maxsize=1)
    def _default_tokenizer():
        """加载本地 Qwen tokenizer，并在进程内复用单例。"""
        try:
            from tokenizers import Tokenizer  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "未安装 tokenizers，无法加载本地 Qwen tokenizer。"
            ) from exc

        tokenizer_path = (
            Path(__file__).resolve().parents[1] / "model" / "data" / "tokenizer.json"
        )
        if not tokenizer_path.exists():
            raise RuntimeError(f"未找到 Qwen tokenizer 文件：{tokenizer_path}")
        return Tokenizer.from_file(str(tokenizer_path))

    @staticmethod
    def _default_token_counter(text: str) -> int:
        """使用本地 Qwen tokenizer 统计文本 token 数。"""
        tokenizer = ContextBuilder._default_tokenizer()
        return len(tokenizer.encode(text).ids)
