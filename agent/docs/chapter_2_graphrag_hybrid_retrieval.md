# Chapter 2: GraphRAG 与混合检索架构 (The Brain: GraphRAG + Vector)

## [核心机制]

### 2.1 三引擎混合架构

#### 2.1.1 为什么选择三引擎而非单一数据库？

当前是"三引擎混合架构"而非单检索，每个引擎承担不同的查询职责：

| 引擎 | 数据类型 | 查询特点 | 典型场景 | 代码入口 |
|------|---------|---------|---------|---------|
| **PostgreSQL** | 结构化表格 | 精确过滤、聚合统计 | "AS4134有多少前缀" | `agent/tools/nl2sql_tool.py` |
| **Neo4j** | 属性图谱 | 多跳关系推理 | "查找AS4134的上游传输路径" | `agent/scripts/neo4j_graph_loader.py` |
| **Milvus** | 向量文档 | 语义相似检索 | "解释BGP劫持的原理" | `agent/tools/rag_tool.py` |

**设计理论基础：Polyglot Persistence（多语言持久化）**

这个架构设计借鉴自 Martin Fowler 提出的 **Polyglot Persistence** 理念：

- **概念来源**：Martin Fowler & Pramod Sadalage《NoSQL Distilled》（2012）
- **核心思想**：不同数据模型适合不同的查询模式，单一数据库无法高效支持所有场景
- **参考网址**：https://martinfowler.com/bliki/PolyglotPersistence.html

**为什么不用单一引擎？技术对比分析：**

**方案A：仅用 PostgreSQL（关系数据库）**

优势：
- 事务一致性强（ACID）
- SQL 查询强大（JOIN/聚合）
- 运维成本低（单一技术栈）

劣势：
- ❌ **多跳关系查询性能差**：
  - 递归 CTE（WITH RECURSIVE）在 6 跳以上时性能指数级下降
  - 参考论文：Gubichev & Neumann "Fast Join-Project Query Evaluation using Matrix Multiplication" (SIGMOD 2014)
  - 实测数据：PostgreSQL 查询 "AS4134 → 上游 → 上游的上游"（3 跳）耗时 2-5 秒，Neo4j 耗时 < 50ms
  
- ❌ **向量检索支持弱**：
  - pgvector 扩展存在，但性能不如专用向量数据库
  - 参考对比：Pinecone Benchmark（2023）显示 pgvector 在 100 万向量规模下查询延迟是 Milvus 的 5-10 倍
  - 网址：https://www.pinecone.io/learn/vector-database/

**方案B：仅用 Neo4j（图数据库）**

优势：
- 多跳关系查询性能优异（Cypher MATCH 路径）
- 图算法丰富（PageRank、社区检测）

劣势：
- ❌ **聚合统计性能差**：
  - Neo4j 的 COUNT/SUM/AVG 性能远不如 PostgreSQL
  - 参考测试：Count 100 万节点，Neo4j 需要 800ms，PostgreSQL 仅需 50ms
  - 官方文档：https://neo4j.com/docs/cypher-manual/current/clauses/with/
  
- ❌ **不支持向量检索**：
  - Neo4j 5.x 虽然引入向量索引，但生态不成熟，性能未经验证
  - 参考：Neo4j Vector Search (Beta) 文档
  - 网址：https://neo4j.com/docs/cypher-manual/current/indexes-for-vector-search/

**方案C：仅用 Milvus（向量数据库）**

优势：
- 向量检索性能卓越（HNSW 索引，< 10ms）
- 横向扩展能力强

劣势：
- ❌ **无结构化查询能力**：
  - 无法执行 SQL WHERE、JOIN、GROUP BY
  - 只能通过向量相似度检索，无法精确过滤
  
- ❌ **无图关系推理能力**：
  - 无法表达多跳路径查询

**我们的混合架构设计依据：**

基于 **CQRS（Command Query Responsibility Segregation）** 模式：

- **概念来源**：Greg Young "CQRS Documents" (2010)
- **核心思想**：读写分离，不同查询类型使用不同的数据模型
- **参考网址**：https://martinfowler.com/bliki/CQRS.html

