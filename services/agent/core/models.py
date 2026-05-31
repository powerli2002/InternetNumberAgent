"""
数据模型定义模块

定义智能体系统中使用的数据结构和类型，包括：
1. 记忆条目：统一的三类记忆数据结构
2. 证据项：工具调用结果和检索信息的封装
3. 对话轮次：用户与助手间的对话记录
4. 待办事项：任务规划和分解的数据结构
5. 工具结果：工具执行的返回封装

设计原则：
- 使用 dataclass 简化数据定义和序列化
- 支持元数据扩展，便于后续功能增强
- 统一的评分机制，便于排序和筛选
- 时间戳追踪，支持审计和调试
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class MemoryItem:
    """
    统一的记忆条目数据结构

    用于封装所有类型的记忆内容，支持三类记忆系统的统一处理。
    包含内容、类型、时间戳和扩展元数据。

    记忆类型：
    - working: 工作记忆，短期对话上下文
    - episodic: 情景记忆，重要对话片段
    - semantic: 语义记忆，长期概念和知识
    """

    content: str
    """记忆内容文本"""

    memory_type: str
    """记忆类型：working/episodic/semantic"""

    created_at: datetime = field(default_factory=datetime.utcnow)
    """创建时间戳，用于时间衰减计算"""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """扩展元数据，如来源、标签、重要性等"""

    score: float = 0.0
    """相关性评分，检索时用于排序"""


@dataclass
class EvidenceItem:
    """
    上下文证据项

    封装工具调用结果和检索信息，作为上下文的证据来源。
    支持来源追踪和相关性评分。
    """

    title: str
    """证据标题，用于上下文分区"""

    content: str
    """证据内容文本"""

    source: str
    """证据来源：nl2sql/rag/task/memory 等"""

    score: float = 0.0
    """证据重要性评分"""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """扩展元数据，如工具参数、执行时间等"""


@dataclass
class TodoItem:
    """
    待办任务项

    用于任务规划和分解，支持状态追踪和优先级管理。
    限制同时只能有一个任务处于 in_progress 状态。
    """

    id: str
    """任务唯一标识符"""

    title: str
    """任务标题"""

    intent: str
    """任务意图描述"""

    status: str = "pending"
    """任务状态：pending/in_progress/completed/cancelled"""

    created_at: datetime = field(default_factory=datetime.utcnow)
    """创建时间"""

    updated_at: datetime = field(default_factory=datetime.utcnow)
    """最后更新时间"""


@dataclass
class ToolResult:
    """
    工具执行结果封装

    统一封装各类工具的执行结果，便于链路追踪和错误处理。
    """

    tool_name: str
    """工具名称"""

    output: Any
    """工具输出结果"""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """执行元数据，如耗时、状态码等"""


@dataclass
class ConversationTurn:
    """
    对话轮次记录

    记录用户与助手之间的单轮对话，用于上下文管理和历史追踪。
    """

    role: str
    """角色标识：user/assistant"""

    content: str
    """对话内容文本"""

    created_at: datetime = field(default_factory=datetime.utcnow)
    """对话时间戳"""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """扩展元数据，如 token 数、模型信息等"""