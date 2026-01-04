from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from agent.models import MemoryItem


class BaseMemory(ABC):
    """记忆接口定义。"""

    @abstractmethod
    def add(self, item: MemoryItem) -> None:
        """写入记忆。"""

    @abstractmethod
    def search(self, query: str, top_k: int = 5) -> List[MemoryItem]:
        """检索记忆。"""