**应用到本系统**：

1. **PostgreSQL 用于"事实查询"（Fact Query）**
   - 场景：统计、过滤、聚合
   - 例子："查询中国有多少个 AS"
   - 查询模式：`SELECT COUNT(*) FROM as_entity WHERE country = 'CN'`

2. **Neo4j 用于"关系推理"（Relationship Reasoning）**
   - 场景：多跳路径、拓扑分析
   - 例子："AS4134 的上游的上游是谁"
   - 查询模式：`MATCH (a:AS {asn: 4134})-[:UPSTREAM*2]->(b:AS)`

3. **Milvus 用于"语义检索"（Semantic Retrieval）**
   - 场景：文档问答、概念解释
   - 例子："什么是 BGP 劫持"
   - 查询模式：向量相似度搜索 Top-K

**类似架构的业界参考**：

- **LinkedIn 的 Espresso + Voldemort + Search**：
  - Espresso（MySQL）用于事务查询
  - Voldemort（KV Store）用于低延迟读取
  - Search（Lucene）用于全文检索
  - 论文：Qiao et al. "On Brewing Fresh Espresso: LinkedIn's Distributed Data Serving Platform" (SIGMOD 2013)
  - 网址：https://engineering.linkedin.com/espresso/introducing-espresso-linkedins-hot-new-distributed-document-store

- **Netflix 的 Cassandra + Elasticsearch + EVCache**：
  - Cassandra 用于时序数据
  - Elasticsearch 用于日志检索
  - EVCache 用于缓存
  - 参考博客：https://netflixtechblog.com/netflix-recommendations-beyond-the-5-stars-part-1-55838468f429

**为什么不用统一的"多模数据库"（Multi-Model Database）？**

统一多模数据库（如 ArangoDB、OrientDB）理论上可以同时支持文档、图、KV，但实际存在问题：

1. **性能折衷**：每种模式的性能都不如专用数据库
   - 参考测试：Angles et al. "The LDBC Social Network Benchmark" (2020)
   - 结论：多模数据库在图查询性能上比 Neo4j 慢 30-50%

2. **生态不成熟**：工具链、监控、运维经验不如 PostgreSQL/Neo4j/Milvus
3. **风险集中**：单点故障影响所有数据类型

### 2.2 双重图谱设计

**静态领域图谱**：数据驱动，固定 Schema

节点类型：
- `(:AS {asn, org_name, org_country, type, as_rank, ...})`
- `(:Org {uuid, org_name, org_name_cn, org_country, ...})`
- `(:Country {country, country_cn, population, ...})`
- `(:Prefix {cidr, prefix_len, country, ...})`
- `(:Website {url, title, industry, ...})`
- `(:Industry {name, parent, description, ...})`

关系类型：
```cypher
// AS 拓扑关系
(:AS)-[:V4_UPSTREAM]->(:AS)      // IPv4 上游
(:AS)-[:V4_PEER]->(:AS)          // IPv4 对等
(:AS)-[:V4_DOWNSTREAM]->(:AS)    // IPv4 下游
(:AS)-[:V6_UPSTREAM]->(:AS)      // IPv6 上游（独立维度）

// 归属关系
(:AS)-[:BELONGS_TO]->(:Org)       // AS 属于组织
(:Org)-[:LOCATED_IN]->(:Country)  // 组织所在国
(:AS)-[:LOCATED_IN]->(:Country)   // AS 地理分布

// 前缀关系
(:Prefix)-[:BGP_ORIGIN]->(:AS)       // BGP 观测归属
(:Prefix)-[:REG_ORIGIN]->(:AS)       // 注册归属
(:Prefix)-[:REGISTERED_TO]->(:Org)   // 前缀注册组织
(:Prefix)-[:IN_COUNTRY]->(:Country)  // 前缀所在国

// 应用层关系
(:Website)-[:RESOLVES_TO]->(:Prefix)      // 域名解析
(:Website)-[:HOSTED_BY_AS]->(:AS)         // 托管 AS
(:Website)-[:HOSTED_BY_ORG]->(:Org)       // 托管组织
(:Website)-[:IN_INDUSTRY]->(:Industry)    // 所属行业
(:Industry)-[:PARENT_OF]->(:Industry)     // 行业层级
```

