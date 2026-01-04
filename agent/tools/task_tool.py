from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

from agent.models import TodoItem


@dataclass
class TaskResult:
    """子代理执行结果。"""

    task: TodoItem
    summary: str
    sources: List[str]


class TaskTool:
    """Task 工具：派生子代理执行子任务。"""

    def __init__(self, agent_factory: Callable[[], "FusionAgent"]) -> None:
        self.agent_factory = agent_factory

    def run_task(self, task: TodoItem) -> TaskResult:
        """创建独立子代理执行任务，避免主上下文污染。"""
        agent = self.agent_factory()
        prompt = f"任务标题：{task.title}\n任务意图：{task.intent}\n请给出结论与证据摘要。"
        response, metadata = agent.respond(prompt, history=[])
        sources = metadata.get("sources", []) if metadata else []
        return TaskResult(task=task, summary=response, sources=sources)

    def run_tasks(self, tasks: List[TodoItem]) -> List[TaskResult]:
        return [self.run_task(task) for task in tasks]
