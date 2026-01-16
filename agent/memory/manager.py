from __future__ import annotations

from typing import List

from agent.models import MemoryItem
from .episodic import EpisodicMemory
from .semantic import SemanticMemory
from .working import WorkingMemory


class MemoryManager:
    """统一调度工作、情景、语义三类记忆。"""

    def __init__(
        self,
        working_memory: WorkingMemory,
        episodic_memory: EpisodicMemory,
        semantic_memory: SemanticMemory,
    ) -> None:
        # 三类记忆统一挂载，保持接口一致
        self.working_memory = working_memory
        self.episodic_memory = episodic_memory
        self.semantic_memory = semantic_memory

    def add_memory(self, item: MemoryItem) -> None:
        # 按类型路由写入不同记忆系统
        if item.memory_type == "working":
            self.working_memory.add(item)
        elif item.memory_type == "episodic":
            self.episodic_memory.add(item)
        elif item.memory_type == "semantic":
            self.semantic_memory.add(item)
        else:
            # 默认写入工作记忆
            self.working_memory.add(item)

    def search(self, query: str, top_k: int = 5) -> List[MemoryItem]:
        """混合检索：合并三类记忆结果。"""
        # 三路召回后按分数排序，统一截断
        results = []
        results.extend(self.working_memory.search(query, top_k=top_k))
        results.extend(self.episodic_memory.search(query, top_k=top_k))
        results.extend(self.semantic_memory.search(query, top_k=top_k))
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]