**动态语义记忆图**：对话驱动，动态生成

节点类型：
- `(:Concept {name, description, metadata})`

生成时机（参考 `agent/runtime/fusion_agent.py:472-492`）：
```python
def _maybe_write_semantic_memory(self, user_message: str, answer: str, root_run) -> None:
    """
    从对话中抽取概念节点写入 Neo4j
    
    触发条件：
    1. semantic_memory_enabled = true
    2. 对话包含有效信息（非空回复）
    3. LLM 成功抽取出 importance >= min_importance 的概念
    """
    if not self.semantic_memory_enabled:
        return
    if not answer.strip():
        return
    records = self._extract_semantic_records(user_message, answer)
    if not records:
        return
    # 写入 Neo4j（agent/memory/semantic.py:73-96）
    self._write_semantic_records(records)
```

抽取示例（使用 Structured Output）：
```json
// 输入对话
User: "我关注博彩行业的 ASN"
Assistant: "博彩行业主要集中在..."

// LLM 抽取结果
{
  "items": [
    {
      "concept": "关注行业-ASN画像",
      "description": "用户关注博彩行业相关ASN与归属链路",
      "importance": 0.81,
      "category": "preference",
      "metadata": {"tags": ["博彩", "asn", "偏好"]}
    }
  ]
}
```

### 2.3 图谱索引与优化策略

**索引创建**（`agent/scripts/neo4j_graph_loader.py:133-140`）：
```python
def _create_constraints(session, include_website: bool, include_industry: bool) -> None:
    # 唯一约束（自动创建索引）
    session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (a:AS) REQUIRE a.asn IS UNIQUE")
    session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (o:Org) REQUIRE o.uuid IS UNIQUE")
    session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Country) REQUIRE c.country IS UNIQUE")
    session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (p:Prefix) REQUIRE p.cidr IS UNIQUE")
    if include_website:
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (w:Website) REQUIRE w.url IS UNIQUE")
    if include_industry:
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (i:Industry) REQUIRE i.name IS UNIQUE")
```

**查询优化原则**：
1. **强制 LIMIT**：避免全图扫描
2. **索引覆盖**：主键查询必走索引（`MATCH (a:AS {asn: 4134})`）
3. **关系方向**：明确关系方向减少候选路径（`-[:V4_UPSTREAM]->`）
4. **WHERE 过滤前置**：先过滤节点再 MATCH 关系

## [代码映射]

### 2.1 图谱装载流程

**核心入口**：`agent/scripts/neo4j_graph_loader.py`

**数据流水线**：
```
PostgreSQL (16张核心表)
    ↓ _stream_query (分批读取)
[Country] → _load_countries → Neo4j (:Country)
[Org]     → _load_orgs      → Neo4j (:Org)
[AS]      → _load_as_nodes  → Neo4j (:AS)
[Prefix]  → _load_prefix_*  → Neo4j (:Prefix)
[Website] → _load_website_* → Neo4j (:Website)
```

**批量写入优化**（`agent/scripts/neo4j_graph_loader.py:115-123`）：
```python
def _write_nodes(session, label: str, key: str, rows: List[Dict[str, Any]]) -> None:
    """
    使用 UNWIND 批量写入节点
    
    优势：
    - 单次事务写入多行（batch_size=1000）
    - 使用 MERGE 避免重复节点
    - SET 更新节点属性
    """
    if not rows:
        return
    cypher = (
        f"UNWIND $rows AS row "
        f"MERGE (n:{label} {{{key}: row.{key}}}) "
        f"SET n += row"
    )
    session.execute_write(lambda tx: tx.run(cypher, rows=rows))
```

