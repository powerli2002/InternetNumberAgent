"""LangGraph 主编排器（运行时总控）。

调度流程（主图）：
1. plan：探测当前可用工具并调用 LLM 生成可执行计划（步骤、依赖、工具、参数、重规划预算）。
2. validate_plan：规范化计划，修复重复 step_id、不可用工具与非法依赖。
3. dispatch <-> execute_ready：按依赖关系挑选 ready 步骤，并发执行直到 pending 清空。
4. collect_memory_notes：补充工作记忆/情景记忆/笔记检索结果。
5. conflict_check：基于步骤结果做冲突判定，必要时触发 replan 回到 plan。
6. build_context：融合系统提示词、历史、证据、记忆、笔记为最终回答上下文。
7. generate_answer：LLM 生成最终可读答案。
8. write_memory：写入工作记忆并按配置抽取语义记忆。

整体架构：
- 状态层：`AgentGraphState`（TypedDict）是整张图的单一状态载体。
- 编排层：LangGraph `StateGraph` 负责节点注册、边连接与条件分支路由。
- 执行层：MCP 工具（NL2SQL/RAG/Neo4j-LlamaIndex/Note）提供外部能力，支持并发步骤执行。
- 记忆层：Working/Episodic/Semantic 三层记忆由 `MemoryManager` 统一管理。
- 观测层：LangSmith 自动追踪（root run + 自动节点/LLM/tool run）并在 root 输出聚合节点审计记录。

LangGraph 思想与语法（本文件用法）：
- `StateGraph(StateType)`：声明“共享状态 + 节点函数”的图执行模型。
- `add_node(name, fn)`：注册状态变换节点；`fn(state) -> partial_state_update`。
- `add_edge(a, b)`：声明固定顺序边。
- `add_conditional_edges(a, router, mapping)`：router 返回键，映射到不同后继节点。
- `END`：图结束哨兵；`compile()` 产出可运行图；`invoke(init_state)` 同步执行整图。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
import contextvars
import hashlib
import json
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

from langsmith.run_helpers import get_current_run_tree, tracing_context
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from agent.core.config import AgentConfig
from agent.core.llm import LLMClient, LLMMessage
from agent.core.models import ConversationTurn, EvidenceItem, MemoryItem
from agent.core.prompts import (
    GRAPH_CYPHER_PROMPT,
    LANGGRAPH_CONFLICT_PROMPT,
    LANGGRAPH_PLAN_PROMPT,
    SEMANTIC_EXTRACT_PROMPT,
    SYSTEM_PROMPT,
)
from agent.core.tracing import LangSmithTracer
from agent.memory import EpisodicMemory, MemoryManager, SemanticMemory, WorkingMemory
from agent.memory.semantic import SemanticRecord
from agent.runtime.context_builder import ContextBuilder
from agent.runtime.graph_models import GraphPlan, GraphPlanStep
from agent.runtime.graph_schemas import build_conflict_schema, build_main_plan_schema
from agent.services.mcp.client import MCPToolClient
from fusiondata.src.utils.logging_manager import logger


_ROOT_RUN_CTX: contextvars.ContextVar[Any] = contextvars.ContextVar("langgraph_root_run", default=None)
_NODE_RECORDS_CTX: contextvars.ContextVar[Optional[List[Dict[str, Any]]]] = contextvars.ContextVar(
    "langgraph_node_records",
    default=None,
)


class AgentGraphState(TypedDict, total=False):
    """LangGraph 状态。"""

    query: str
    history: List[ConversationTurn]
    trace_id: str
    available_tools: Dict[str, bool]
    plan_steps: List[Dict[str, Any]]
    plan_reason: str
    max_replans: int
    replan_count: int
    pending_ids: List[str]
    completed_ids: List[str]
    ready_ids: List[str]
    step_results: Dict[str, Dict[str, Any]]
    evidences: List[EvidenceItem]
    sources: List[str]
    memories: List[MemoryItem]
    notes: List[str]
    conflicts: List[str]
    need_replan: bool
    context: str
    answer: str
    metadata: Dict[str, Any]
    error: str


def _truncate(text: str, limit: int = 1000) -> str:
    """对任意文本做长度截断，避免追踪/提示词被超长内容污染。

    Args:
        text: 待处理文本，允许为任意可字符串化对象。
        limit: 最大保留字符数，超过时追加截断标记。

    Returns:
        截断后的字符串；若原文本较短则原样返回。
    """
    # 统一截断长文本，避免把超长内容直接写入追踪或提示词上下文。
    if text is None:
        return ""
    raw = str(text)
    if len(raw) <= limit:
        return raw
    return f"{raw[:limit]}...<truncated {len(raw)} chars>"


def _trace_json(value: Any, limit: int = 6000) -> str:
    """将任意对象转为可追踪 JSON 字符串，并在超长时截断。"""
    try:
        raw = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        raw = str(value)
    return _truncate(raw, limit=limit)


def _to_jsonable(value: Any) -> Any:
    """把任意对象尽量转换为 JSON 可序列化结构。"""
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return str(value)


def _serialize_evidence_items(evidences: List[Any], max_items: int = 30) -> List[Dict[str, Any]]:
    """序列化证据列表，供 trace 与评测链路持久化。"""
    serialized: List[Dict[str, Any]] = []
    for evidence in evidences[: max(0, int(max_items))]:
        if isinstance(evidence, EvidenceItem):
            title = str(evidence.title or "")
            source = str(evidence.source or "")
            content = str(evidence.content or "")
            score = float(evidence.score)
            metadata = _to_jsonable(evidence.metadata or {})
        elif isinstance(evidence, dict):
            title = str(evidence.get("title") or "")
            source = str(evidence.get("source") or "")
            content = str(evidence.get("content") or "")
            score = float(evidence.get("score") or 0.0)
            metadata = _to_jsonable(evidence.get("metadata") or {})
        else:
            title = ""
            source = ""
            content = str(evidence or "")
            score = 0.0
            metadata = {}
        serialized.append(
            {
                "title": _truncate(title, 200),
                "source": _truncate(source, 60),
                "content": _truncate(content, 2000),
                "score": score,
                "metadata": metadata,
            }
        )
    return serialized


def _trace_state_snapshot(state: AgentGraphState) -> Dict[str, Any]:
    """抽取状态快照，作为节点输入记录写入 root run。"""
    pending = [str(item) for item in (state.get("pending_ids") or [])[:20]]
    completed = [str(item) for item in (state.get("completed_ids") or [])[:20]]
    ready = [str(item) for item in (state.get("ready_ids") or [])[:20]]
    return {
        "trace_id": str(state.get("trace_id") or ""),
        "query": _truncate(str(state.get("query") or ""), 300),
        "pending_ids": pending,
        "completed_ids": completed,
        "ready_ids": ready,
        "plan_steps_size": len(state.get("plan_steps") or []),
        "sources_size": len(state.get("sources") or []),
        "conflicts_size": len(state.get("conflicts") or []),
        "replan_count": int(state.get("replan_count", 0)),
    }


def _extract_json(text: str) -> Dict[str, Any]:
    """从模型自由文本输出中提取第一个完整 JSON 对象。

    该函数用于兼容 LLM 常见输出形态：纯 JSON、Markdown 代码块、以及
    “解释文字 + JSON 片段”的混合文本。

    Args:
        text: 模型返回文本。

    Returns:
        解析后的 JSON 字典对象。

    Raises:
        ValueError: 未检测到可解析 JSON 对象，或输入为空。
        json.JSONDecodeError: 检测到 JSON 边界但内容不合法。
    """
    if not text:
        raise ValueError("模型输出为空，无法解析 JSON")
    raw = text.strip()
    # 兼容 ```json ... ``` 代码块格式。
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("模型输出不包含 JSON 对象")
    return json.loads(raw[start : end + 1])


class LangGraphOrchestrator:
    """LangGraph 主编排器。"""

    def __init__(self, config: Optional[AgentConfig] = None) -> None:
        """初始化编排器依赖，并编译主图。

        Args:
            config: 可选配置对象；为空时从默认配置源加载。
        """
        # 读取运行配置：统一管理模型、数据库、图谱、工具服务等参数。
        self.config = config or AgentConfig.load()
        # 追踪器用于记录整条链路与各节点的输入输出，便于定位问题。
        self.tracer = LangSmithTracer()
        # 主 LLM 客户端：承担计划生成、冲突判断、答案生成、Cypher 生成等任务。
        self.llm = LLMClient(
            api_key=self.config.dashscope_api_key,
            base_url=self.config.dashscope_base_url,
            model=self.config.dashscope_model,
        )
        # 上下文构建器负责把多源证据压缩到 token 预算内。
        self.context_builder = ContextBuilder(
            max_tokens=self.config.max_context_tokens,
            llm_client=self.llm,
            compress_mode=self.config.context_compress_mode,
            compress_target_ratio=self.config.context_compress_target_ratio,
        )
        # 统一记忆管理器：工作记忆 + 情景记忆 + 语义记忆。
        self.memory_manager = MemoryManager(
            working_memory=WorkingMemory(capacity=self.config.working_memory_size), # 纯标量
            episodic_memory=EpisodicMemory(
                sqlite_path=self.config.memory_store_dir / "episodic.sqlite",
                capacity=self.config.episodic_memory_size,
                postgres_url=self.config.postgres_url,
            ),
            semantic_memory=SemanticMemory(
                uri=self.config.neo4j_uri,
                user=self.config.neo4j_user,
                password=self.config.neo4j_password,
            ),
        )
        # MCP 客户端：统一访问 nl2sql/rag/neo4j/note 等工具端点。
        self.mcp_client = MCPToolClient(
            server_url=self.config.mcp_server_url,
            timeout_seconds=self.config.mcp_timeout_seconds,
            tracer=self.tracer,
        )
        # 启动时一次性编译执行图，后续复用同一图实例。
        self.graph = self._build_graph()

    def respond(self, user_message: str, history: Optional[List[ConversationTurn]] = None) -> Tuple[str, Dict[str, Any]]:
        """执行完整 LangGraph 主流程并返回最终答案。

        执行顺序为：规划 -> 计划校验 -> 调度执行 -> 记忆补充 ->
        冲突检查 -> 上下文构建 -> 答案生成 -> 记忆写回。

        Args:
            user_message: 用户当前输入问题。
            history: 可选多轮对话历史，按时间顺序传入。

        Returns:
            二元组 `(answer, metadata)`：
            - answer: 最终自然语言回答。
            - metadata: 追踪与可解释字段（来源、冲突、重规划次数等）。
        """
        history = history or []
        trace_id = str(uuid.uuid4())
        # LangGraph 的初始状态：后续每个节点只返回“增量字段”，由图引擎合并到该状态。
        init_state: AgentGraphState = {
            "query": user_message,
            "history": history,
            "trace_id": trace_id,
            "plan_steps": [],
            "plan_reason": "",
            "max_replans": 1,
            "replan_count": 0,
            "pending_ids": [],
            "completed_ids": [],
            "ready_ids": [],
            "step_results": {},
            "evidences": [],
            "sources": [],
            "memories": [],
            "notes": [],
            "conflicts": [],
            "need_replan": False,
            "context": "",
            "answer": "",
            "metadata": {},
            "error": "",
        }
        main_flow_trace: Dict[str, Any] = {
            "stage": "main_flow_start",
            "init_state_snapshot": _trace_state_snapshot(init_state),
            "history_size": len(history),
        }

        # 根追踪 run：将整次问答链路绑定到同一个 trace 上，便于跨节点观测。
        root_ctx = (
            self.tracer.start_run(
                name="langgraph_agent",
                run_type="chain",
                inputs={"question": user_message},
                tags=["fusion", "langgraph", "qa"],
                metadata={"trace_id": trace_id},
            )
            if self.tracer.enabled
            else nullcontext()
        )

        with root_ctx as run:
            # 把根 run 放入 ContextVar，子节点/子线程可显式透传父 run 形成树状追踪。
            token = _ROOT_RUN_CTX.set(run if run else None)
            node_records: List[Dict[str, Any]] = []
            node_token = _NODE_RECORDS_CTX.set(node_records)
            auto_trace_ctx = (
                tracing_context(
                    parent=run,
                    project_name=self.tracer.project_name,
                    client=self.tracer.client,
                    metadata={"trace_id": trace_id},
                )
                if self.tracer.enabled and run and hasattr(run, "id")
                else tracing_context(enabled=False)
                if self.tracer.enabled
                else nullcontext()
            )
            try:
                # LangGraph 核心入口：从 init_state 出发执行至 END，得到最终状态快照。
                with auto_trace_ctx:
                    final_state = self.graph.invoke(init_state)
            finally:
                _NODE_RECORDS_CTX.reset(node_token)
                _ROOT_RUN_CTX.reset(token)

            answer = str(final_state.get("answer") or "")
            evidences = list(final_state.get("evidences") or [])
            evidence_items = _serialize_evidence_items(evidences)
            evidence_sources = list(
                dict.fromkeys(item.get("source", "") for item in evidence_items if str(item.get("source", "")).strip())
            )
            metadata = {
                # 对 sources 去重并保序，避免重复来源污染前端展示。
                "sources": list(dict.fromkeys(final_state.get("sources") or [])),
                "trace_id": trace_id,
                "plan_reason": final_state.get("plan_reason", ""),
                "conflicts": final_state.get("conflicts", []),
                "replan_count": final_state.get("replan_count", 0),
                "evidence_count": len(evidences),
                "evidence_sources": evidence_sources,
            }
            final_state_output = {
                "plan_steps_size": len(final_state.get("plan_steps") or []),
                "completed_ids": [str(item) for item in (final_state.get("completed_ids") or [])[:30]],
                "pending_ids": [str(item) for item in (final_state.get("pending_ids") or [])[:30]],
                "conflicts": [str(item) for item in (final_state.get("conflicts") or [])[:20]],
                "step_results": _trace_json(final_state.get("step_results") or {}, limit=6000),
                "evidence_count": len(evidences),
                "evidence_sources": evidence_sources,
                "evidence_items": evidence_items,
                "context_preview": _truncate(str(final_state.get("context") or ""), 1200),
                "answer_preview": _truncate(answer, 1200),
                "error": _truncate(str(final_state.get("error") or ""), 800),
            }
            main_flow_trace["final_state_snapshot"] = _trace_state_snapshot(final_state)
            main_flow_trace["final_answer_preview"] = _truncate(answer, 1200)
            if run:
                run.add_outputs(
                    {
                        "answer": answer,
                        "metadata": metadata,
                        "trace_version": "single_trace_auto_v1",
                        "node_records": node_records,
                        "final_state_output": final_state_output,
                        "main_flow_trace": main_flow_trace,
                    }
                )
            return answer, metadata

    def stream_response(
        self,
        user_message: str,
        history: Optional[List[ConversationTurn]] = None,
    ) -> Tuple[Iterable[str], Dict[str, Any]]:
        """提供兼容流式消费的回答接口。

        当前实现是“先全量生成，再分块输出”的伪流式模式，优点是实现简单、
        与现有 `respond` 流程保持一致；缺点是不具备真正 token 级实时性。

        Args:
            user_message: 用户当前输入问题。
            history: 可选历史对话。

        Returns:
            二元组 `(iterable_chunks, metadata)`。
        """
        # 当前实现是“伪流式”：先拿完整答案，再切分为小块向上游发送。
        answer, metadata = self.respond(user_message, history=history)

        def _iter() -> Iterable[str]:
            """按固定分片大小迭代返回答案文本。"""
            if not answer:
                yield ""
                return
            # 固定块大小，便于前端按片段渲染。
            chunk_size = 32
            for idx in range(0, len(answer), chunk_size):
                yield answer[idx : idx + chunk_size]

        return _iter(), metadata

    def _build_graph(self):
        """构建并编译 LangGraph 主执行图。

        图结构采用“固定边 + 条件边”组合：
        - 固定边保证主干流程顺序执行；
        - 条件边负责调度循环（dispatch-execute）与冲突重规划分支。

        Returns:
            编译后的 LangGraph 可执行对象（支持 `invoke`）。
        """
        # 语法要点：StateGraph(状态类型) 声明图；每个节点都是状态到“局部更新”的函数。
        workflow = StateGraph(AgentGraphState)
        # add_node(name, fn)：注册节点；name 供边和路由器引用。
        workflow.add_node("plan", self._plan_node)
        workflow.add_node("validate_plan", self._validate_plan_node)
        workflow.add_node("dispatch", self._dispatch_node)
        workflow.add_node("execute_ready", self._execute_ready_node)
        workflow.add_node("collect_memory_notes", self._collect_memory_and_notes_node)
        workflow.add_node("conflict_check", self._conflict_check_node)
        workflow.add_node("build_context", self._build_context_node)
        workflow.add_node("generate_answer", self._generate_answer_node)
        workflow.add_node("write_memory", self._write_memory_node)

        # set_entry_point：设定图入口节点。
        workflow.set_entry_point("plan")
        # add_edge(a, b)：固定流转边，按顺序推进。
        workflow.add_edge("plan", "validate_plan")
        workflow.add_edge("validate_plan", "dispatch")
        # add_conditional_edges：router 返回键，再按 mapping 选择后继节点。
        workflow.add_conditional_edges(
            "dispatch",
            self._after_dispatch,
            {
                "execute_ready": "execute_ready",
                "collect_memory_notes": "collect_memory_notes",
            },
        )
        # 执行一批 ready 步骤后回到 dispatch，形成“直到 pending 清空”的循环。
        workflow.add_edge("execute_ready", "dispatch")
        workflow.add_edge("collect_memory_notes", "conflict_check")
        workflow.add_conditional_edges(
            "conflict_check",
            self._after_conflict_check,
            {
                "plan": "plan",
                "build_context": "build_context",
            },
        )
        workflow.add_edge("build_context", "generate_answer")
        workflow.add_edge("generate_answer", "write_memory")
        # END 是 LangGraph 的结束哨兵。
        workflow.add_edge("write_memory", END)
        # compile() 把声明式图结构编译成可 invoke 的运行时对象。
        return workflow.compile()

    @staticmethod
    def _after_dispatch(state: AgentGraphState) -> str:
        """dispatch 后的条件路由。

        Args:
            state: 当前图状态。

        Returns:
            - `"execute_ready"`: 仍有待执行步骤，继续进入执行节点。
            - `"collect_memory_notes"`: 计划步骤已全部执行完成。
        """
        # 条件路由函数：只要还有 pending 就继续执行工具步骤，否则进入记忆/笔记补充。
        pending = state.get("pending_ids") or []
        if pending:
            return "execute_ready"
        return "collect_memory_notes"

    @staticmethod
    def _after_conflict_check(state: AgentGraphState) -> str:
        """冲突检查后的条件路由。

        Args:
            state: 当前图状态。

        Returns:
            - `"plan"`: 需要重规划。
            - `"build_context"`: 可以进入回答生成阶段。
        """
        # 冲突检测后，若需重规划则回到 plan 节点，否则进入上下文构建与答案生成。
        if state.get("need_replan"):
            return "plan"
        return "build_context"

    def _trace_node(self, name: str, state: AgentGraphState, fn):
        """统一包装节点执行，记录节点输入输出到 root run 聚合字段。

        Args:
            name: 节点名称，用于追踪标记。
            state: 进入节点时的全局状态快照。
            fn: 具体节点执行函数，应返回局部状态更新字典。

        Returns:
            节点局部更新字典，供 LangGraph 合并到全局状态。
        """
        node_records = _NODE_RECORDS_CTX.get()
        started_at = time.time()
        started_perf = time.perf_counter()
        current_run = get_current_run_tree()
        try:
            # fn 返回“局部状态更新字典”，由 LangGraph 自动与全局状态合并。
            output = fn()
            trace_extras: Dict[str, Any] = {}
            if isinstance(output, dict):
                # 允许节点返回仅用于追踪的字段，避免污染全局状态。
                raw_trace_extras = output.pop("_trace_outputs", None)
                if isinstance(raw_trace_extras, dict):
                    trace_extras = raw_trace_extras
            prompt_records_raw = trace_extras.pop("prompt_records", [])
            prompt_records = prompt_records_raw if isinstance(prompt_records_raw, list) else []
            record = {
                "node_name": name,
                "status": "ok",
                "started_at": started_at,
                "ended_at": time.time(),
                "duration_ms": int((time.perf_counter() - started_perf) * 1000),
                "input_snapshot": _trace_state_snapshot(state),
                "output_summary": {
                    "keys": sorted(output.keys()) if isinstance(output, dict) else [],
                    "pending_size": len(output.get("pending_ids", state.get("pending_ids", [])))
                    if isinstance(output, dict)
                    else 0,
                    "completed_size": len(output.get("completed_ids", state.get("completed_ids", [])))
                    if isinstance(output, dict)
                    else 0,
                    "need_replan": bool(output.get("need_replan", state.get("need_replan", False)))
                    if isinstance(output, dict)
                    else False,
                    "sources_size": len(output.get("sources", state.get("sources", []))) if isinstance(output, dict) else 0,
                },
                "prompt_records": prompt_records,
                "final_output": _trace_json(output, limit=10000),
            }
            if trace_extras:
                record["trace_extras"] = trace_extras
            if isinstance(node_records, list):
                node_records.append(record)
            if current_run is not None:
                try:
                    # 同步写入当前 LangGraph 自动节点 run，便于在单节点详情页直接排障。
                    current_run.add_outputs(
                        {
                            "node_audit": {
                                "node_name": name,
                                "input_snapshot": record["input_snapshot"],
                                "output_summary": record["output_summary"],
                                "prompt_records": prompt_records,
                                "trace_extras": trace_extras,
                            }
                        }
                    )
                except Exception as trace_exc:
                    logger.debug("节点追踪输出写入失败 node=%s error=%s", name, trace_exc)
            return output
        except Exception as exc:
            if isinstance(node_records, list):
                node_records.append(
                    {
                        "node_name": name,
                        "status": "error",
                        "started_at": started_at,
                        "ended_at": time.time(),
                        "duration_ms": int((time.perf_counter() - started_perf) * 1000),
                        "input_snapshot": _trace_state_snapshot(state),
                        "output_summary": {"keys": [], "pending_size": 0, "completed_size": 0, "need_replan": False, "sources_size": 0},
                        "prompt_records": [],
                        "final_output": "",
                        "error": str(exc),
                    }
                )
            if current_run is not None:
                try:
                    current_run.add_outputs(
                        {
                            "node_audit": {
                                "node_name": name,
                                "status": "error",
                                "error": str(exc),
                                "input_snapshot": _trace_state_snapshot(state),
                            }
                        }
                    )
                except Exception as trace_exc:
                    logger.debug("节点异常追踪输出写入失败 node=%s error=%s", name, trace_exc)
            raise

    def _plan_node(self, state: AgentGraphState) -> Dict[str, Any]:
        """`plan` 节点：生成主计划并初始化调度状态。

        计划采用结构化输出（GraphPlan），并携带依赖关系与工具参数。
        该节点会在每轮规划前动态探测可用工具，避免计划引用不可用能力。
        若模型规划失败，则降级到单步保底计划，保证流程可继续。

        Args:
            state: 当前图状态。

        Returns:
            局部更新：`plan_steps`、`plan_reason`、`pending_ids` 等。
        """
        def _impl() -> Dict[str, Any]:
            """节点内部实现：调用 LLM 生成计划并做基础容错。"""
            query = str(state.get("query") or "")
            trace_id = str(state.get("trace_id") or "")
            trace_outputs: Dict[str, Any] = {}
            # 重规划时将上一轮计划、步骤结果摘要及彻底失败的工具列表传给 planner。
            previous_plan_steps, previous_step_summaries, permanently_failed_tools = self._build_previous_plan_payload(state)
            # 每轮规划前重新探测工具可用性，适配 MCP 工具热插拔与重规划场景。
            available_tools = self._resolve_available_tools(trace_id)
            # 仅把“当前可用工具”暴露给规划模型，降低无效计划概率。
            allowed = [
                tool
                for tool in ("nl2sql", "rag", "graph", "none")
                if available_tools.get(tool, False)
            ]
            if not allowed:
                allowed = ["none"]

            payload = {
                "query": query,
                "available_tools": allowed,
                "allowed_tables": self.config.allowed_tables,
                "max_rows": self.config.nl2sql_max_rows,
                "history_tail": [
                    {"role": turn.role, "content": _truncate(turn.content, 200)}
                    for turn in (state.get("history") or [])[-4:]
                ],
                "replan_count": int(state.get("replan_count", 0)),
                "previous_conflicts": state.get("conflicts", []),
                "previous_plan_steps": previous_plan_steps,
                "previous_step_summaries": previous_step_summaries,
                "permanently_failed_tools": permanently_failed_tools,
            }
            # 使用结构化 tool_call + schema，强约束计划输出字段。
            messages = [
                LLMMessage(role="system", content=LANGGRAPH_PLAN_PROMPT),
                LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
            ]
            schema = build_main_plan_schema(allowed)
            prompt_records: List[Dict[str, Any]] = [
                {
                    "stage": "plan_request",
                    "system_prompt": _truncate(LANGGRAPH_PLAN_PROMPT, 2000),
                    "user_payload": _trace_json(payload, limit=5000),
                    "tool_schema": _trace_json(schema, limit=5000),
                }
            ]
            try:
                # 调用 LLM 生成计划，返回结果是 result_payload
                _, result_payload = self.llm.tool_call(messages, tools=[schema], tool_choice="required")
                prompt_records.append(
                    {
                        "stage": "plan_response",
                        "tool_payload": _trace_json(result_payload, limit=5000),
                    }
                )
                # 兼容：部分 API 将 tool arguments 双重编码为字符串，一次 json.loads 后仍为 str。
                if isinstance(result_payload, str):
                    try:
                        result_payload = json.loads(result_payload)
                    except json.JSONDecodeError as e:
                        trace_outputs["plan_parse_status"] = "failed"
                        trace_outputs["plan_parse_error"] = f"计划 JSON 二次解析失败: {e}"
                        trace_outputs["plan_result_payload"] = _trace_json(result_payload)
                        raise
                # 把 LLM 的输出结果转换为 GraphPlan 对象
                try:
                    plan = GraphPlan.from_dict(result_payload)
                except Exception as parse_exc:
                    # 记录原始结果与解析错误，便于在 LangSmith 中按字段检索失败样本。
                    trace_outputs["plan_parse_status"] = "failed"
                    trace_outputs["plan_parse_error"] = str(parse_exc)
                    trace_outputs["plan_result_payload"] = _trace_json(result_payload)
                    raise
            except Exception as exc:
                logger.warning(
                    "LangGraph 规划失败，使用兜底计划 type=%s error=%s",
                    type(exc).__name__,
                    exc,
                )
                # 规划失败常见原因：模型未返回 tool_call；tool arguments JSON 解析失败；
                # arguments 双重编码（一次解析后仍为 str）；GraphPlan.from_dict 校验失败（如 steps 为空）。
                # 规划失败时保底生成单步计划，确保流程可继续收敛。
                fallback_tool = "nl2sql" if available_tools.get("nl2sql", False) else "rag"
                plan = GraphPlan(
                    steps=[
                        GraphPlanStep(
                            step_id="step_1",
                            objective=query,
                            tool=fallback_tool,  # type: ignore[arg-type]
                            arguments={"question": query} if fallback_tool == "nl2sql" else {"query": query, "top_k": 5},
                            depends_on=[],
                            can_parallel=False,
                            is_complex=False,
                        )
                    ],
                    reason="规划失败，降级为单步执行",
                    max_replans=1,
                )
            # 清理无效依赖，防止 dispatch 阶段因脏依赖阻塞。
            plan.sanitize_dependencies()
            trace_outputs["prompt_records"] = prompt_records
            trace_outputs["plan_steps_size"] = len(plan.steps)
            trace_outputs["plan_reason"] = plan.reason
            return {
                "available_tools": available_tools,
                "plan_steps": [step.to_dict() for step in plan.steps],
                "plan_reason": plan.reason,
                "max_replans": max(int(state.get("max_replans", 1)), plan.max_replans),
                "pending_ids": [step.step_id for step in plan.steps],
                "completed_ids": [],
                "ready_ids": [],
                "need_replan": False,
                "_trace_outputs": trace_outputs,
            }

        return self._trace_node("plan", state, _impl)

    def _validate_plan_node(self, state: AgentGraphState) -> Dict[str, Any]:
        """`validate_plan` 节点：规范化计划，消除不可执行项。

        处理内容包括：
        1. 过滤非法步骤；
        2. 去重 step_id；
        3. 工具可用性降级（nl2sql/graph -> rag -> none）；
        4. 清洗无效依赖关系。

        Args:
            state: 当前图状态。

        Returns:
            规范化后的计划与调度队列初始化结果。
        """
        def _impl() -> Dict[str, Any]:
            """节点内部实现：把模型计划修正为可调度计划。"""
            raw_steps = state.get("plan_steps") or []
            available_tools = state.get("available_tools") or {}
            normalized: List[GraphPlanStep] = []
            used_ids: set[str] = set()

            for idx, raw in enumerate(raw_steps):
                if not isinstance(raw, dict):
                    continue
                try:
                    # 只处理字典步骤；不是字典就跳过
                    # 把原始字典转换为 GraphPlanStep 对象
                    step = GraphPlanStep.from_dict(raw, idx)
                except Exception:
                    # 转换失败就跳过
                    continue
                if step.step_id in used_ids:
                    # step_id 在状态中作为主键使用，重复会覆盖结果，必须去重。
                    step.step_id = f"{step.step_id}_{idx + 1}"
                used_ids.add(step.step_id)

                # 如果工具不可使用则降级
                if step.tool in {"nl2sql", "rag", "graph"} and not available_tools.get(step.tool, False):
                    # 工具不可用时优先降级到 rag，再降级为 none
                    if available_tools.get("rag", False):
                        step.tool = "rag"
                        step.arguments = {"query": step.objective, "top_k": 5}
                    else:
                        step.tool = "none"
                        step.arguments = {}
                if step.tool == "nl2sql":
                    # query_mode 由规划器给出，这里仅做枚举归一，避免执行层做规则推断。
                    query_mode = LangGraphOrchestrator._normalize_query_mode((step.arguments or {}).get("query_mode"))
                    step.arguments["query_mode"] = query_mode
                normalized.append(step)

            if not normalized:
                # 计划全失效时生成 no-op 保底步骤，避免主图崩溃。
                fallback = GraphPlanStep(
                    step_id="step_1",
                    objective=str(state.get("query") or ""),
                    tool="none",
                    arguments={},
                    depends_on=[],
                    can_parallel=False,
                    is_complex=False,
                )
                normalized = [fallback]

            # 二次清洗依赖，确保 dispatch 的拓扑推进可执行。
            plan = GraphPlan(steps=normalized, reason=str(state.get("plan_reason") or ""), max_replans=int(state.get("max_replans", 1)))
            plan.sanitize_dependencies()

            return {
                "plan_steps": [step.to_dict() for step in plan.steps],
                "pending_ids": [step.step_id for step in plan.steps],
                "completed_ids": [],
                "ready_ids": [],
            }

        return self._trace_node("validate_plan", state, _impl)

    def _dispatch_node(self, state: AgentGraphState) -> Dict[str, Any]:
        """`dispatch` 节点：从“未完成任务”里挑出“现在能做的任务”。
        从 state 里取：pending_ids（未完成步骤）、completed_ids（已完成步骤）、plan_steps（步骤配置，含 depends_on）。
        若 pending 为空，直接返回 ready_ids: []，本轮不执行任何步骤
        算 ready：
            - 用 plan_steps 建 step_map（step_id → 步骤配置）。
            - 对每个 pending 里的 step_id：看其 depends_on 是否全部在 completed 里；是则把该 step_id 加入 ready。
            即：依赖都满足的待办步骤才会进入 ready。

        
        Args:
            state: 当前图状态。
        Returns:
            局部更新：`ready_ids`，以及必要时追加 `conflicts`。
        """
        def _impl() -> Dict[str, Any]:
            """节点内部实现：根据依赖关系，把待执行步骤分成“先做/后做”。

            术语说明（对应本函数变量）：
            - pending：还没做完的步骤（待办列表）。
            - completed：已经做完的步骤。
            - ready：可以立刻执行的步骤（它依赖的前置步骤都已完成）。
            """
            # pending_ids = “还没做”的步骤 ID 列表。
            pending = list(state.get("pending_ids") or [])
            # 没有待办就返回空 ready，表示这一轮无需再执行步骤。
            if not pending:
                return {"ready_ids": []}

            # completed_ids 转成集合，后面判断“某依赖是否完成”会更快。
            completed = set(state.get("completed_ids") or [])
            # 用 step_id 建字典，方便根据步骤 ID 直接取步骤详情。
            step_map = {step.get("step_id"): step for step in (state.get("plan_steps") or []) if isinstance(step, dict)}
            # ready 存放“这一轮可以马上执行”的步骤。
            ready: List[str] = []
            for step_id in pending:
                step = step_map.get(step_id)
                if not step:
                    # 计划里找不到这个 step_id，跳过，避免抛异常中断调度。
                    continue
                # depends_on = 当前步骤依赖的前置步骤列表。
                depends_on = [str(x) for x in (step.get("depends_on") or [])]
                # 只有“所有前置步骤都在 completed 里”，当前步骤才算 ready。
                if all(dep in completed for dep in depends_on):
                    ready.append(step_id)

            conflicts = list(state.get("conflicts") or [])
            if not ready and pending:
                # 正常情况下 pending 里总该有可执行项；若没有，多半是依赖写错或形成环。
                # 为避免系统一直卡住，这里强制推进第一个待办步骤。
                ready = [pending[0]]
                conflicts.append("计划依赖存在环或脏数据，已强制执行首个待执行步骤。")

            # 只返回本节点需要更新的字段，由 LangGraph 与全局状态合并。
            return {"ready_ids": ready, "conflicts": conflicts}

        return self._trace_node("dispatch", state, _impl)

    def _execute_ready_node(self, state: AgentGraphState) -> Dict[str, Any]:
        """`execute_ready` 节点：并发执行 ready 步骤并聚合结果。

        并发粒度为“同一批 ready 步骤”，批次之间仍由调度节点串行推进。

        Args:
            state: 当前图状态。

        Returns:
            局部更新：`step_results`、`evidences`、`sources`、
            `pending_ids`、`completed_ids`。
        """
        def _impl() -> Dict[str, Any]:
            """节点内部实现：线程池并发执行并容错汇总。

            流程简述：
            1. 从 state 取本轮可执行步骤 ready_ids，无则直接返回空更新。
            2. 准备聚合容器（evidences/sources/step_results）与调度队列（pending/completed）。
            3. 在线程池中并发执行各 ready 步骤，单步失败不阻断整批，结果统一回填状态。
            4. 返回合并后的 pending/completed/step_results/evidences/sources，供 dispatch 与后续节点使用。
            """
            # ----- 1. 本轮可执行步骤 -----
            ready_ids = list(state.get("ready_ids") or [])
            if not ready_ids:
                return {}

            # ----- 2. 计划步骤索引与状态聚合容器 -----
            # step_map：step_id -> 步骤配置（tool/objective/arguments），供执行器与 trace 使用。
            step_map = {step.get("step_id"): step for step in (state.get("plan_steps") or []) if isinstance(step, dict)}
            # 证据与来源在节点内累加，冲突检查与回答生成会消费 evidences/sources。
            evidences = list(state.get("evidences") or [])
            sources = list(state.get("sources") or [])
            step_results = dict(state.get("step_results") or {})
            # 本批执行完后：pending 去掉本批 ready，completed 加上本批 step_id。
            pending = [step_id for step_id in (state.get("pending_ids") or []) if step_id not in ready_ids]
            completed = list(state.get("completed_ids") or [])

            # ----- 3. 追踪父 run（供 MCP 子 span 挂载） -----
            # 并行线程不会继承 ContextVar，故在主线程提前取 root_run 并透传到 _execute_single_step。
            # respond() 调用时 _ROOT_RUN_CTX 有值；LangGraph Studio/API 直接 invoke 时无值，
            # 退化为当前节点 run，使 MCP 工具在 LangSmith trace 中显示为 execute_ready 的子 span。
            root_run = _ROOT_RUN_CTX.get() or get_current_run_tree()
            tool_input_records: List[Dict[str, Any]] = []
            tool_output_records: List[Dict[str, Any]] = []
            futures: Dict[Any, str] = {}

            # ----- 4. 线程池并发执行本批 ready 步骤 -----
            max_workers = max(1, min(4, len(ready_ids)))
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                def _run_step_in_context(step_payload: Dict[str, Any], ctx: contextvars.Context):
                    """在线程中恢复父上下文，保证 LangSmith 自动追踪能继承 parent。"""
                    return ctx.run(self._execute_single_step, step_payload, state, root_run)

                for step_id in ready_ids:
                    step = step_map.get(step_id)
                    if not step:
                        continue
                    # 记录本批输入，写入 node 的 trace_outputs（tool_dispatch_inputs）。
                    tool_input_records.append(
                        {
                            "step_id": step_id,
                            "tool": str(step.get("tool") or "none"),
                            "objective": _truncate(str(step.get("objective") or ""), 200),
                            "arguments": step.get("arguments", {}) if isinstance(step.get("arguments"), dict) else {},
                        }
                    )
                    # 复制当前上下文到子线程，再提交；完成顺序不定，用 as_completed 按完成顺序消费。
                    step_ctx = contextvars.copy_context()
                    futures[pool.submit(_run_step_in_context, step, step_ctx)] = step_id

                total = len(futures)
                done = 0
                logger.info("步骤批次开始 total=%s ready_ids=%s", total, ",".join(ready_ids))
                for future in as_completed(futures):
                    step_id = futures[future]
                    done += 1
                    try:
                        result = future.result()
                    except Exception as exc:
                        # 单步骤异常不阻断整批：转为 error 结果并写入一条证据，便于后续冲突/回答节点感知。
                        # 解析 |step_retried=True 后缀（由 _run_graph_step 编码），用于重规划时禁止重复调用。
                        exc_str = str(exc)
                        step_retried = False
                        if "|step_retried=True" in exc_str:
                            step_retried = True
                            exc_str = exc_str.replace("|step_retried=True", "").rstrip("|").strip()
                        elif "|step_retried=False" in exc_str:
                            exc_str = exc_str.replace("|step_retried=False", "").rstrip("|").strip()
                        result = {
                            "step_id": step_id,
                            "status": "error",
                            "error": exc_str,
                            "result": {},
                            "retried": step_retried,
                            "evidences": [
                                EvidenceItem(
                                    title=f"步骤 {step_id} 执行失败",
                                    content=f"错误: {exc_str}",
                                    source="executor",
                                    score=0.1,
                                )
                            ],
                            "sources": ["executor"],
                        }
                    logger.info(
                        "步骤批次进度 done=%s/%s step_id=%s status=%s",
                        done,
                        total,
                        step_id,
                        str(result.get("status", "unknown")),
                    )
                    # 记录本批输出摘要，写入 node 的 trace_outputs（tool_dispatch_outputs）。
                    tool_output_records.append(
                        {
                            "step_id": step_id,
                            "status": str(result.get("status", "unknown")),
                            "tool": str(result.get("tool") or step_map.get(step_id, {}).get("tool") or "none"),
                            "error": _truncate(str(result.get("error") or ""), 300),
                            "result_preview": _trace_json(result.get("result", {}), limit=2000),
                            "evidences_size": len(result.get("evidences") or []),
                            "sources_size": len(result.get("sources") or []),
                        }
                    )

                    # 回填单步结果到主状态：step_results 供去重/重规划，evidences/sources 供冲突检查与上下文构建。
                    step_results[step_id] = {
                        "status": result.get("status", "error"),
                        "result": result.get("result", {}),
                        "error": result.get("error", ""),
                        "tool": str(result.get("tool") or ""),
                        "objective": str(result.get("objective") or ""),
                        "arguments": result.get("arguments", {}) if isinstance(result.get("arguments"), dict) else {},
                        "signature": str(result.get("signature") or ""),
                        "reused_from_step_id": str(result.get("reused_from_step_id") or ""),
                        # retried=True 表示工具内部已经过子图重试仍失败，重规划时应禁止再次使用该工具。
                        "retried": bool(result.get("retried", False)),
                    }
                    completed.append(step_id)
                    evidences.extend(result.get("evidences", []))
                    sources.extend(result.get("sources", []))
                logger.info("步骤批次完成 total=%s", total)

            # ----- 5. 组装节点追踪输出（供 LangSmith 节点详情与 root 聚合） -----
            trace_outputs = {
                "prompt_records": [
                    {"stage": "tool_dispatch_inputs", "ready_ids": ready_ids, "tools": tool_input_records},
                    {
                        "stage": "tool_dispatch_outputs",
                        "results": tool_output_records,
                        "state_after_merge": {
                            "pending_ids": pending[:20],
                            "completed_ids": completed[:20],
                            "step_results_size": len(step_results),
                            "evidences_size": len(evidences),
                            "sources_size": len(sources),
                        },
                    },
                ]
            }

            # ----- 6. 返回局部状态更新（LangGraph 会与全局 state 合并） -----
            # ready_ids 置空表示本批已全部执行完；下一轮由 dispatch 根据 pending/completed 再产出新的 ready_ids。
            return {
                "pending_ids": pending,
                "completed_ids": completed,
                "ready_ids": [],
                "step_results": step_results,
                "evidences": evidences,
                "sources": sources,
                "_trace_outputs": trace_outputs,
            }

        return self._trace_node("execute_ready", state, _impl)

    def _collect_memory_and_notes_node(self, state: AgentGraphState) -> Dict[str, Any]:
        """`collect_memory_notes` 节点：补充回答所需的记忆与笔记证据。

        Args:
            state: 当前图状态。

        Returns:
            局部更新：`memories` 与 `notes`。
        """
        def _impl() -> Dict[str, Any]:
            """节点内部实现：优先本地记忆检索，按能力开关调用 note 工具。"""
            query = str(state.get("query") or "")
            trace_id = str(state.get("trace_id") or "")

            # 统一记忆检索：从工作/情景/语义记忆中取与当前问题最相关的片段。
            memories = self.memory_manager.search(query, top_k=5)
            notes: List[str] = []
            available_tools = state.get("available_tools") or {}
            if available_tools.get("note", False):
                try:
                    payload = self.mcp_client.call_tool(
                        "note_search",
                        {"query": query, "limit": 3, "trace_id": trace_id},
                        trace_id=trace_id,
                        root_run=_ROOT_RUN_CTX.get(),
                    )
                    raw_notes = payload.get("notes", []) if isinstance(payload, dict) else []
                    if isinstance(raw_notes, list):
                        notes = [str(item) for item in raw_notes]
                except Exception as exc:
                    logger.warning("note_search 失败，忽略该节点 error=%s", exc)

            return {
                "memories": memories,
                "notes": notes,
            }

        return self._trace_node("collect_memory_notes", state, _impl)

    def _conflict_check_node(self, state: AgentGraphState) -> Dict[str, Any]:
        """`conflict_check` 节点：检测步骤结果是否冲突并决定是否重规划。

        Args:
            state: 当前图状态。

        Returns:
            局部更新：`conflicts`、`need_replan`、`replan_count`。
        """
        def _impl() -> Dict[str, Any]:
            """节点内部实现：结构化冲突判定 + 重规划预算控制。"""
            step_results = state.get("step_results") or {}
            replan_count = int(state.get("replan_count", 0))
            max_replans = int(state.get("max_replans", 1))
            trace_outputs: Dict[str, Any] = {}

            conflicts = list(state.get("conflicts") or [])
            need_replan = False

            if not step_results:
                # 无证据通常意味着工具层失败或计划不可执行，按预算决定是否重规划。
                conflicts.append("未获得任何工具证据。")
                need_replan = replan_count < max_replans
                return {
                    "conflicts": conflicts,
                    "need_replan": need_replan,
                    "replan_count": replan_count + 1 if need_replan else replan_count,
                    "_trace_outputs": {
                        "prompt_records": [],
                        "verdict": "no_evidence",
                        "conflicts_size": len(conflicts),
                    },
                }

            payload = {
                "query": state.get("query", ""),
                "step_results": step_results,
            }
            messages = [
                LLMMessage(role="system", content=LANGGRAPH_CONFLICT_PROMPT),
                LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
            ]
            schema = build_conflict_schema()
            prompt_records: List[Dict[str, Any]] = [
                {
                    "stage": "conflict_request",
                    "system_prompt": _truncate(LANGGRAPH_CONFLICT_PROMPT, 2000),
                    "user_payload": _trace_json(payload, limit=5000),
                    "tool_schema": _trace_json(schema, limit=5000),
                }
            ]
            verdict = "pass"
            try:
                # 结构化冲突判定：模型只返回 verdict/conflicts，便于程序分支处理。
                _, model_payload = self.llm.tool_call(messages, tools=[schema], tool_choice="required")
                verdict = str(model_payload.get("verdict") or "unknown").strip().lower()
                model_conflicts = model_payload.get("conflicts") if isinstance(model_payload.get("conflicts"), list) else []
                conflicts.extend([str(item) for item in model_conflicts if str(item).strip()])
                prompt_records.append(
                    {
                        "stage": "conflict_response",
                        "tool_payload": _trace_json(model_payload, limit=5000),
                    }
                )
            except Exception as exc:
                logger.warning("冲突核验失败，按 unknown 处理 error=%s", exc)
                verdict = "unknown"
                prompt_records.append({"stage": "conflict_response", "error": str(exc)})

            if verdict == "conflict" and replan_count < max_replans:
                # 仅在预算内触发 replan，避免无限循环。
                need_replan = True

            trace_outputs["prompt_records"] = prompt_records
            trace_outputs["verdict"] = verdict
            trace_outputs["conflicts_size"] = len(conflicts)
            return {
                "conflicts": conflicts,
                "need_replan": need_replan,
                "replan_count": replan_count + 1 if need_replan else replan_count,
                "_trace_outputs": trace_outputs,
            }

        return self._trace_node("conflict_check", state, _impl)

    def _build_context_node(self, state: AgentGraphState) -> Dict[str, Any]:
        """`build_context` 节点：聚合多源信息构建最终回答上下文。

        Args:
            state: 当前图状态。

        Returns:
            局部更新：`context`（用于最终答案生成）。
        """
        def _impl() -> Dict[str, Any]:
            """节点内部实现：调用 ContextBuilder 做上下文拼装与裁剪。"""
            # ContextBuilder 负责把“系统提示词 + 证据 + 记忆 + 历史”压缩为单轮上下文。
            context, trace_payload = self.context_builder.build_with_trace(
                system_prompt=SYSTEM_PROMPT,
                user_query=str(state.get("query") or ""),
                history=list(state.get("history") or []),
                memories=list(state.get("memories") or []),
                evidences=list(state.get("evidences") or []),
                notes=list(state.get("notes") or []),
            )
            context_before = str(trace_payload.get("context_before_compress") or "")
            context_after = str(trace_payload.get("context_after_compress") or context)
            trace_payload.pop("context_before_compress", None)
            trace_payload.pop("context_after_compress", None)
            return {
                "context": context,
                "_trace_outputs": {
                    "prompt_records": [
                        {
                            "stage": "context_before_compress",
                            "context_preview": _truncate(context_before, 5000),
                            "token_estimate": trace_payload.get("token_stats", {}).get("before_compress"),
                        },
                        {
                            "stage": "context_after_compress",
                            "context_preview": _truncate(context_after, 5000),
                            "token_estimate": trace_payload.get("token_stats", {}).get("after_compress"),
                        },
                    ],
                    "context_build_stats": trace_payload,
                },
            }

        return self._trace_node("build_context", state, _impl)

    def _generate_answer_node(self, state: AgentGraphState) -> Dict[str, Any]:
        """`generate_answer` 节点：基于上下文生成最终自然语言答案。

        Args:
            state: 当前图状态。

        Returns:
            局部更新：`answer`。
        """
        def _impl() -> Dict[str, Any]:
            """节点内部实现：以系统提示词 + 上下文调用 LLM 对话接口。"""
            context = str(state.get("context") or "")
            # 生成节点只消费 build_context 的产物，避免直接依赖中间执行细节。
            messages = [
                LLMMessage(role="system", content=SYSTEM_PROMPT),
                LLMMessage(role="user", content=context),
            ]
            answer = self.llm.chat(messages)
            return {
                "answer": answer,
                "_trace_outputs": {
                    "prompt_records": [
                        {
                            "stage": "generate_answer_request",
                            "system_prompt": _truncate(SYSTEM_PROMPT, 2000),
                            "user_context": _truncate(context, 5000),
                        },
                        {
                            "stage": "generate_answer_response",
                            "answer_preview": _truncate(answer, 2000),
                        },
                    ]
                },
            }

        return self._trace_node("generate_answer", state, _impl)

    def _write_memory_node(self, state: AgentGraphState) -> Dict[str, Any]:
        """`write_memory` 节点：写入工作记忆并触发可选语义记忆抽取。

        Args:
            state: 当前图状态。

        Returns:
            空更新字典；该节点副作用是持久化记忆。
        """
        def _impl() -> Dict[str, Any]:
            """节点内部实现：将问答摘要写入记忆系统。"""
            question = str(state.get("query") or "")
            answer = str(state.get("answer") or "")
            # 问答闭环：先写工作记忆，再按阈值抽取语义记忆。
            self.memory_manager.add_memory(
                MemoryItem(
                    content=f"用户问题：{question}\n回答：{answer}",
                    memory_type="working",
                    metadata={"source": "chat"},
                )
            )
            self._maybe_write_semantic_memory(question, answer)
            return {}

        return self._trace_node("write_memory", state, _impl)

    def _execute_single_step(
        self,
        step: Dict[str, Any],
        state: AgentGraphState,
        root_run: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """执行单个计划步骤并路由到对应工具执行器。

        Args:
            step: 单个计划步骤（来自 `plan_steps`）。
            state: 当前图状态，用于读取 `trace_id` 与工具能力上下文。
            root_run: 可选根追踪对象，用于跨线程保持追踪父子关系。

        Returns:
            标准化步骤结果，包含 `status/result/evidences/sources` 字段。
        """
        step_id = str(step.get("step_id") or "")
        objective = str(step.get("objective") or "").strip()
        tool = str(step.get("tool") or "none").strip().lower()
        arguments = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
        signature = LangGraphOrchestrator._build_step_signature(tool, objective, arguments)
        trace_id = str(state.get("trace_id") or "")
        started_at = time.monotonic()
        logger.info(
            "步骤开始 step_id=%s tool=%s objective=%s",
            step_id or "-",
            tool,
            _truncate(objective, 120),
        )
        # 复用历史同签名步骤结果，避免重规划后重复访问同一工具。
        reused = LangGraphOrchestrator._find_reusable_step_result(state, signature, step_id)
        if reused is not None:
            reused_from_step_id, reused_entry = reused
            reused_result = reused_entry.get("result", {})
            logger.info(
                "步骤复用 step_id=%s reused_from=%s signature=%s",
                step_id or "-",
                reused_from_step_id,
                signature,
            )
            evidence = EvidenceItem(
                title="步骤结果复用",
                content=(
                    f"复用来源步骤: {reused_from_step_id}\n"
                    f"签名: {signature}\n"
                    f"结果摘要: {_truncate(str(reused_result), 1500)}"
                ),
                source="reuse",
                score=1.0,
                metadata={
                    "step_id": step_id,
                    "reused_from_step_id": reused_from_step_id,
                    "signature": signature,
                },
            )
            return {
                "step_id": step_id,
                "status": "ok",
                "result": reused_result,
                "evidences": [evidence],
                "sources": ["reuse"],
                "error": "",
                "tool": tool,
                "objective": objective,
                "arguments": arguments,
                "signature": signature,
                "reused_from_step_id": reused_from_step_id,
            }
        try:
            # 工具分发器：根据 step.tool 路由到不同执行器。
            if tool == "nl2sql":
                result = self._run_nl2sql_step(step_id, objective, arguments, trace_id, root_run=root_run)
            elif tool == "rag":
                result = self._run_rag_step(step_id, objective, arguments, trace_id, root_run=root_run)
            elif tool == "graph":
                result = self._run_graph_step(step_id, objective, arguments, trace_id, root_run=root_run)
            else:
                result = {
                    "step_id": step_id,
                    "status": "ok",
                    "result": {"tool": "none", "message": "步骤无需工具执行"},
                    "evidences": [],
                    "sources": [],
                }
            # 统一回填步骤元信息，供后续重规划与去重复用。
            result["tool"] = tool
            result["objective"] = objective
            result["arguments"] = arguments
            result["signature"] = signature
            result["reused_from_step_id"] = str(result.get("reused_from_step_id") or "")
            logger.info(
                "步骤完成 step_id=%s tool=%s status=%s elapsed=%.2fs",
                step_id or "-",
                tool,
                str(result.get("status", "ok")),
                time.monotonic() - started_at,
            )
            return result
        except Exception as exc:
            logger.warning(
                "步骤失败 step_id=%s tool=%s elapsed=%.2fs error=%s",
                step_id or "-",
                tool,
                time.monotonic() - started_at,
                exc,
            )
            raise

    def _run_nl2sql_step(
        self,
        step_id: str,
        objective: str,
        arguments: Dict[str, Any],
        trace_id: str,
        root_run: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """执行 NL2SQL 工具步骤并产出可解释证据。

        Args:
            step_id: 计划步骤 ID。
            objective: 步骤目标描述。
            arguments: 步骤参数（question/tables/enable_column_retrieval）。
            trace_id: 链路追踪 ID。
            root_run: 可选根追踪对象。

        Returns:
            标准化步骤结果，`result` 中包含 SQL 与查询结果。
        """
        question_list = self._normalize_text_list(arguments.get("question"), arguments.get("questions"), objective)
        if not question_list:
            raise ValueError("NL2SQL 缺少 question/questions 参数")
        tables = arguments.get("tables") if isinstance(arguments.get("tables"), list) else None
        use_columns = bool(arguments.get("enable_column_retrieval", False))
        query_mode = self._normalize_query_mode(arguments.get("query_mode"))

        items: List[Dict[str, Any]] = []
        for idx, question in enumerate(question_list, start=1):
            first_error = ""
            retried = False
            retried_without_columns = False
            try:
                # 首次按计划参数执行，可选启用列检索能力提升 SQL 命中率。
                payload = self.mcp_client.call_tool(
                    "nl2sql_query",
                    {
                        "question": question,
                        "tables": tables,
                        "enable_column_retrieval": use_columns,
                        "query_mode": query_mode,
                        "trace_id": trace_id,
                    },
                    trace_id=trace_id,
                    root_run=root_run,
                )
            except Exception as exc:
                # 重试时把首次报错注入上下文，帮助 NL2SQL 修正失败原因。
                retried = True
                first_error = str(exc)
                retried_without_columns = use_columns
                retry_question = self._build_retry_question(
                    question,
                    first_error,
                    tool_name="nl2sql",
                    extra_instruction=(
                        f"query_mode={query_mode}。若上次 SQL 无法执行，请输出语义等价但可执行的 SQL。"
                    ),
                )
                try:
                    payload = self.mcp_client.call_tool(
                        "nl2sql_query",
                        {
                            "question": retry_question,
                            "tables": tables,
                            "enable_column_retrieval": False if use_columns else use_columns,
                            "query_mode": query_mode,
                            "trace_id": trace_id,
                        },
                        trace_id=trace_id,
                        root_run=root_run,
                    )
                except Exception as retry_exc:
                    items.append(
                        {
                            "index": idx,
                            "question": question,
                            "status": "error",
                            "error": str(retry_exc),
                            "first_error": first_error,
                            "retried": True,
                            "retried_without_columns": retried_without_columns,
                        }
                    )
                    continue

            sql = str(payload.get("sql", "")) if isinstance(payload, dict) else ""
            result = payload.get("result", {}) if isinstance(payload, dict) else {}
            items.append(
                {
                    "index": idx,
                    "question": question,
                    "status": "ok",
                    "sql": sql,
                    "result": result,
                    "retried": retried,
                    "first_error": first_error,
                    "retried_without_columns": retried_without_columns,
                }
            )

        success_items = [item for item in items if str(item.get("status") or "") == "ok"]
        if not success_items:
            first_error = str(items[0].get("error") or "NL2SQL 执行失败") if items else "NL2SQL 执行失败"
            raise RuntimeError(first_error)

        if len(items) == 1:
            result_payload = {
                "sql": str(success_items[0].get("sql") or ""),
                "result": success_items[0].get("result", {}),
            }
            evidence_body = (
                f"问题: {success_items[0].get('question')}\n"
                f"SQL: {success_items[0].get('sql')}\n"
                f"结果: {_truncate(str(success_items[0].get('result', {})), 2000)}"
            )
        else:
            result_payload = {
                "items": items,
                "success_count": len(success_items),
                "total_count": len(items),
            }
            detail_lines: List[str] = []
            for item in items:
                if str(item.get("status") or "") == "ok":
                    detail_lines.append(
                        f"[{item.get('index')}] OK question={_truncate(str(item.get('question') or ''), 120)} "
                        f"sql={_truncate(str(item.get('sql') or ''), 200)}"
                    )
                else:
                    detail_lines.append(
                        f"[{item.get('index')}] ERROR question={_truncate(str(item.get('question') or ''), 120)} "
                        f"error={_truncate(str(item.get('error') or ''), 200)}"
                    )
            evidence_body = "\n".join(detail_lines)

        # 统一产出证据对象，后续上下文构建只依赖 EvidenceItem 抽象。
        evidence = EvidenceItem(
            title="NL2SQL 结果",
            content=evidence_body,
            source="nl2sql",
            score=1.0 if len(success_items) == len(items) else 0.7,
            metadata={
                "step_id": step_id,
                "query_mode": query_mode,
                "total_count": len(items),
                "success_count": len(success_items),
                "failed_count": len(items) - len(success_items),
            },
        )
        return {
            "step_id": step_id,
            "status": "ok",
            "result": result_payload,
            "evidences": [evidence],
            "sources": ["nl2sql"],
        }

    @staticmethod
    def _normalize_query_mode(query_mode: Any) -> str:
        """归一化 query_mode，仅做枚举校验。"""
        mode = str(query_mode or "").strip().upper()
        if mode in {"COUNT", "GROUP_BY", "EXISTS", "OTHER"}:
            return mode
        return "OTHER"

    @staticmethod
    def _normalize_text_list(*raw_values: Any) -> List[str]:
        """把输入归一化为去重且有序的字符串列表。"""
        values: List[str] = []
        for raw in raw_values:
            if isinstance(raw, list):
                for item in raw:
                    text = str(item or "").strip()
                    if text:
                        values.append(text)
                continue
            text = str(raw or "").strip()
            if text:
                values.append(text)
        return list(dict.fromkeys(values))

    @staticmethod
    def _build_retry_question(
        original_question: str,
        first_error: str,
        *,
        tool_name: str,
        extra_instruction: str = "",
    ) -> str:
        """构造重试问题：把首次错误注入上下文，指导工具修正重试。"""
        base = str(original_question or "").strip()
        error_text = _truncate(str(first_error or ""), 500)
        retry_parts = [
            base,
            "[重试上下文]",
            f"工具={tool_name}",
            f"首次错误={error_text}",
            "请根据上述错误修正查询并仅返回可执行结果。",
        ]
        extra = str(extra_instruction or "").strip()
        if extra:
            retry_parts.append(extra)
        return "\n".join(part for part in retry_parts if str(part).strip())

    def _run_rag_step(
        self,
        step_id: str,
        objective: str,
        arguments: Dict[str, Any],
        trace_id: str,
        root_run: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """执行 RAG 检索步骤并抽取文档证据片段。

        Args:
            step_id: 计划步骤 ID。
            objective: 步骤目标描述。
            arguments: 步骤参数（query/top_k）。
            trace_id: 链路追踪 ID。
            root_run: 可选根追踪对象。

        Returns:
            标准化步骤结果，`result` 为 rag_search 原始返回。
        """
        query = str(arguments.get("query") or objective)
        try:
            top_k = max(1, int(arguments.get("top_k", 5)))
        except Exception:
            # 参数异常时使用默认 top_k，避免步骤失败。
            top_k = 5
        payload = self.mcp_client.call_tool(
            "rag_search",
            {"query": query, "top_k": top_k, "trace_id": trace_id},
            trace_id=trace_id,
            root_run=root_run,
        )

        chunks = payload.get("chunks", []) if isinstance(payload, dict) else []
        evidences: List[EvidenceItem] = []
        sources: List[str] = []
        # 为控制上下文长度，仅保留前 3 个高相关片段进入证据池。
        for chunk in chunks[:3]:
            if not isinstance(chunk, dict):
                continue
            src = str(chunk.get("source") or "rag")
            text = str(chunk.get("text") or "")
            evidences.append(
                EvidenceItem(
                    title="RAG 文档片段",
                    content=f"来源: {src}\n{text}",
                    source="rag",
                    score=0.8,
                    metadata={"step_id": step_id, "score": chunk.get("score")},
                )
            )
            sources.append(src)

        return {
            "step_id": step_id,
            "status": "ok",
            "result": payload if isinstance(payload, dict) else {"data": payload},
            "evidences": evidences,
            "sources": sources,
        }

    def _run_graph_step(
        self,
        step_id: str,
        objective: str,
        arguments: Dict[str, Any],
        trace_id: str,
        root_run: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """执行图数据库查询步骤（LlamaIndex Text2Cypher）。

        Args:
            step_id: 计划步骤 ID。
            objective: 步骤目标描述。
            arguments: 步骤参数（question/max_rows）。
            trace_id: 链路追踪 ID。
            root_run: 可选根追踪对象。

        Returns:
            标准化步骤结果，`result` 为 neo4j_llamaindex_query 返回内容。
        """
        # 当前链路不在主流程生成 Cypher；统一交给 Neo4j-LlamaIndex 工具内部生成并执行。
        question_list = self._normalize_text_list(arguments.get("question"), arguments.get("questions"), objective)
        if not question_list:
            raise ValueError("graph 缺少 question/questions 参数")
        max_rows = arguments.get("max_rows")
        # 子图最多修复重试次数：第1次正常生成，后续每次用修复 template 重试。
        max_cypher_retries: int = 2

        items: List[Dict[str, Any]] = []
        for idx, question in enumerate(question_list, start=1):
            repair_context: Optional[Dict[str, Any]] = None
            attempt_errors: List[str] = []
            payload: Optional[Dict[str, Any]] = None

            # 子图重试循环：每次失败后提取 raw_cypher 并通过修复模板重试，
            # 错误上下文在 LlamaIndex PromptTemplate 内正确传递，而非混入 question。
            for attempt in range(1 + max_cypher_retries):
                try:
                    call_args: Dict[str, Any] = {
                        "question": question,
                        "max_rows": max_rows,
                        "trace_id": trace_id,
                    }
                    if repair_context:
                        call_args["repair_context"] = repair_context
                    payload = self.mcp_client.call_tool(
                        "neo4j_llamaindex_query",
                        call_args,
                        trace_id=trace_id,
                        root_run=root_run,
                    )
                    break  # 成功，退出重试循环
                except Exception as exc:
                    err_msg = str(exc)
                    attempt_errors.append(err_msg)
                    # 从异常消息中提取 raw_cypher（格式: "...校验错误...|raw_cypher=CALL ..."）
                    raw_cypher = ""
                    if "|raw_cypher=" in err_msg:
                        raw_cypher = err_msg.split("|raw_cypher=", 1)[-1].strip()
                    # 去掉 |raw_cypher=... 后的纯错误部分
                    clean_error = err_msg.split("|raw_cypher=")[0].strip()
                    logger.warning(
                        "neo4j 查询失败 attempt=%d/%d trace_id=%s error=%s raw_cypher=%s",
                        attempt + 1, 1 + max_cypher_retries,
                        trace_id or "-", clean_error, raw_cypher or "(未捕获)",
                    )
                    if attempt < max_cypher_retries:
                        repair_context = {"raw_cypher": raw_cypher, "error": clean_error}
                    else:
                        # 全部重试耗尽，记录错误并跳出
                        items.append(
                            {
                                "index": idx,
                                "question": question,
                                "status": "error",
                                "error": clean_error,
                                "first_error": attempt_errors[0] if attempt_errors else clean_error,
                                "retried": attempt > 0,
                                "attempt_count": attempt + 1,
                            }
                        )
                        payload = None
                        break

            if payload is None:
                continue

            cypher = str(payload.get("cypher", "")) if isinstance(payload, dict) else ""
            row_count = payload.get("row_count") if isinstance(payload, dict) else None
            items.append(
                {
                    "index": idx,
                    "question": question,
                    "status": "ok",
                    "payload": payload if isinstance(payload, dict) else {"data": payload},
                    "cypher": cypher,
                    "row_count": row_count,
                    "retried": len(attempt_errors) > 0,
                    "first_error": attempt_errors[0] if attempt_errors else "",
                    "attempt_count": len(attempt_errors) + 1,
                }
            )

        success_items = [item for item in items if str(item.get("status") or "") == "ok"]
        if not success_items:
            first_error = str(items[0].get("error") or "graph 执行失败") if items else "graph 执行失败"
            any_retried = any(item.get("retried") for item in items)
            # 用后缀编码 retried 信息，使外层 except 可识别是否已经过子图重试。
            raise RuntimeError(f"{first_error}|step_retried={any_retried}")

        if len(items) == 1:
            result_payload = success_items[0].get("payload", {})
            evidence_body = (
                f"问题: {success_items[0].get('question')}\n"
                f"Cypher: {success_items[0].get('cypher')}\n"
                f"结果: {_truncate(str(result_payload), 2000)}"
            )
        else:
            result_payload = {
                "items": items,
                "success_count": len(success_items),
                "total_count": len(items),
            }
            detail_lines: List[str] = []
            for item in items:
                if str(item.get("status") or "") == "ok":
                    detail_lines.append(
                        f"[{item.get('index')}] OK question={_truncate(str(item.get('question') or ''), 120)} "
                        f"cypher={_truncate(str(item.get('cypher') or ''), 200)} "
                        f"row_count={item.get('row_count')}"
                    )
                else:
                    detail_lines.append(
                        f"[{item.get('index')}] ERROR question={_truncate(str(item.get('question') or ''), 120)} "
                        f"error={_truncate(str(item.get('error') or ''), 200)}"
                    )
            evidence_body = "\n".join(detail_lines)

        evidence = EvidenceItem(
            title="图谱查询结果",
            content=evidence_body,
            source="neo4j",
            score=0.9 if len(success_items) == len(items) else 0.6,
            metadata={
                "step_id": step_id,
                "total_count": len(items),
                "success_count": len(success_items),
                "failed_count": len(items) - len(success_items),
            },
        )
        # 任意子问题有过重试则标记，供 _build_previous_plan_payload 识别彻底失败工具。
        any_retried = any(item.get("retried") for item in items)
        return {
            "step_id": step_id,
            "status": "ok",
            "result": result_payload,
            "evidences": [evidence],
            "sources": ["neo4j"],
            "retried": any_retried,
        }
    @staticmethod
    def _normalize_arguments_for_signature(tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """规范化步骤参数，构建稳定签名用于跨轮去重。"""
        normalized: Dict[str, Any]
        if tool == "nl2sql":
            tables = arguments.get("tables") if isinstance(arguments.get("tables"), list) else []
            questions = LangGraphOrchestrator._normalize_text_list(arguments.get("question"), arguments.get("questions"))
            normalized = {
                "questions": questions,
                "tables": sorted({str(item).strip() for item in tables if str(item).strip()}),
                "enable_column_retrieval": bool(arguments.get("enable_column_retrieval", False)),
                "query_mode": LangGraphOrchestrator._normalize_query_mode(arguments.get("query_mode")),
            }
        elif tool == "rag":
            normalized = {
                "query": str(arguments.get("query") or "").strip(),
                "top_k": int(arguments.get("top_k", 5)) if str(arguments.get("top_k", "")).strip() else 5,
            }
        elif tool == "graph":
            questions = LangGraphOrchestrator._normalize_text_list(arguments.get("question"), arguments.get("questions"))
            normalized = {
                "questions": questions,
                "max_rows": arguments.get("max_rows"),
            }
        else:
            normalized = {str(k): arguments[k] for k in sorted(arguments.keys())}
        return normalized

    @staticmethod
    def _build_step_signature(tool: str, objective: str, arguments: Dict[str, Any]) -> str:
        """构建步骤签名：同工具+同目标+同参数可复用。"""
        normalized_tool = str(tool or "none").strip().lower()
        payload = {
            "tool": normalized_tool,
            "objective": str(objective or "").strip(),
            "arguments": LangGraphOrchestrator._normalize_arguments_for_signature(normalized_tool, arguments),
        }
        raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _find_reusable_step_result(
        state: AgentGraphState,
        signature: str,
        current_step_id: str,
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        """在已有步骤结果中查找同签名成功结果。"""
        step_results = state.get("step_results") or {}
        if not isinstance(step_results, dict):
            return None
        for prev_step_id, entry in step_results.items():
            if str(prev_step_id) == current_step_id:
                continue
            if not isinstance(entry, dict):
                continue
            if str(entry.get("status") or "").strip().lower() != "ok":
                continue
            prev_signature = str(entry.get("signature") or "").strip()
            if prev_signature and prev_signature == signature:
                return str(prev_step_id), entry
        return None

    @staticmethod
    def _summarize_step_result_for_plan(step_id: str, step_result: Dict[str, Any]) -> Dict[str, Any]:
        """压缩步骤结果摘要，供 planner 在重规划时参考。"""
        if not isinstance(step_result, dict):
            return {"step_id": step_id, "status": "unknown", "tool": "", "summary": "无结果"}

        status = str(step_result.get("status") or "unknown")
        error = _truncate(str(step_result.get("error") or ""), 200)
        tool = str(step_result.get("tool") or "").strip().lower()
        payload = step_result.get("result", {})
        if not tool and isinstance(payload, dict):
            if "sql" in payload:
                tool = "nl2sql"
            elif "cypher" in payload:
                tool = "graph"
            elif "chunks" in payload:
                tool = "rag"
            elif str(payload.get("tool") or "").strip().lower() == "none":
                tool = "none"

        summary = "无摘要"
        if isinstance(payload, dict):
            if tool == "nl2sql":
                batch_items = payload.get("items") if isinstance(payload.get("items"), list) else []
                if batch_items:
                    ok_count = sum(1 for item in batch_items if isinstance(item, dict) and str(item.get("status") or "") == "ok")
                    first_ok = next(
                        (
                            item
                            for item in batch_items
                            if isinstance(item, dict) and str(item.get("status") or "") == "ok"
                        ),
                        {},
                    )
                    sql_preview = _truncate(str(first_ok.get("sql") or ""), 180) if isinstance(first_ok, dict) else ""
                    summary = f"batch={len(batch_items)}; success={ok_count}; first_sql={sql_preview}"
                else:
                    sql_preview = _truncate(str(payload.get("sql") or ""), 220)
                    result_payload = payload.get("result", {}) if isinstance(payload.get("result"), dict) else {}
                    row_count = result_payload.get("row_count")
                    if row_count is None and isinstance(result_payload.get("rows"), list):
                        row_count = len(result_payload.get("rows") or [])
                    summary = f"sql={sql_preview}; row_count={row_count}"
            elif tool == "graph":
                batch_items = payload.get("items") if isinstance(payload.get("items"), list) else []
                if batch_items:
                    ok_count = sum(1 for item in batch_items if isinstance(item, dict) and str(item.get("status") or "") == "ok")
                    first_ok = next(
                        (
                            item
                            for item in batch_items
                            if isinstance(item, dict) and str(item.get("status") or "") == "ok"
                        ),
                        {},
                    )
                    cypher_preview = _truncate(str(first_ok.get("cypher") or ""), 180) if isinstance(first_ok, dict) else ""
                    summary = f"batch={len(batch_items)}; success={ok_count}; first_cypher={cypher_preview}"
                else:
                    cypher_preview = _truncate(str(payload.get("cypher") or ""), 220)
                    row_count = payload.get("row_count")
                    if row_count is None and isinstance(payload.get("rows"), list):
                        row_count = len(payload.get("rows") or [])
                    summary = f"cypher={cypher_preview}; row_count={row_count}"
            elif tool == "rag":
                chunks = payload.get("chunks") if isinstance(payload.get("chunks"), list) else []
                sources = []
                for chunk in chunks[:3]:
                    if not isinstance(chunk, dict):
                        continue
                    src = str(chunk.get("source") or "").strip()
                    if src:
                        sources.append(src)
                summary = f"chunk_count={len(chunks)}; sources={sources}"
            else:
                summary = _truncate(_trace_json(payload, limit=600), 260)
        else:
            summary = _truncate(str(payload), 260)

        return {
            "step_id": step_id,
            "status": status,
            "tool": tool,
            "objective": _truncate(str(step_result.get("objective") or ""), 160),
            "summary": summary,
            "error": error,
            "signature": str(step_result.get("signature") or ""),
            "reused_from_step_id": str(step_result.get("reused_from_step_id") or ""),
        }

    def _build_previous_plan_payload(
        self, state: AgentGraphState
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        """拼装重规划输入：上一轮计划步骤、各步骤结果摘要、彻底失败的工具列表。

        Returns:
            (previous_plan_steps, previous_step_summaries, permanently_failed_tools)
            permanently_failed_tools：经过子图重试后仍失败的工具名列表，供 planner 禁止重复使用。
        """
        raw_plan_steps = state.get("plan_steps") if isinstance(state.get("plan_steps"), list) else []
        step_results = state.get("step_results") if isinstance(state.get("step_results"), dict) else {}

        previous_plan_steps: List[Dict[str, Any]] = []
        previous_step_summaries: List[Dict[str, Any]] = []
        planned_step_ids: List[str] = []
        permanently_failed_tools: List[str] = []

        for raw_step in raw_plan_steps[:20]:
            if not isinstance(raw_step, dict):
                continue
            step_id = str(raw_step.get("step_id") or "").strip()
            if not step_id:
                continue
            planned_step_ids.append(step_id)
            depends_on = raw_step.get("depends_on") if isinstance(raw_step.get("depends_on"), list) else []
            tool_name = str(raw_step.get("tool") or "")
            previous_plan_steps.append(
                {
                    "step_id": step_id,
                    "tool": tool_name,
                    "objective": _truncate(str(raw_step.get("objective") or ""), 200),
                    "depends_on": [str(item).strip() for item in depends_on if str(item).strip()],
                }
            )
            result = step_results.get(step_id, {}) if isinstance(step_results.get(step_id), dict) else {}
            summary = self._summarize_step_result_for_plan(step_id, result)
            previous_step_summaries.append(summary)

            # 步骤失败且经过子图重试（retried=True）意味着已尝试修复仍无法执行，
            # 将该工具标记为"彻底失败"，重规划时不应再生成此工具步骤。
            if (
                str(result.get("status") or "") == "error"
                and result.get("retried")
                and tool_name
                and tool_name not in permanently_failed_tools
            ):
                permanently_failed_tools.append(tool_name)

        # 兼容历史残留结果：即使不在当前计划，也给 planner 作为补充上下文。
        for step_id, step_result in step_results.items():
            sid = str(step_id)
            if sid in planned_step_ids:
                continue
            if not isinstance(step_result, dict):
                continue
            previous_step_summaries.append(self._summarize_step_result_for_plan(sid, step_result))

        return previous_plan_steps[:20], previous_step_summaries[:30], permanently_failed_tools

    def _resolve_available_tools(self, trace_id: str) -> Dict[str, bool]:
        """从 MCP 服务动态发现当前可用工具能力。

        Args:
            trace_id: 当前会话追踪 ID，用于透传到工具层日志。

        Returns:
            工具可用性字典；包含 nl2sql/rag/graph/none/note。
        """
        available = {
            "nl2sql": False,
            "rag": False,
            "graph": False,
            "none": True,
            "note": False,
        }
        try:
            # 运行时发现而非静态配置，支持工具服务热插拔。
            tools = self.mcp_client.list_tools_sync(trace_id=trace_id, root_run=_ROOT_RUN_CTX.get())
            names = {str(item.get("name") or "").strip() for item in tools if isinstance(item, dict)}
            available["nl2sql"] = "nl2sql_query" in names
            available["rag"] = "rag_search" in names
            # graph 工具要求 LlamaIndex 自主 Text2Cypher 执行能力。
            available["graph"] = "neo4j_llamaindex_query" in names
            available["note"] = "note_search" in names
        except Exception as exc:
            logger.warning("MCP 工具发现失败，使用默认能力集 error=%s", exc)
            available.update({"nl2sql": True, "rag": True, "graph": True, "note": True})
        return available

    def _generate_cypher(self, objective: str) -> str:
        """根据自然语言目标生成 Cypher 查询语句。

        Args:
            objective: 图查询目标描述。

        Returns:
            可执行 Cypher 字符串；若输出含 JSON 包裹则自动提取 `cypher` 字段。
        """
        messages = [
            LLMMessage(role="system", content=GRAPH_CYPHER_PROMPT),
            LLMMessage(role="user", content=json.dumps({"objective": objective}, ensure_ascii=False)),
        ]
        # 兼容模型输出 markdown fenced code / JSON 包裹等格式噪声。
        content = self.llm.chat(messages)
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("cypher"):
                text = text[6:].strip()
        if "{" in text and "}" in text:
            try:
                payload = _extract_json(text)
                if payload.get("cypher"):
                    return str(payload.get("cypher")).strip()
            except Exception:
                # JSON 解析失败时回退为原始文本，交由下游执行器兜底处理。
                pass
        return text

    def _maybe_write_semantic_memory(self, user_message: str, answer: str) -> None:
        """按配置与阈值条件写入语义记忆。

        Args:
            user_message: 用户问题文本。
            answer: 模型回答文本。
        """
        # 语义记忆写入是可选能力，由配置开关与重要度阈值共同控制。
        if not self.config.semantic_memory_enabled:
            return
        if not answer.strip():
            return
        records = self._extract_semantic_records(user_message, answer)
        if not records:
            return
        for record in records:
            try:
                self.memory_manager.semantic_memory.add_concept(record)
            except Exception as exc:
                logger.warning("语义记忆写入失败 concept=%s error=%s", record.concept, exc)

    def _extract_semantic_records(self, user_message: str, answer: str) -> List[SemanticRecord]:
        """从问答内容中抽取结构化语义记忆条目。

        Args:
            user_message: 用户问题文本。
            answer: 模型回答文本。

        Returns:
            通过重要度阈值过滤后的 `SemanticRecord` 列表。
        """
        prompt = [
            LLMMessage(role="system", content=SEMANTIC_EXTRACT_PROMPT),
            LLMMessage(role="user", content=f"用户问题：{user_message}\n助手回答：{answer}\n请抽取语义记忆条目。"),
        ]
        try:
            raw = self.llm.structured_chat(prompt, schema={"type": "array"})
        except Exception:
            # 抽取失败不影响主流程，直接返回空列表。
            return []

        items: Any = raw
        if isinstance(raw, dict):
            items = raw.get("items") or raw.get("concepts") or []
        if not isinstance(items, list):
            return []

        records: List[SemanticRecord] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            concept = str(item.get("concept", "")).strip()
            description = str(item.get("description", "")).strip()
            if not concept or not description:
                continue
            try:
                importance = float(item.get("importance", 0.0))
            except (TypeError, ValueError):
                importance = 0.0
            # 低重要度条目直接丢弃，减少语义图谱噪声。
            if importance < self.config.semantic_memory_min_importance:
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            category = str(item.get("category", "")).strip()
            if category:
                # category 归入 metadata，统一下游消费结构。
                metadata.setdefault("category", category)
            metadata.setdefault("source", "semantic_extract")
            metadata.setdefault("importance", importance)
            records.append(SemanticRecord(concept=concept, description=description, metadata=metadata))
            if len(records) >= self.config.semantic_memory_max_items:
                break
        return records
