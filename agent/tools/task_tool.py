from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
import uuid

from agent.core.models import TodoItem
from agent.subagents.protocol import TaskEnvelope, allowed_agent_names
from agent.subagents.supervisor import SubAgentSupervisor, SubAgentExecution


@dataclass
class TaskResult:
    """子代理执行结果。"""

    task: TodoItem
    summary: str
    sources: List[str]


class TaskTool:
    """Task 工具：使用协议化子代理执行子任务。"""

    def __init__(
        self,
        supervisor_factory: Callable[[], SubAgentSupervisor],
        allowed_tables: Optional[List[str]] = None,
        default_budget: Optional[Dict[str, int]] = None,
    ) -> None:
        self.supervisor_factory = supervisor_factory
        self.allowed_tables = allowed_tables or []
        self.default_budget = default_budget or {"max_tokens": 1200, "max_time_ms": 15000}

    def run_task(
        self,
        task: TodoItem,
        trace_id: Optional[str] = None,
        parent_context: Optional[Dict[str, str]] = None,
        root_run=None,
    ) -> TaskResult:
        """执行单个子任务，返回摘要与来源。"""
        supervisor = self.supervisor_factory()
        envelope = self._build_envelope(task, trace_id=trace_id, parent_context=parent_context)
        execution: SubAgentExecution = supervisor.execute(envelope, root_run=root_run)
        return TaskResult(task=task, summary=execution.summary, sources=execution.sources)

    def run_tasks(
        self,
        tasks: List[TodoItem],
        trace_id: Optional[str] = None,
        parent_context: Optional[Dict[str, str]] = None,
        root_run=None,
    ) -> List[TaskResult]:
        return [self.run_task(task, trace_id=trace_id, parent_context=parent_context, root_run=root_run) for task in tasks]

    def _build_envelope(
        self,
        task: TodoItem,
        trace_id: Optional[str],
        parent_context: Optional[Dict[str, str]],
    ) -> TaskEnvelope:
        """将 TodoItem 转为 TaskEnvelope，注入约束与预算。"""
        trace_id = trace_id or str(uuid.uuid4())
        objective = task.title
        if task.intent:
            objective = f"{task.title}\n{task.intent}"
        constraints = {
            "tables": self.allowed_tables,
            "tools_allowed": allowed_agent_names(),
        }
        context = {
            "task_id": task.id,
            "intent": task.intent,
        }
        if parent_context:
            context.update(parent_context)
        return TaskEnvelope(
            objective=objective,
            constraints=constraints,
            context=context,
            expected_output="结构化结果 + 证据摘要",
            budget=dict(self.default_budget),
            trace_id=trace_id,
            task_id=task.id,
        )