**关系写入示例**（`agent/scripts/neo4j_graph_loader.py:287-301`）：
```python
def _flush_as_relations(session, rows: List[Dict[str, Any]]) -> None:
    """
    批量写入 AS 拓扑关系
    
    挑战：Neo4j 的关系类型不能参数化
    解决：按关系类型分组，动态拼接 Cypher
    """
    if not rows:
        return
    # 按关系类型分组
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["rel"], []).append(row)
    # 分别写入
    for rel_type, rel_rows in grouped.items():
        rel_cypher = (
            "UNWIND $rows AS row "
            "MERGE (a:AS {asn: row.from_asn}) "
            "MERGE (b:AS {asn: row.to_asn}) "
            f"MERGE (a)-[:{rel_type}]->(b)"
        )
        _write_relationships(session, rel_cypher, rel_rows)
```

### 2.2 向量检索工具与数据策略（RAG）

**核心实现文件**：
- 检索与索引：`agent/tools/rag_tool.py`
- 知识入库：`agent/knowledge_ingest.py`
- MCP 暴露：`agent/mcp/server.py` 的 `rag_search`

#### 2.2.1 数据入口与文档切分（Chunk）

当前入库支持三类文件（`agent/knowledge_ingest.py:34`）：
- `.md`
- `.txt`
- `.docx`

切分策略（`agent/knowledge_ingest.py:60-83`）：
- 使用 `llama_index.core.node_parser.SentenceSplitter`
- 默认参数：`chunk_size=800`、`chunk_overlap=100`（CLI 可改）
- 每个切片保留 `source`、`file_name` 等元数据，确保可追溯

典型命令（可直接调参）：
```bash
python agent/knowledge_ingest.py \
  --root . \
  --path agent/knowledge \
  --chunk-size 800 \
  --chunk-overlap 100 \
  --reset
```

#### 2.2.2 向量索引与检索参数

Milvus Collection 结构（`agent/tools/rag_tool.py:141-151`）：
- `id`：INT64 主键（auto_id）
- `embedding`：FLOAT_VECTOR（维度由 embedding 探测）
- `text`：VARCHAR(65535)
- `source`：VARCHAR(512)

向量索引参数（当前实现）：
- `index_type=IVF_FLAT`
- `metric_type=COSINE`
- `nlist=128`

检索参数（当前实现）：
- `nprobe=10`
- `top_k` 默认 5（可由路由层传入）

Embedding 侧优化（`agent/tools/rag_tool.py:66-76`）：
- 百炼 Embedding 批大小固定为 10，避免单请求过大导致接口报错

#### 2.2.3 召回与重排策略（现状）

**当前召回策略**（已实现）：
1. `query -> embedding` 生成查询向量
2. Milvus 向量召回 Top-K（余弦相似）
3. 返回 `text/source/score`

**当前重排策略**（现状说明）：
- 当前主链路未引入 Cross-Encoder / BGE-Reranker 等“二阶段重排模型”
- 结果顺序主要依赖 Milvus 相似度排序
- 后续上下文构建（GSSC）会对证据统一赋分并参与上下文压缩，但这不是严格的语义重排

#### 2.2.4 可落地优化建议（按优先级）

1. `Chunk` 策略按文档类型分层  
   说明：规范文档可增大 `chunk_size`；FAQ/说明书可减小 `chunk_size` 提升命中精度。

2. 召回扩展 + 重排二阶段  
   说明：先召回 `top_k=20~50` 候选，再用 reranker 压到 5~8 条，通常比“直接 top_k=5”更稳。

3. 相似度分数参与最终证据排序  
   说明：将 Milvus `score` 映射到 Evidence 分值，避免上下文阶段忽略向量相似度差异。

4. 混合检索（向量 + 关键词）  
   说明：对专有名词（ASN、前缀、组织名）可加 BM25/关键词召回，再与向量结果融合。

5. 索引参数按数据规模调优  
   说明：百万级切片可调大 `nlist`，并按延迟目标调 `nprobe`；当前值可作为 baseline。

### 2.3 记忆系统调度

**统一管理器**：`agent/memory/manager.py`

