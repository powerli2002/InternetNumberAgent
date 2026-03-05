"""评测题库与样本构建逻辑。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List

from agent.evaluate.core.schemas import QuerySample

# 固定题库模板：总计 30 题，严格满足 20 RAG + 5 NL2SQL + 5 Graph。
# 其中前 20 题均为“仅依赖 Milvus 文档检索可回答”的知识性问题。
_QUERY_BANK: List[Dict[str, object]] = [
    # ----- 20 个 RAG（仅文档检索） -----
    {
        "query": "什么是自治系统（AS）？按连接属性和流量角色，自治系统通常可以分为哪几类？",
        "category": "rag",
        "difficulty": "easy",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["as", "classification", "chapter2"],
    },
    {
        "query": "BGP 协议中常见的消息类型有哪些？它们各自承担什么作用？",
        "category": "rag",
        "difficulty": "easy",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["bgp", "message_type", "chapter2"],
    },
    {
        "query": "什么是 BGP 路由信息库（RIB）？它在域间路由运行中的意义是什么？",
        "category": "rag",
        "difficulty": "easy",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["rib", "bgp", "chapter2"],
    },
    {
        "query": "BGP 路由决策过程通常会考虑哪些关键因素？",
        "category": "rag",
        "difficulty": "easy",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["bgp", "decision_process", "chapter2"],
    },
    {
        "query": "被动路由报文采集与实时流报文采集的主要区别是什么？",
        "category": "rag",
        "difficulty": "easy",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["collection", "passive", "realtime"],
    },
    {
        "query": "BGP 监控协议（BMP）在路由监测体系中的作用是什么？",
        "category": "rag",
        "difficulty": "medium",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["bmp", "monitoring", "chapter2"],
    },
    {
        "query": "RIPE NCC、Routeviews、BGPStream 这三类路由信息服务在监测场景中的定位分别是什么？",
        "category": "rag",
        "difficulty": "medium",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["ripe", "routeviews", "bgpstream"],
    },
    {
        "query": "域间路由异常通常如何分类？常见的分类维度有哪些？",
        "category": "rag",
        "difficulty": "easy",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["anomaly", "taxonomy", "chapter2"],
    },
    {
        "query": "前缀劫持事件可以按哪些维度进行分类（如路径位置、前缀粒度、事件影响、事件动机）？",
        "category": "rag",
        "difficulty": "easy",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["hijack", "classification", "chapter4"],
    },
    {
        "query": "YouTube 劫持事件常被用于说明哪类域间路由安全问题？其教学意义是什么？",
        "category": "rag",
        "difficulty": "medium",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["youtube", "hijack_case", "chapter4"],
    },
    {
        "query": "控制平面检测、数据平面检测、混合检测三种方法在路由异常监测中的侧重点有何不同？",
        "category": "rag",
        "difficulty": "medium",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["control_plane", "data_plane", "hybrid"],
    },
    {
        "query": "基于知识过滤的路由劫持检测流程为什么要分为“疑似事件检测、合规性过滤、事件定级评估”三步？",
        "category": "rag",
        "difficulty": "easy",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["knowledge_filtering", "hijack_detection", "chapter4"],
    },
    {
        "query": "路由泄露事件有哪些典型类型？请简述“发夹弯”“对等体横向泄漏”“上坡/下坡泄露”的区别。",
        "category": "rag",
        "difficulty": "easy",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["route_leak", "taxonomy", "chapter5"],
    },
    {
        "query": "什么是“无谷（Valley-Free）”准则？它在路由泄露检测中起什么作用？",
        "category": "rag",
        "difficulty": "medium",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["valley_free", "route_leak", "chapter5"],
    },
    {
        "query": "实时路由泄露检测算法中，“精确匹配、快速定位、风险评估”三类步骤分别解决什么问题？",
        "category": "rag",
        "difficulty": "medium",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["realtime_detection", "route_leak", "chapter5"],
    },
    {
        "query": "域间路由中断事件可以按哪些维度分类（位置、原因、粒度）？",
        "category": "rag",
        "difficulty": "easy",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["outage", "classification", "chapter6"],
    },
    {
        "query": "在 BGP 中断检测中，为什么需要构建“路由可见性特征”？",
        "category": "rag",
        "difficulty": "medium",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["visibility", "outage_detection", "chapter6"],
    },
    {
        "query": "主动防御与被动防御在域间路由安全中的定位有什么差异？",
        "category": "rag",
        "difficulty": "easy",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["defense", "active_passive", "chapter7"],
    },
    {
        "query": "域间路由防御联盟中常见的“过滤、源地址验证、协调、验证”分别指什么？",
        "category": "rag",
        "difficulty": "medium",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["defense_alliance", "coordination", "chapter7"],
    },
    {
        "query": "在路由劫持检测中，RPKI 验证一般如何辅助判断前缀宣告是否合法？",
        "category": "rag",
        "difficulty": "medium",
        "expected_tools": ["rag"],
        "expected_tool_calls": [{"name": "rag"}],
        "tags": ["rpki", "hijack_detection", "bgp"],
    },

    # ----- 5 个 SQL -----
    {
        "query": "统计 as_entity 中活跃 AS 的总量，并按国家前 10 排名。",
        "category": "nl2sql",
        "difficulty": "easy",
        "expected_tools": ["nl2sql"],
        "expected_tool_calls": [{"name": "nl2sql"}],
        "tags": ["as_entity", "country", "count"],
    },
    {
        "query": "给出 org_entity 中名称包含 telecom 的组织数量，并列出前 5 个示例。",
        "category": "nl2sql",
        "difficulty": "easy",
        "expected_tools": ["nl2sql"],
        "expected_tool_calls": [{"name": "nl2sql"}],
        "tags": ["org_entity", "filter", "count"],
    },
    {
        "query": "检查 ip_bgp_entity 中是否存在同一前缀对应多个 origin_as 的记录，返回是否存在。",
        "category": "nl2sql",
        "difficulty": "medium",
        "expected_tools": ["nl2sql"],
        "expected_tool_calls": [{"name": "nl2sql"}],
        "tags": ["ip_bgp_entity", "consistency", "exists"],
    },
    {
        "query": "评估 as_entity 与 org_entity 的映射完整性，输出缺失映射的 AS 数量。",
        "category": "nl2sql",
        "difficulty": "medium",
        "expected_tools": ["nl2sql"],
        "expected_tool_calls": [{"name": "nl2sql"}],
        "tags": ["as_entity", "org_entity", "mapping"],
    },
    {
        "query": "比较 ipv4_entity 与 ipv6_entity 的前缀规模分布差异，给出统计结果。",
        "category": "nl2sql",
        "difficulty": "medium",
        "expected_tools": ["nl2sql"],
        "expected_tool_calls": [{"name": "nl2sql"}],
        "tags": ["ipv4_entity", "ipv6_entity", "distribution"],
    },

    # ----- 5 个 Neo4j -----
    {
        "query": "以某个 ASN 为起点，查询其上游/下游邻接关系并给出摘要。",
        "category": "graph",
        "difficulty": "medium",
        "expected_tools": ["graph"],
        "expected_tool_calls": [{"name": "graph"}],
        "tags": ["asn", "topology", "neighbor"],
    },
    {
        "query": "从图谱中查询某个前缀关联的 AS 与组织信息，并返回链路摘要。",
        "category": "graph",
        "difficulty": "medium",
        "expected_tools": ["graph"],
        "expected_tool_calls": [{"name": "graph"}],
        "tags": ["prefix", "as", "org"],
    },
    {
        "query": "判断两个 ASN 在图谱中是否存在可达路径，并给出最短路径节点序列。",
        "category": "graph",
        "difficulty": "hard",
        "expected_tools": ["graph"],
        "expected_tool_calls": [{"name": "graph"}],
        "tags": ["asn", "path", "reachability"],
    },
    {
        "query": "查询某个组织在图谱中的关联 AS 与前缀子图规模（节点数与关系数）。",
        "category": "graph",
        "difficulty": "hard",
        "expected_tools": ["graph"],
        "expected_tool_calls": [{"name": "graph"}],
        "tags": ["org", "subgraph", "size"],
    },
    {
        "query": "用图谱关系解释一个域名从网站实体到组织归属的关系链。",
        "category": "graph",
        "difficulty": "medium",
        "expected_tools": ["graph"],
        "expected_tool_calls": [{"name": "graph"}],
        "tags": ["domain", "graph_path", "org"],
    },
]


def _summary_digest(summary_path: Path) -> str:
    """读取 summary.md 并返回摘要哈希。"""
    if not summary_path.exists():
        raise FileNotFoundError(f"summary 文件不存在: {summary_path}")
    text = summary_path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"summary 文件为空: {summary_path}")
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def build_query_samples(count: int, summary_path: Path) -> List[QuerySample]:
    """根据固定题库生成 QuerySample 列表。"""
    if count <= 0:
        raise ValueError("count 必须大于 0")
    if count > len(_QUERY_BANK):
        raise ValueError(f"count 不能超过题库上限 {len(_QUERY_BANK)}")

    digest = _summary_digest(summary_path)
    samples: List[QuerySample] = []
    for idx, item in enumerate(_QUERY_BANK[:count], start=1):
        tags = [str(tag) for tag in item.get("tags", [])]
        tags.append(f"summary:{digest}")
        samples.append(
            QuerySample(
                id=f"Q{idx:03d}",
                query=str(item["query"]),
                category=str(item["category"]),
                difficulty=str(item["difficulty"]),
                expected_tools=[str(t) for t in item.get("expected_tools", [])],
                expected_tool_calls=[dict(v) for v in item.get("expected_tool_calls", [])],
                tags=tags,
                reference_answer="",
            )
        )
    return samples
