"""子代理路由器：生成 RouterDecision。"""

from __future__ import annotations

import json
from typing import List, Optional

from agent.core.llm import LLMClient, LLMMessage
from agent.core.prompts import SUBAGENT_ROUTER_PROMPT
from agent.core.tracing import LangSmithTracer
from agent.subagents.protocol import RouterDecision, TaskEnvelope, allowed_agent_names
from agent.subagents.function_schemas import subagent_router_schema
from src.utils.logging_manager import logger


class SubAgentRouter:
    """基于 LLM 的路由决策器。"""

    def __init__(
        self,
        llm: LLMClient,
        allowed_agents: Optional[List[str]] = None,
        tracer: Optional[LangSmithTracer] = None,
    ) -> None:
        self.llm = llm
        self.allowed_agents = allowed_agents or allowed_agent_names()
        self.tracer = tracer

    def decide(self, task: TaskEnvelope, root_run=None) -> RouterDecision:
        """根据任务生成 RouterDecision。"""
        allowed_agents = task.constraints.get("tools_allowed") if isinstance(task.constraints, dict) else None
        if not isinstance(allowed_agents, list) or not allowed_agents:
            allowed_agents = self.allowed_agents
        try:
            prompt = SUBAGENT_ROUTER_PROMPT.format(
                agent_list=", ".join(allowed_agents),
                max_turns=4,
            )
        except Exception as exc:
            # 避免提示模板格式错误阻断整条 supervisor 链路
            logger.warning("SubAgentRouter prompt 格式化失败，使用兜底提示: %s", exc)
            prompt = (
                "你是子代理路由器。"
                "仅输出 JSON，字段包含 plan/reason/max_turns。"
                f"可用子代理: {', '.join(allowed_agents)}。"
                "plan 中每一步包含 agent/objective/constraints/expected_output/budget。"
            )
        messages = [
            LLMMessage(role="system", content=prompt),
            LLMMessage(role="user", content=json.dumps(task.to_dict(), ensure_ascii=False)),
        ]
        tools = [subagent_router_schema(allowed_agents)]
        payload = None
        try:
            if self.tracer and self.tracer.enabled and root_run:
                with self.tracer.start_run(
                    name="subagent_router",
                    run_type="llm",
                    inputs={"task": task.to_dict()},
                    tags=["subagent", "router"],
                    metadata={"trace_id": task.trace_id},
                    parent=root_run,
                ) as run:
                    _, payload = self.llm.tool_call(messages, tools=tools, tool_choice="required")
                    run.add_outputs({"payload": payload})
            else:
                _, payload = self.llm.tool_call(messages, tools=tools, tool_choice="required")
            decision = RouterDecision.from_dict(payload)
        except Exception:
            # 解析失败时走安全兜底：默认只调用 rag_docs
            decision = RouterDecision.from_dict(
                {
                    "plan": [
                        {
                            "agent": "rag_docs",
                            "objective": task.objective,
                            "constraints": task.constraints,
                            "expected_output": "文档证据摘要",
                            "budget": task.budget,
                        }
                    ],
                    "reason": "路由解析失败，降级为文档检索",
                    "max_turns": 1,
                }
            )
        # 裁剪为允许的代理集合
        filtered_plan = [step for step in decision.plan if step.agent in allowed_agents]
        if not filtered_plan:
            filtered_plan = decision.plan[:1]
        return RouterDecision(plan=filtered_plan, reason=decision.reason, max_turns=decision.max_turns)