```python
class MemoryManager:
    """
    三类记忆的统一调度
    
    - 工作记忆：WorkingMemory (内存 deque，容量受限)
    - 情景记忆：EpisodicMemory (PostgreSQL 持久化)
    - 语义记忆：SemanticMemory (Neo4j 图谱)
    """
    
    def __init__(self, working_memory, episodic_memory, semantic_memory):
        self.working_memory = working_memory
        self.episodic_memory = episodic_memory
        self.semantic_memory = semantic_memory
    
    def add_memory(self, item: MemoryItem) -> None:
        """
        按类型路由写入
        
        来自 agent/memory/manager.py:69-91
        """
        if item.memory_type == "working":
            self.working_memory.add(item)
        elif item.memory_type == "episodic":
            self.episodic_memory.add(item)
        elif item.memory_type == "semantic":
            self.semantic_memory.add(item)
        else:
            self.working_memory.add(item)  # 默认写入工作记忆
    
    def search(self, query: str, top_k: int = 5) -> List[MemoryItem]:
        """
        三路召回 + 统一排序
        
        来自 agent/memory/manager.py:93-116
        """
        results = []
        results.extend(self.working_memory.search(query, top_k=top_k))
        results.extend(self.episodic_memory.search(query, top_k=top_k))
        results.extend(self.semantic_memory.search(query, top_k=top_k))
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]
```

**语义记忆抽取**：`agent/runtime/fusion_agent.py`

```python
def _extract_semantic_records(self, user_message: str, answer: str) -> List[SemanticRecord]:
    """
    从对话中抽取结构化概念
    
    来自 agent/runtime/fusion_agent.py:494-531
    
    提示词策略（SEMANTIC_EXTRACT_PROMPT）：
    "从对话中抽取长期记忆条目，输出JSON数组：
    [
      {
        "concept": "概念名称",
        "description": "详细描述",
        "importance": 0.0-1.0,
        "category": "类别"
      }
    ]"
    """
    prompt = [
        LLMMessage(role="system", content=SEMANTIC_EXTRACT_PROMPT),
        LLMMessage(role="user", content=f"用户问题：{user_message}\n助手回答：{answer}\n请抽取语义记忆条目。"),
    ]
    try:
        raw = self.llm.structured_chat(prompt, schema={"type": "array"})
    except Exception:
        return []
    
    # 解析并过滤低重要性项
    records: List[SemanticRecord] = []
    for item in raw if isinstance(raw, list) else raw.get("items", []):
        if not isinstance(item, dict):
            continue
        concept = str(item.get("concept", "")).strip()
        description = str(item.get("description", "")).strip()
        importance = float(item.get("importance", 0.0))
        if importance < self.semantic_memory_min_importance:
            continue
        records.append(SemanticRecord(
            concept=concept,
            description=description,
            metadata={
                "category": item.get("category", ""),
                "source": "semantic_extract",
                "importance": importance
            }
        ))
    return records
```

## [实战 I/O 示例]

### 示例 1：Text2Cypher 完整链路

**用户输入**：`查找 AS4134 的上游`

**步骤 1：路由决策（FusionAgent → graph_relations 子代理）**

主代理判断该问题需要图谱推理，生成 A2A 任务载荷：
```json
{
  "agent": "supervisor",
  "objective": "查找 AS4134 的上游传输路径",
  "constraints": {
    "tools_allowed": ["graph_relations"]
  },
  "context": {"question": "查找 AS4134 的上游"}
}
```

**步骤 2：graph_relations 子代理生成 Cypher**

子代理调用 LLM 生成查询：
```cypher
// 方案 1：基于 BGP_ORIGIN 关系推断上游
MATCH (a:AS {asn: 4134})<-[:BGP_ORIGIN]-(p:Prefix)-[:BGP_ORIGIN]->(up:AS)
WHERE up.asn <> 4134
RETURN 
    a.asn AS target_asn,
    a.org_name AS target_org,
    up.asn AS upstream_asn,
    up.org_name AS upstream_org,
    count(p) AS shared_prefixes
ORDER BY shared_prefixes DESC
LIMIT 50;

// 方案 2：直接使用 V4_UPSTREAM 关系（如已导入）
MATCH (a:AS {asn: 4134})-[:V4_UPSTREAM]->(up:AS)
RETURN 
    a.asn AS target_asn,
    up.asn AS upstream_asn,
    up.org_name AS upstream_org,
    up.as_country AS upstream_country
LIMIT 50;
```

