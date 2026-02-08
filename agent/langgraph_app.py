from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import List, Tuple

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, MessagesState, StateGraph

# 确保项目根目录在 sys.path 中，便于导入 agent 包
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from agent.core.config import AgentConfig
from agent.core.models import ConversationTurn
from agent.core.prompts import SYSTEM_PROMPT
from agent.runtime.fusion_agent import FusionAgent


_config = AgentConfig.load()
_fusion_agent = FusionAgent(_config)

# LangChain ChatOpenAI 兼容 DashScope 的 OpenAI 模式，用于 LangGraph 的流式输出
_llm = ChatOpenAI(
    model=_config.dashscope_model,
    api_key=_config.dashscope_api_key,
    base_url=_config.dashscope_base_url,
    temperature=0.2,
    streaming=True,
)


def _content_to_text(content) -> str:
    """将多模态消息内容提取为纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(p for p in parts if p)
    return str(content)


def _extract_user_message(messages: List[BaseMessage]) -> str:
    """提取最后一条人类消息作为当前问题。"""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return _content_to_text(msg.content)
    raise ValueError("未找到用户消息")


def _build_history(messages: List[BaseMessage]) -> List[ConversationTurn]:
    """将历史消息转换为 ConversationTurn 列表。"""
    history: List[ConversationTurn] = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            history.append(ConversationTurn(role="user", content=_content_to_text(msg.content)))
        elif isinstance(msg, AIMessage):
            history.append(ConversationTurn(role="assistant", content=_content_to_text(msg.content)))
    return history


def _agent_node(state: MessagesState) -> MessagesState:
    """LangGraph 节点：基于 FusionAgent 构建上下文并调用 LLM。"""
    messages = state["messages"]
    user_message = _extract_user_message(messages)
    history = _build_history(messages[:-1])
    context, _sources, _question_type = _fusion_agent._prepare_context(
        user_message,
        history,
        None,
        str(uuid.uuid4()),
    )

    response = _llm.invoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=context),
        ]
    )
    # 写入记忆，保持与原流程一致
    _fusion_agent._write_final_answer(user_message, response.content, None)
    return {"messages": [response]}


def build_graph():
    """构建 LangGraph 图。"""
    workflow = StateGraph(MessagesState)
    workflow.add_node("agent", _agent_node)
    workflow.set_entry_point("agent")
    workflow.add_edge("agent", END)
    return workflow.compile()


graph = build_graph()
