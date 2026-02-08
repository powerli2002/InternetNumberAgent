"""
记忆系统统一管理模块

实现三类记忆的统一调度和管理：
1. 工作记忆（Working Memory）：短期对话上下文，内存存储
2. 情景记忆（Episodic Memory）：重要对话片段，PostgreSQL 持久化（无 PG 时回退 SQLite）
3. 语义记忆（Semantic Memory）：长期知识和概念，Neo4j 图存储

记忆策略：
- 写入时按类型路由到对应存储
- 检索时混合搜索并按相关性排序
- 支持时间衰减和重要性过滤
- 保证检索性能和存储效率

架构优势：
- 分层存储：不同类型记忆使用最适合的存储方式
- 统一接口：简化上层调用复杂度
- 可扩展性：易于添加新的记忆类型
- 容错性：单个记忆系统失败不影响整体
"""

from __future__ import annotations

from typing import List

from agent.core.models import MemoryItem
from .episodic import EpisodicMemory
from .semantic import SemanticMemory
from .working import WorkingMemory


class MemoryManager:
    """
    记忆系统统一管理器

    协调三种记忆类型的写入和检索操作，实现记忆系统的统一接口。
    采用门面模式简化上层调用，同时保持各记忆系统的独立性。

    记忆分层策略：
    - 工作记忆：快速访问，容量有限，存储最近对话
    - 情景记忆：持久化存储，支持时间衰减，记录重要片段
    - 语义记忆：图结构存储，记录概念关系，长期保存

    检索策略：
    - 并行搜索：同时查询三种记忆系统
    - 统一排序：按相关性分数倒序排列
    - Top-K 截断：返回最相关的结果
    """

    def __init__(
        self,
        working_memory: WorkingMemory,
        episodic_memory: EpisodicMemory,
        semantic_memory: SemanticMemory,
    ) -> None:
        """
        初始化记忆管理器

        Args:
            working_memory: 工作记忆实例
            episodic_memory: 情景记忆实例
            semantic_memory: 语义记忆实例
        """
        # 三类记忆统一挂载，保持接口一致
        self.working_memory = working_memory
        self.episodic_memory = episodic_memory
        self.semantic_memory = semantic_memory

    def add_memory(self, item: MemoryItem) -> None:
        """
        添加记忆条目到相应记忆系统

        根据记忆类型自动路由到对应的存储系统：
        - working: 工作记忆（短期对话）
        - episodic: 情景记忆（重要对话片段）
        - semantic: 语义记忆（长期知识）
        - 其他: 默认写入工作记忆

        Args:
            item: 要添加的记忆条目
        """
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
        """
        在所有记忆系统中搜索相关内容

        执行流程：
        1. 并行查询三种记忆系统
        2. 收集所有搜索结果
        3. 按相关性分数统一排序
        4. 返回 Top-K 最相关结果

        Args:
            query: 搜索查询字符串
            top_k: 返回结果的最大数量

        Returns:
            List[MemoryItem]: 按相关性排序的记忆条目列表
        """
        # 三路召回后按分数排序，统一截断
        results = []
        results.extend(self.working_memory.search(query, top_k=top_k))
        results.extend(self.episodic_memory.search(query, top_k=top_k))
        results.extend(self.semantic_memory.search(query, top_k=top_k))
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]