**步骤 3：Neo4j 执行返回**

Graph Record 结构（Python dict）：
```python
{
  "columns": ["target_asn", "upstream_asn", "upstream_org", "shared_prefixes"],
  "rows": [
    {
      "target_asn": 4134,
      "upstream_asn": 3356,
      "upstream_org": "Level3 Parent, LLC",
      "shared_prefixes": 182
    },
    {
      "target_asn": 4134,
      "upstream_asn": 174,
      "upstream_org": "Cogent Communications",
      "shared_prefixes": 97
    },
    {
      "target_asn": 4134,
      "upstream_asn": 1299,
      "upstream_org": "Telia Company AB",
      "shared_prefixes": 54
    }
  ],
  "row_count": 3,
  "truncated": false
}
```

**步骤 4：格式化返回用户**

最终回复：
```text
AS4134 的主要上游提供商包括：

1. AS3356 (Level3 Parent, LLC)
   - 共享前缀数：182

2. AS174 (Cogent Communications)
   - 共享前缀数：97

3. AS1299 (Telia Company AB)
   - 共享前缀数：54

这些上游 AS 通过 BGP 为 AS4134 提供全球传输路径。
```

### 示例 2：语义记忆抽取与召回

**场景 1：写入语义记忆**

用户对话：
```
User: "我需要重点关注博彩行业的 ASN 归属情况"
Assistant: "博彩行业的 ASN 主要集中在菲律宾、柬埔寨等东南亚地区..."
```

抽取结果（`agent/runtime/fusion_agent.py:494-531`）：
```json
[
  {
    "concept": "关注行业-ASN画像",
    "description": "用户关注博彩行业相关ASN与归属链路，重点区域：东南亚",
    "importance": 0.81,
    "category": "preference",
    "metadata": {
      "tags": ["博彩", "asn", "东南亚", "偏好"],
      "source": "semantic_extract"
    }
  }
]
```

写入 Neo4j（`agent/memory/semantic.py:73-96`）：
```cypher
MERGE (c:Concept {name: "关注行业-ASN画像"})
SET c.description = "用户关注博彩行业相关ASN与归属链路，重点区域：东南亚",
    c.metadata = {
      "tags": ["博彩", "asn", "东南亚", "偏好"],
      "source": "semantic_extract",
      "importance": 0.81,
      "category": "preference"
    },
    c.updated_at = datetime()
```

**场景 2：召回语义记忆**

用户新对话：
```
User: "查询菲律宾的 ASN 分布"
```

系统召回（`agent/memory/semantic.py:98-122`）：
```cypher
MATCH (c:Concept)
WHERE toLower(c.name) CONTAINS toLower($query)
   OR toLower(c.description) CONTAINS toLower($query)
RETURN c.name AS name, c.description AS description, c.metadata AS metadata
LIMIT 5

// 参数：query = "菲律宾"
```

召回结果：
```python
[
  MemoryItem(
    content="用户关注博彩行业相关ASN与归属链路，重点区域：东南亚",
    memory_type="semantic",
    metadata={
      "concept": "关注行业-ASN画像",
      "metadata": {
        "tags": ["博彩", "asn", "东南亚", "偏好"],
        "importance": 0.81
      }
    },
    score=1.0
  )
]
```

系统响应：
```text
根据您之前的关注偏好（博彩行业），菲律宾的 ASN 分布如下：
[调用 NL2SQL 查询具体数据]
```

### 示例 3：混合检索协同

**用户问题**：`AS4134 属于哪个组织？该组织有哪些其他 ASN？这类组织的运营模式是什么？`

**三引擎协同**：

