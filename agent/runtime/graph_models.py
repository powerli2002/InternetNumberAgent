"""LangGraph 运行时数据模型。

本文件只负责“计划数据结构”与“基础清洗规则”，不承担调度执行逻辑。

设计目标：
1. 把 LLM 输出的松散 JSON 规范化为强约束对象；
2. 在进入调度前尽早发现并修复常见脏数据；
3. 在对象与字典之间稳定转换，便于写入/读取 LangGraph 状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal


# 计划步骤允许的工具集合。
# 使用 Literal 的目的：在静态类型检查阶段限制合法值，减少“拼写错误型”问题。
ToolName = Literal["nl2sql", "rag", "graph", "todo", "none"]


@dataclass
class GraphPlanStep:
    """图编排中的执行步骤。

    字段说明：
    - step_id: 步骤唯一标识。后续调度、依赖解析、结果索引都依赖该值。
    - objective: 当前步骤要达成的目标描述，必须非空。
    - tool: 执行该步骤的工具类型（受 ToolName 限制）。
    - arguments: 传给工具的参数载荷。
    - depends_on: 前置依赖步骤 ID 列表，只有这些步骤完成后当前步骤才可执行。
    - can_parallel: 是否可并行执行（调度层可参考，不是强约束）。
    - is_complex: 是否属于复杂步骤（可用于策略分流或监控标记）。
    - expected_output: 期望产出描述，便于追踪与评估。
    - budget: 预算约束（如 token、时间、调用次数等），具体语义由上层定义。
    """

    step_id: str
    objective: str
    tool: ToolName
    arguments: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    can_parallel: bool = True
    is_complex: bool = False
    expected_output: str = "结构化结果 + 证据摘要"
    budget: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """将步骤对象序列化为可写入状态的 dict。

        说明：LangGraph 状态通常以基础类型（dict/list/str 等）传递，
        因此这里提供统一出口，确保字段命名与结构稳定。
        """
        return {
            "step_id": self.step_id,
            "objective": self.objective,
            "tool": self.tool,
            "arguments": self.arguments,
            "depends_on": self.depends_on,
            "can_parallel": self.can_parallel,
            "is_complex": self.is_complex,
            "expected_output": self.expected_output,
            "budget": self.budget,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], idx: int) -> "GraphPlanStep":
        """从原始字典构建步骤对象，并执行最小必要清洗。

        Args:
            data: 原始步骤数据（通常来自 LLM 结构化输出）。
            idx: 步骤在列表中的位置，用于生成兜底 step_id。

        Returns:
            规范化后的 GraphPlanStep。

        Raises:
            ValueError: 当 objective 缺失/为空时抛出，避免生成不可执行步骤。
        """
        # 1) step_id 清洗：优先使用输入值；缺失时根据位置兜底生成。
        raw_step_id = str(data.get("step_id") or "").strip()
        step_id = raw_step_id or f"step_{idx + 1}"

        # 2) objective 是执行语义核心，必须存在。
        objective = str(data.get("objective") or "").strip()
        if not objective:
            raise ValueError(f"步骤 {step_id} 缺少 objective")

        # 3) tool 统一小写并限定到白名单；非法值降级为 none，避免执行器报错。
        tool = str(data.get("tool") or "none").strip().lower()
        if tool not in {"nl2sql", "rag", "graph", "todo", "none"}:
            tool = "none"

        # 4) 仅接受 dict/list 等预期结构，类型不匹配则回退默认值。
        # 这样可以提升对“半结构化输出”的容错能力。
        arguments = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
        depends_on_raw = data.get("depends_on") if isinstance(data.get("depends_on"), list) else []

        # 5) 依赖列表元素统一转字符串并去空白，过滤空项。
        depends_on = [str(x).strip() for x in depends_on_raw if str(x).strip()]
        expected_output = str(data.get("expected_output") or "结构化结果 + 证据摘要").strip()
        budget = data.get("budget") if isinstance(data.get("budget"), dict) else {}

        return cls(
            step_id=step_id,
            objective=objective,
            tool=tool,  # type: ignore[arg-type]
            arguments=arguments,
            depends_on=depends_on,
            can_parallel=bool(data.get("can_parallel", True)),
            is_complex=bool(data.get("is_complex", False)),
            expected_output=expected_output,
            budget=budget,
        )


@dataclass
class GraphPlan:
    """LangGraph 主计划。

    一个计划由多个 GraphPlanStep 组成，外加计划级元信息：
    - reason: 规划理由，便于追踪与解释；
    - max_replans: 允许的最大重规划次数（由上层编排器消费）。
    """

    steps: List[GraphPlanStep]
    reason: str
    max_replans: int = 1

    def to_dict(self) -> Dict[str, Any]:
        """将计划对象序列化为 dict，供状态存储或跨组件传输。"""
        return {
            "steps": [step.to_dict() for step in self.steps],
            "reason": self.reason,
            "max_replans": self.max_replans,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphPlan":
        """从llm输出的原始字典构建计划对象，并做计划级基础校验。"""
        # 1) 仅处理 list[dict] 形态的步骤输入，其余类型直接视为空。
        raw_steps = data.get("steps") if isinstance(data.get("steps"), list) else []

        # 2) 逐项转换为 GraphPlanStep。单步转换内部会进一步清洗字段。
        steps = [
            GraphPlanStep.from_dict(item, idx)
            for idx, item in enumerate(raw_steps)
            if isinstance(item, dict)
        ]

        # 3) 空计划不可调度，直接抛错交给上层走兜底策略。
        if not steps:
            raise ValueError("计划 steps 不能为空")

        # 4) reason 允许缺省，但会填充可解释默认值。
        reason = str(data.get("reason") or "未提供规划理由").strip() or "未提供规划理由"
        try:
            # 5) max_replans 至少为 0，防止出现负数导致的策略歧义。
            max_replans = max(0, int(data.get("max_replans", 1)))
        except Exception:
            # 输入异常时回退到保守默认值，保证系统继续运行。
            max_replans = 1
        return cls(steps=steps, reason=reason, max_replans=max_replans)

    def sanitize_dependencies(self) -> None:
        """清理依赖关系中的无效项，避免调度阻塞或死锁。

        清理规则：
        - 依赖目标不在当前计划中：删除；
        - 自依赖（A 依赖 A）：删除。

        注意：这里不做“环检测”（如 A->B->A），环检测若需要应由上层补充。
        """
        # 先构建当前计划的合法步骤 ID 集合，用于 O(1) membership 判断。
        known_ids = {step.step_id for step in self.steps}
        for step in self.steps:
            # 仅保留“存在于计划内且非自身”的依赖项。
            step.depends_on = [dep for dep in step.depends_on if dep in known_ids and dep != step.step_id]