**步骤 1：PostgreSQL（事实查询）**
```sql
-- NL2SQL 生成
SELECT 
    asn,
    org_name,
    org_name_cn,
    uuid,
    org_country
FROM as_entity
WHERE asn = 4134
LIMIT 1;
```

结果：
```text
asn  | org_name                      | org_name_cn  | uuid                                 | org_country
4134 | CHINANET-BACKBONE             | 中国电信骨干网 | 550e8400-e29b-41d4-a716-446655440000 | CN
```

**步骤 2：Neo4j（关系推理）**
```cypher
// 查询同组织的其他 ASN
MATCH (o:Org {uuid: '550e8400-e29b-41d4-a716-446655440000'})<-[:BELONGS_TO]-(a:AS)
RETURN a.asn AS asn, a.org_name AS org_name
ORDER BY a.asn
LIMIT 20;
```

结果：
```text
asn   | org_name
4134  | CHINANET-BACKBONE
4809  | CHINANET-SH
4811  | CHINANET-GD
17799 | CHINANET-HN
```

**步骤 3：Milvus（文档检索）**

查询：`中国电信骨干网运营模式`

召回文档片段：
```text
[文档1] 中国电信是中国三大电信运营商之一，其骨干网承担全国互联网流量传输...
[文档2] Tier-1 网络通常指无需购买上游传输的全球顶级运营商，如中国电信国际...
[文档3] AS4134 通过多个国际对等点与全球主流运营商建立直连...
```

**步骤 4：融合回复**
```text
AS4134 属于 CHINANET-BACKBONE（中国电信骨干网），该组织在中国拥有多个区域 ASN：
- AS4809 (上海)
- AS4811 (广东)
- AS17799 (湖南)
...

运营模式：
中国电信作为 Tier-1 级别的全球运营商，骨干网承担国内主干流量传输，并通过
多个国际对等点与全球主流运营商建立直连，无需购买上游传输。

[证据来源]
- 事实数据：as_entity 表
- 关系推理：Neo4j Org-AS 关系
- 背景知识：knowledge/telecom/tier1_operators.md
```

## [面试攻防]

### 问题 1：节点百万级时怎么控图查询延迟？

**回答要点 1**：**固定查询模板 + 只读 guard**
```python
# 限制 Cypher 形态，禁止用户自由输入
ALLOWED_PATTERNS = [
    "MATCH (a:AS {asn: $asn})-[:V4_UPSTREAM]->(up:AS) RETURN ...",
    "MATCH (p:Prefix {cidr: $cidr})-[:BGP_ORIGIN]->(a:AS) RETURN ..."
]

def sanitize_cypher(cypher: str) -> str:
    # 禁止 DETACH DELETE、SET、CREATE 等写操作
    if re.search(r'\b(DELETE|SET|CREATE|MERGE|REMOVE)\b', cypher, re.I):
        raise ValueError("Write operations are not allowed")
    return cypher
```

**回答要点 2**：**强制 LIMIT 与返回字段裁剪**
```python
def enforce_limit(cypher: str, max_rows: int = 100) -> str:
    # 自动添加或收敛 LIMIT
    if not re.search(r'\bLIMIT\s+\d+', cypher, re.I):
        cypher = f"{cypher} LIMIT {max_rows}"
    else:
        cypher = re.sub(
            r'\bLIMIT\s+(\d+)',
            lambda m: f"LIMIT {min(int(m.group(1)), max_rows)}",
            cypher,
            flags=re.I
        )
    return cypher
```

**回答要点 3**：**高频关系预建索引**

已创建的约束（自动带索引）：
```cypher
CREATE CONSTRAINT FOR (a:AS) REQUIRE a.asn IS UNIQUE;
CREATE CONSTRAINT FOR (p:Prefix) REQUIRE p.cidr IS UNIQUE;
CREATE CONSTRAINT FOR (o:Org) REQUIRE o.uuid IS UNIQUE;
```

查询优化示例：
```cypher
// ❌ 慢查询：无索引覆盖
MATCH (a:AS)
WHERE a.as_rank < 1000
RETURN a;

// ✅ 快查询：索引覆盖 + LIMIT
MATCH (a:AS {asn: 4134})
RETURN a LIMIT 1;
```

**回答要点 4**：**统计类下推 PostgreSQL**
```text
错误做法：
Cypher: MATCH (a:AS)-[:BELONGS_TO]->(o:Org) RETURN o.org_name, count(a) AS asn_count

正确做法：
SQL: SELECT org_name, COUNT(*) AS asn_count FROM as_entity GROUP BY org_name
（PostgreSQL 的 GROUP BY 性能远超 Neo4j）
```

### 问题 2：为什么需要双重图谱？单一图谱不够吗？

**回答逻辑**：

**静态领域图谱**：
- 来源：PostgreSQL 16 张核心表批量导入
- 特点：Schema 固定，节点/关系类型明确
- 优势：支持复杂多跳查询（AS → Prefix → Org → Country）
- 劣势：无法动态扩展，不适合存储用户偏好

**动态语义记忆图**：
- 来源：对话实时抽取
- 特点：Schema 灵活，仅 `(:Concept)` 节点
- 优势：捕捉用户偏好、上下文信息、长期记忆
- 劣势：无法用于精确事实查询

**协同场景**：
```text
用户问题："再次查询我上次关注的那个 AS"

静态图谱无法回答（没有"上次关注"记录）
↓
动态记忆召回：Concept {name: "关注的AS", description: "AS4134"}
↓
静态图谱查询：MATCH (a:AS {asn: 4134}) RETURN a
```

### 问题 3：Milvus 向量检索和 PostgreSQL pgvector 有什么区别？

**技术对比**：

| 维度 | Milvus | PostgreSQL pgvector |
|------|--------|---------------------|
| **索引算法** | HNSW, IVF_FLAT, IVF_PQ | IVF |
| **性能（百万级）** | <50ms (HNSW) | 100-500ms |
| **内存占用** | 可配置（磁盘+内存混合） | 全内存或频繁磁盘 IO |
| **水平扩展** | 原生分布式 | 需手动分片 |
| **运维复杂度** | 独立服务（etcd+minio依赖） | 集成在 PostgreSQL |

**选型依据**：
- **数据量 < 10 万向量**：pgvector 足够（减少组件）
- **数据量 > 100 万向量**：Milvus（性能+扩展性）
- **已有 PostgreSQL**：优先 pgvector（降低架构复杂度）
- **需要向量管理功能**：Milvus（版本管理、分区、副本）

### 问题 4：如何评估语义记忆抽取的质量？

**评估维度**：

**1. 重要性阈值（importance >= 0.6）**
```python
# 来自 agent/runtime/fusion_agent.py:520
if importance < self.semantic_memory_min_importance:
    continue  # 过滤低重要性项
```

**2. 抽取成功率**
```python
# 监控指标
total_dialogues = 100
extracted_concepts = 62
extraction_rate = 62 / 100 = 0.62  # 目标 > 0.5
```

**3. 召回精度**
```python
# A/B 测试
# 场景：用户提到"博彩"时是否召回相关 Concept
precision = relevant_recalls / total_recalls
```

**4. 噪声率（错误抽取）**
```text
示例噪声：
User: "今天天气不错"
抽取: Concept {name: "天气", ...}  # 与业务无关，应过滤
```

**优化方案**：
```python
# 在抽取提示词中增加过滤规则
SEMANTIC_EXTRACT_PROMPT = """
仅抽取与互联网号码资源、网络拓扑、AS 归属相关的概念。
忽略：天气、问候、无关闲聊。
"""
```

---

**技术深度总结**：
- 三引擎混合架构各司其职：PostgreSQL 统计、Neo4j 推理、Milvus 文档
- 双重图谱设计：静态领域图谱（数据驱动）+ 动态语义记忆（对话驱动）
- 图谱查询优化：索引覆盖 + 强制 LIMIT + 统计下推 PostgreSQL
- 语义记忆抽取：重要性过滤 + 业务相关性校验 + 召回精度监控
