# 互联网号码资源问答系统 - 系统架构深度解析

> **目标读者**：准备技术面试的开发者、系统架构师、AI 工程师  
> **文档定位**：通过具体的输入输出（I/O）数据流，展示系统底层逻辑的绝对掌控

## 核心价值

这套文档将帮助你：

1. **掌握核心模块**：从数据融合到 GraphRAG、从 Multi-Agent 编排到 Text2SQL 安全防御
2. **理解 I/O 链路**：每个示例都展示 Raw Input → 中间处理 → Final Output 的完整数据流
3. **应对面试攻防**：每章末尾提供高频面试问题及技术深度回答要点
4. **代码映射明确**：关键逻辑都标注了对应的代码文件和行号
5. **设计理由清晰**：每个技术选型都附带理论依据、学术参考、业界最佳实践和对比分析
6. **可追溯性强**：所有设计决策都提供参考文献、论文链接、开源项目网址

## 文档特色：深度解析设计理由

**与其他技术文档的区别**：

大多数技术文档只告诉你"怎么做（How）"和"做了什么（What）"，但本文档重点解释**"为什么这样做（Why）"**：

### ✅ 本文档提供的深度内容：

1. **理论基础**：每个架构设计都追溯到学术理论
   - 双轨并行架构 → RFC 2050、RFC 4271、CAIDA 研究
   - 多语言持久化 → Martin Fowler 的 Polyglot Persistence
   - 零信任架构 → NIST SP 800-207

2. **选型对比**：为什么选 A 而不选 B/C/D
   - PostgreSQL vs Neo4j vs Milvus：技术对比矩阵
   - LlamaIndex vs LangChain：功能差异分析
   - text-embedding-v3 vs bge-large-zh：成本-质量权衡

3. **学术参考**：所有设计都基于业界研究
   - 70+ 篇论文引用（SIGMOD、VLDB、EMNLP、arXiv）
   - 20+ 个开源项目参考（LangChain、LlamaIndex、Neo4j）
   - 10+ 个业界案例（LinkedIn、Netflix、CAIDA）

4. **实验验证**：不只是理论，还有实测数据
   - Chunk Size 800 tokens：基于 A/B 测试的最优值
   - Overlap 100 tokens：实验证明提升 Hit@5 达 11%
   - 向量维度 1536：性能-成本平衡点的量化分析

5. **可追溯性**：所有引用都提供网址
   - 论文链接（arXiv、ACM、IEEE）
   - RFC 标准链接（IETF）
   - 开源项目链接（GitHub）
   - 技术博客链接（Engineering Blogs）

### ❌ 其他文档常见的问题：

- ❌ 只贴代码，不解释为什么这样设计
- ❌ 缺少技术选型的对比分析
- ❌ 没有学术或业界参考
- ❌ 设计决策没有数据支撑

## 文档结构

### [Chapter 1: 领域数据融合与组织](./chapter_1_data_foundation.md)
**Data Foundation - 系统的数据底座**

**核心内容**：
- 双轨并行架构：注册侧（RIR/WHOIS）vs 观测侧（BGP）
- 16 张核心表设计原则：委托层 → 注册层 → 观测层 → 聚合层 → 应用层
- 多值字段编码：Python 列表 → PostgreSQL Array 转换链路
- CSV 导入流程：解析 → 清洗 → 幂等写入

**实战 I/O 示例**：
- Raw CSV 行 → PostgreSQL Row（完整数据流）
- 多源冲突检测：注册归属 vs BGP 观测归属
- JSON 字段查询：联系人信息提取

**面试攻防**：
- 多源数据冲突怎么处理？
- 为什么是 16 张核心表？
- CSV 中的 Python 列表字符串为什么不直接用 JSON？
- 如何保证 CSV 导入的幂等性？

---

### [Chapter 2: GraphRAG 与混合检索架构](./chapter_2_graphrag_hybrid_retrieval.md)
**The Brain - 三引擎混合检索**

**核心内容**：
- 三引擎架构：PostgreSQL（统计） + Neo4j（关系推理） + Milvus（文档）
- 双重图谱设计：静态领域图谱（数据驱动）+ 动态语义记忆（对话驱动）
- 图谱索引优化：唯一约束 + 强制 LIMIT + 索引覆盖
- RAG 数据策略：SentenceSplitter 分块、Milvus IVF_FLAT 检索、召回与重排优化路径
- 记忆系统调度：三路召回（工作记忆 + 情景记忆 + 语义记忆）

**实战 I/O 示例**：
- Text2Cypher 完整链路：自然语言 → Cypher Query → Neo4j Record
- 语义记忆抽取与召回：对话 → Concept 节点 → 图谱存储
- 混合检索协同：PostgreSQL + Neo4j + Milvus 三引擎融合回复

**面试攻防**：
- 节点百万级时怎么控图查询延迟？
- 为什么需要双重图谱？
- Milvus 向量检索和 PostgreSQL pgvector 有什么区别？
- RAG 的 chunk 如何划分？为什么是 800/100？
- 召回与重排怎么设计？当前系统做到哪一步？
- 如何评估语义记忆抽取的质量？

---

### [Chapter 3: Multi-Agent 编排与工具协议](./chapter_3_multi_agent_orchestration.md)
**The Hands - 协议驱动编排**

**核心内容**：
- 协议驱动架构：工具层 FastMCP（HTTP） + 代理间 A2A（HTTP+SSE）
- 两阶段 Function Calling：先 `route_plan`，再 `route_step_tool`
- MCP vs A2A：单一工具执行 vs 复杂任务编排
- LangSmith 追踪：全链路可观测

**实战 I/O 示例**：
- 计划决策：用户问题 → Function Calling（plan-only）→ ToolRouterDecision JSON
- 单步动作决策：PlanStep → Function Calling（step-action）→ ToolActionStep JSON
- TodoItem → A2A 载荷：任务拆解 → 标准化载荷 → Worker 执行
- MCP vs A2A 调用对比：协议级别的差异

**面试攻防**：
- 为什么 Function Calling + Protocol，不用传统 ReAct Loop？
- MCP 和 A2A 的边界在哪里？
- 如果 A2A Worker 宕机，主代理如何降级？
- LangSmith 追踪在协议调用中如何传递？

---

### [Chapter 4: Text2SQL 引擎与安全防御](./chapter_4_text2sql_safety.md)
**The Logic - SQL 生成与安全围栏**

**核心内容**：
- 生成 → 校验 → 执行：三段式安全链路
- Schema 注入策略：表结构 + 业务语义 + 列值提示
- 向量检索优化：表/列双重索引 + Milvus 持久化 + 内存缓存
- SQLGuard 安全围栏：禁写操作 + 禁多语句 + 禁危险函数 + 强制 LIMIT

**实战 I/O 示例**：
- Schema 注入片段：如何引导 LLM 使用正确字段
- SQL 生成与 Guard 防护：原始 SQL vs 安全 SQL
- 向量检索辅助：枚举值匹配 → 精确 SQL 生成
- 索引缓存加速：首次 8.5 秒 vs 缓存命中 0.4 秒（20 倍提速）

**面试攻防**：
- 如何防止 SQL 注入？
- 大表 JOIN 慢怎么处理？
- 向量检索索引多大？如何优化？
- 如果 LLM 生成的 SQL 语法错误，如何处理？

---

### [Chapter 5: RAG 系统深度解析](./chapter_5_rag_deep_dive.md)
**RAG 完整链路 - 从文档到答案**

**核心内容**：
- RAG 完整流程：文档解析 → 分块 → 向量化 → 索引构建 → 召回 → 重排 → 生成
- 分块策略：LlamaIndex SentenceSplitter（800 tokens, 100 overlap），语义边界切分
- 向量模型选型：阿里云百炼 text-embedding-v3（1536 维），成本低、质量高
- 索引与检索：Milvus IVF_FLAT + COSINE，支持 10 万-100 万规模
- GraphRAG 设计：文档（chunk）+ 图谱（关系）混合，解决多跳推理问题
- 评估体系：Hit Rate（0.87）、NDCG（0.81）、Faithfulness（0.92）
- 增量更新：追加索引 + Hash 去重 + 定期全量重建

**实战 I/O 示例**：
- 完整索引构建链路：原始 Markdown → 分块 → 向量 → Milvus 存储
- 查询与召回：用户问题 → 向量检索 → Top-K 结果 → Prompt 构建
- GraphRAG 协同：向量召回（文档）+ 图遍历（关系）→ 融合生成
- 增量更新验证：新文档追加 → 召回测试

**面试攻防**：
- 为什么选 800 tokens 作为 chunk_size？
- 为什么不用重排（Reranking）？
- 如何评估 RAG 系统？如何定位问题？
- GraphRAG 和传统 RAG 的核心区别是什么？
- 如何处理增量更新？

---

## 如何使用这套文档

### 面试前准备（推荐流程）

1. **第一轮（3 小时）**：快速通读四个章节，理解系统整体架构
2. **第二轮（5 小时）**：深入阅读每章的"实战 I/O 示例"，在纸上画出数据流
3. **第三轮（2 小时）**：针对"面试攻防"部分，准备自己的回答话术
4. **第四轮（1 小时）**：结合代码映射，快速浏览关键代码文件，验证理解

### 面试中使用

当面试官问到具体问题时，使用以下结构回答：

```text
[核心机制] 简述原理（30 秒）
    ↓
[代码映射] 关键代码在哪（10 秒）
    ↓
[实战 I/O] 举具体例子（1 分钟）
    ↓
[技术深度] 扩展讨论（可选，30 秒）
```

**示例问题**：如何防止 SQL 注入？

**回答示范**：
```text
[核心机制]
我们采用 SQLGuard 安全围栏，在执行前校验 SQL。

[代码映射]
实现在 agent/tools/nl2sql_tool.py:251-383，核心是 sanitize() 方法。

[实战 I/O]
举个例子，用户输入"删除所有数据"，LLM 生成 DELETE 语句，
SQLGuard 检测到关键字黑名单中的 "delete"，直接抛异常拒绝执行。

我们有五层防御：
1. 禁止多语句（检测分号）
2. 禁止危险关键字（delete/drop/alter）
3. 禁止危险函数（pg_sleep）
4. 表白名单校验
5. 限制 SQL 长度

[技术深度]
除此之外，我们还配合了表白名单和强制 LIMIT，即使绕过关键字检测，
也无法访问系统表或返回超过 200 行的数据。
```

---

## 技术栈总览

### 数据层
- **PostgreSQL**：16 张核心表，存储结构化事实
- **Neo4j**：属性图谱，存储关系与拓扑
- **Milvus**：向量数据库，存储文档嵌入

### 智能体层
- **LLM**：阿里云百炼（Qwen 系列）
- **Embedding**：text-embedding-v3（1536 维）
- **Framework**：LlamaIndex（Text2SQL）、LangChain（文档分块）

### 编排层
- **MCP**：FastMCP（工具层协议，HTTP）
- **A2A**：自定义协议（代理间，HTTP+SSE）
- **Tracing**：LangSmith（全链路追踪）

### 部署层
- **API**：FastAPI（`agent/interfaces/http/server.py`，端口 2025）
- **MCP Server**：Uvicorn（端口 2032）
- **A2A Worker**：Uvicorn（端口 2031）
- **Frontend**：Agent Chat UI（端口 3012，可选）

---

## 关键指标

### 性能指标
- **NL2SQL 首次查询**：8.5 秒（含索引构建）
- **NL2SQL 缓存命中**：0.4 秒（提速 20 倍）
- **Neo4j 图谱查询**：<50ms（百万节点，索引覆盖）
- **Milvus 向量检索**：<100ms（100 万文档，HNSW 索引）

### 数据规模
- **PostgreSQL**：16 张核心表，约 500 万行（AS 实体 + 前缀）
- **Neo4j**：约 200 万节点（AS/Prefix/Org/Country），500 万关系
- **Milvus**：约 10 万文档片段（知识库）

### 安全指标
- **SQL 注入防御**：5 层防护，0 漏洞（人工测试）
- **访问控制**：表白名单 + 强制 LIMIT，无越权查询
- **降级策略**：A2A 服务不可用时，自动降级为 MCP 直接调用

---

## 进阶学习

### 推荐阅读顺序
1. **系统架构**：`README.md`（当前文档）→ `summary.md`（16 表设计）
2. **部署运维**：`docs/互联网号码资源问答系统技术文档.md`
3. **代理构建**：`docs/子代理构建.md`
4. **代码实现**：`agent/runtime/fusion_agent.py`（主编排）→ `agent/tools/nl2sql_tool.py`（NL2SQL）

### 动手实践
1. **本地部署**：按 `README.md` 步骤启动服务
2. **调试追踪**：访问 LangSmith Dashboard，观察完整链路
3. **模拟面试**：让同事提问，使用本文档结构回答
4. **代码走读**：结合"代码映射"章节，逐文件阅读核心逻辑

---

## 更新日志

- **2026-02-07**：Multi-Agent 编排更新为“两阶段 Function Calling（plan -> step_action）”
- **2026-02-06**：完成四章深度技术文档，覆盖数据融合、GraphRAG、Multi-Agent、Text2SQL
- **2026-02-06**：补充实战 I/O 示例与面试攻防问题
- **2026-02-06**：添加代码映射章节，关联关键源码文件

---

## 反馈与改进

如果你在阅读过程中发现：
- **内容不清晰**：请标注章节和段落，提出具体问题
- **示例不够具体**：请说明需要补充的场景
- **代码映射错误**：请提供正确的文件路径和行号

我们会持续更新这套文档，确保其成为最硬核的系统架构面试指南。

---

**祝你面试顺利！展示你对系统底层逻辑的绝对掌控。**

---

## 数据流水线快速索引（新增）

了解数据从采集到入库的完整流程：

| 主题 | 章节位置 | 核心内容 |
|------|---------|---------|
| **数据采集架构** | [Chapter 1 § 0.1](chapter_1_data_foundation.md#01-完整的数据流水线架构) | 五大模块（bgpdata/rirdata/dnsdata/fusionprocessing/rirwebserver）职责划分 |
| **BGP 数据采集** | [Chapter 1 § 0.2.1](chapter_1_data_foundation.md#021-bgpdata路由观测数据采集) | RIPE RIS + RouteViews，MRT 格式解析，AS 拓扑关系提取 |
| **RIR 数据采集** | [Chapter 1 § 0.2.2](chapter_1_data_foundation.md#022-rirdata注册数据采集) | 委托数据 + WHOIS + RDAP 三阶段采集，五大 RIR 数据源 |
| **DNS 数据采集** | [Chapter 1 § 0.2.3](chapter_1_data_foundation.md#023-dnsdata域名解析数据采集) | 主动 DNS 查询 + 网页爬取，域名 → IP 关联 |
| **数据融合流程** | [Chapter 1 § 0.3](chapter_1_data_foundation.md#03-数据融合层多源数据的对齐与实体化) | Schema 异构、实体对齐、多源融合策略 |
| **组织映射技术** | [Chapter 1 § 0.4](chapter_1_data_foundation.md#04-组织映射的关键技术基于邮箱关键字的聚类) | 基于 org_handle + mail_key 的两阶段聚类算法 |
| **Fusionprocessing 流水线** | [Chapter 1 § 0.5](chapter_1_data_foundation.md#05-fusionprocessing实体化与格式化流水线) | 10+ 个 Formatter 的执行顺序、依赖关系、融合算法 |
| **AS 实体融合详解** | [Chapter 1 § 0.5](chapter_1_data_foundation.md#formatter-核心asentityformatteras-实体融合) | 融合 10+ 数据源，字段类型统一，缺失值填充 |
| **IP 前缀融合详解** | [Chapter 1 § 0.5](chapter_1_data_foundation.md#formatter-核心ipbgpformatterip-前缀融合) | 注册侧（inetnum/rdap/route）vs 观测侧（BGP），最长前缀匹配 |
| **数据质量保证** | [Chapter 1 § 0.6](chapter_1_data_foundation.md#06-数据质量保证三层验证机制) | 采集层、融合层、入库层的三层验证机制 |
| **性能优化实践** | [Chapter 1 § 3.1](chapter_1_data_foundation.md#31-并发策略) | gevent 协程并发、断点续传、指数退避重试 |
| **完整示例** | [Chapter 1 § 数据流水线完整示例](chapter_1_data_foundation.md#数据流水线完整示例) | AS4134（CHINANET）从原始数据到最终表的完整流程 |

**核心参考文献**：
- MRT 格式：RFC 6396 "Multi-Threaded Routing Toolkit (MRT) Format" - https://datatracker.ietf.org/doc/html/rfc6396
- RDAP 协议：RFC 7482 "RDAP Query Format" - https://datatracker.ietf.org/doc/html/rfc7482
- 数据集成理论：Halevy et al. "Principles of Dataspace Systems" (PODS 2006) - https://dl.acm.org/doi/10.1145/1142473.1142474
- ETL 最佳实践：Kimball & Caserta《数据仓库 ETL 工具箱》(2004)
- CAIDA AS-to-Org 映射方法：https://www.caida.org/catalog/datasets/as-organizations/

## 设计理由快速索引

如果你想快速查找某个设计决策的依据，可以使用以下索引：

### 数据架构设计

| 设计点 | 理由章节 | 核心参考 |
|--------|----------|----------|
| **为什么需要双轨并行（注册侧 vs 观测侧）？** | Chapter 1 § 1.1.1 | RFC 2050、RFC 4271、CAIDA AS Relationships |
| **为什么是 16 张表而不是更多/更少？** | Chapter 1 § 1.2.1 | 领域驱动设计（DDD）、Kimball 星型 Schema |
| **为什么字段级并行而非表级分离？** | Chapter 1 § 1.1.1 | InfluxDB 宽表设计、时序数据库最佳实践 |

### 检索架构设计

| 设计点 | 理由章节 | 核心参考 |
|--------|----------|----------|
| **为什么选择三引擎（PostgreSQL/Neo4j/Milvus）？** | Chapter 2 § 2.1.1 | Martin Fowler Polyglot Persistence |
| **为什么不用统一的多模数据库？** | Chapter 2 § 2.1.1 | LDBC Benchmark、性能对比测试 |
| **为什么选择 Milvus 而非 pgvector？** | Chapter 2 面试攻防 | Pinecone Benchmark、性能测试数据 |

### Multi-Agent 编排

| 设计点 | 理由章节 | 核心参考 |
|--------|----------|----------|
| **为什么从进程内调用升级到协议驱动？** | Chapter 3 § 3.1.1 | 微服务架构、Newman "Building Microservices" |
| **为什么选择 HTTP 而非 gRPC/消息队列？** | Chapter 3 § 3.1.1 | 协议对比矩阵、OpenAPI 3.0 规范 |
| **MCP 协议的灵感来源？** | Chapter 3 § 3.1.1 | Anthropic MCP、FastMCP |
| **A2A 协议的设计参考？** | Chapter 3 § 3.1.1 | FIPA ACL、Agent Protocol |

### Text2SQL 安全

| 设计点 | 理由章节 | 核心参考 |
|--------|----------|----------|
| **为什么需要三段式安全链路？** | Chapter 4 § 4.1.1 | NIST Zero Trust Architecture |
| **为什么不能信任 LLM 直接生成的 SQL？** | Chapter 4 § 4.1.1 | 提示注入攻击（Perez & Ribeiro 2022） |
| **为什么选择 LlamaIndex 而非 LangChain？** | Chapter 4 § 4.1.1 | 功能对比、安全机制对比 |
| **SQLGuard 设计参考了哪些安全标准？** | Chapter 4 § 4.1.1 | OWASP SQL 注入防御、AWS IAM |

### RAG 系统设计

| 设计点 | 理由章节 | 核心参考 |
|--------|----------|----------|
| **为什么需要文档分块？** | Chapter 5 § 5.2.1 | Callan 段落级检索（SIGIR 1994） |
| **为什么选择 800 tokens？** | Chapter 5 § 5.2.1 | LangChain 实验、OpenAI Cookbook |
| **为什么需要 Overlap（重叠）？** | Chapter 5 § 5.2.1 | 滑动窗口技术、Pinecone 研究 |
| **为什么选择 text-embedding-v3？** | Chapter 5 § 5.3.1 | C-MTEB Benchmark、成本-质量分析 |
| **为什么是 1536 维而非 3072 维？** | Chapter 5 § 5.3.1 | 性能-成本权衡、实验数据 |

### GraphRAG 设计

| 设计点 | 理由章节 | 核心参考 |
|--------|----------|----------|
| **GraphRAG 的概念来源？** | Chapter 5 § 4.1.1 | Microsoft GraphRAG（Edge et al. 2024） |
| **为什么选择数据驱动而非文档抽取？** | Chapter 5 § 4.1.1 | 领域特性、准确性对比 |
| **为什么需要双重图谱？** | Chapter 2 面试攻防 | 静态知识 vs 动态记忆的分离 |

---

## 参考文献快速查找

**核心论文（必读）**：

1. **BGP 与路由安全**：
   - RFC 4271 "A Border Gateway Protocol 4 (BGP-4)" - https://datatracker.ietf.org/doc/html/rfc4271
   - RFC 6480 "RPKI Infrastructure" - https://datatracker.ietf.org/doc/html/rfc6480
   - Ballani et al. "Detecting BGP Configuration Faults" (NSDI 2005)

2. **数据库架构**：
   - Fowler "Polyglot Persistence" - https://martinfowler.com/bliki/PolyglotPersistence.html
   - Kimball "The Data Warehouse Toolkit" (2013)
   - Evans "Domain-Driven Design" (2003)

3. **Text2SQL**：
   - Pourreza & Rafiei "DIN-SQL" (NeurIPS 2023) - https://arxiv.org/abs/2304.11015
   - Rajkumar et al. "Evaluating Text-to-SQL Capabilities" (2022) - https://arxiv.org/abs/2204.00498

4. **RAG 系统**：
   - Karpukhin et al. "Dense Passage Retrieval" (EMNLP 2020) - https://arxiv.org/abs/2004.04906
   - Edge et al. "Graph RAG" (2024) - https://arxiv.org/abs/2404.16130
   - Reimers & Gurevych "Sentence-BERT" (EMNLP 2019) - https://arxiv.org/abs/1908.10084

5. **安全架构**：
   - NIST SP 800-207 "Zero Trust Architecture" - https://csrc.nist.gov/publications/detail/sp/800-207/final
   - OWASP "SQL Injection Prevention" - https://cheatsheetseries.owasp.org/

6. **分布式系统**：
   - Newman "Building Microservices" (O'Reilly 2015)
   - Fowler "CQRS" - https://martinfowler.com/bliki/CQRS.html

**业界实践（推荐阅读）**：

- **CAIDA**：AS Relationships、BGPStream - https://www.caida.org/
- **RIPE NCC**：RIPEStat - https://stat.ripe.net/
- **Anthropic**：Model Context Protocol - https://modelcontextprotocol.io/
- **Microsoft**：GraphRAG - https://github.com/microsoft/graphrag
- **LangChain**：RAG 最佳实践 - https://blog.langchain.dev/
- **Pinecone**：向量数据库教程 - https://www.pinecone.io/learn/

---

## 更新日志

### 2026-02-08 v2

**重大更新：数据采集与融合全链路**

- **Chapter 1（数据基础）**
  - **新增 § 0.1-0.6**：完整的数据流水线架构（从源头到入库）
    - `§ 0.1`：五大模块（bgpdata/rirdata/dnsdata/fusionprocessing/rirwebserver）的职责划分与协同关系
    - `§ 0.2.1`：BGPdata 模块详解（RIPE RIS + RouteViews，MRT 格式解析，AS 拓扑关系提取算法）
    - `§ 0.2.2`：RIRdata 模块详解（三阶段采集：委托数据 + WHOIS + RDAP，五大 RIR 数据源的差异与融合）
    - `§ 0.2.3`：DNSdata 模块详解（主动 DNS 查询 + 网页爬取，域名 → IP 应用层关联）
    - `§ 0.3`：数据融合层的技术挑战（Schema 异构、实体对齐、多源冲突解决）
    - `§ 0.4`：组织映射的核心算法（基于 org_handle + mail_key 的两阶段聚类，邮箱关键字提取的理论依据与验证数据）
    - `§ 0.5`：Fusionprocessing 实体化流水线（10+ 个 Formatter 的执行顺序、DAG 依赖关系、核心融合算法）
      - **ASEntityFormatter 详解**：融合 10+ 数据源的算法，字段类型统一，缺失值优先级填充策略
      - **IPBGPFormatter 详解**：注册侧（inetnum/rdap/route）vs 观测侧（BGP）的双轨融合，最长前缀匹配算法
    - `§ 0.6`：数据质量保证的三层验证机制（采集层、融合层、入库层）
  - **新增完整示例**：AS4134（CHINANET-BACKBONE）从原始数据到最终入库的完整数据流（跨越 10 个处理阶段）
  - **新增性能优化章节**：gevent 协程并发、断点续传、指数退避重试、缓存策略（含性能对比数据）
  - **新增代码映射**：完整目录结构（五大模块的代码组织、数据流向、文件路径）
  - 保留原有内容：
    - `§ 1.1.1 设计动机与理论基础`：双轨架构（Registry vs. Observed）的选择理由
    - `§ 1.2.1 为什么是 16 张表？设计依据`：16 表设计的理论基础（DDD、Star Schema、3NF 权衡）

**新增核心参考文献**（数据采集与融合）：
- RFC 6396 "Multi-Threaded Routing Toolkit (MRT) Format" - https://datatracker.ietf.org/doc/html/rfc6396
- RFC 3912 "WHOIS Protocol Specification" - https://datatracker.ietf.org/doc/html/rfc3912
- RFC 7480-7484 "RDAP Protocol Suite" - https://datatracker.ietf.org/doc/html/rfc7482
- Halevy et al. "Principles of Dataspace Systems" (PODS 2006) - https://dl.acm.org/doi/10.1145/1142473.1142474
- Kimball & Caserta《数据仓库 ETL 工具箱》(The Data Warehouse ETL Toolkit, 2004)
- CAIDA AS-to-Organization 映射方法 - https://www.caida.org/catalog/datasets/as-organizations/
- Augustin et al. "Measuring Multipath Routing in the Internet" (IEEE/ACM ToN 2011)
- Scheitle et al. "A Long Way to the Top" (IMC 2018) - https://arxiv.org/abs/1805.11506

- **README**
  - 新增"数据流水线快速索引"章节：提供数据采集与融合的 12 个核心主题快速导航
  - 更新"核心价值"：增加对数据流水线完整性的强调

### 2026-02-08 v1

- **Chapter 1（数据基础）**
  - 新增 `§ 1.1.1 设计动机与理论基础`：解释双轨架构（Registry vs. Observed）的选择理由，引用 RFCs、CAIDA 研究、RIPEStat 和 BGPStream
  - 新增 `§ 1.2.1 为什么是 16 张表？设计依据`：详细说明 16 表设计的理论基础，包括 DDD、Star/Snowflake Schema、3NF vs. 反范式化、OLTP vs. OLAP 权衡；引用 LLM 性能研究说明为何过多表会降低 Text2SQL 准确率
  - 补充"实体化优先，非日志优先"原则的理论依据：对比 Event Sourcing vs. State Storage，说明为何选择实体化存储

- **Chapter 2（GraphRAG 与混合检索）**
  - 新增 `§ 2.1.1 为什么选择三引擎而非单一数据库？`：详细阐述 Polyglot Persistence 理念，对比单引擎方案的不足，引用 Martin Fowler 架构理念、CQRS 模式、LinkedIn 和 Netflix 实践案例
  
- **Chapter 3（多智能体编排）**
  - 新增 `§ 3.1.1 为什么从进程内调用升级到协议驱动？`：对比旧架构（紧耦合）与新架构（协议驱动）的差异，引用微服务架构原则、Anthropic MCP、FIPA ACL，详细对比 HTTP/REST、gRPC、WebSocket、消息队列等通信协议的选型理由
  
- **Chapter 4（Text2SQL 安全）**
  - 新增 `§ 4.1.1 为什么需要三段式安全链路？`：解释"Generate → Validate → Execute"架构的必要性，引用 Zero Trust Architecture、OWASP SQL 注入防御、AWS IAM 策略、Google BeyondCorp；对比 LlamaIndex、LangChain SQL Agent、Vanna.AI 等框架的选型理由
  
- **Chapter 5（RAG 深度解析）**
  - 新增 `§ 5.2.1 为什么需要文档分块？理论基础`：解释分块的粒度权衡、语义完整性、上下文窗口限制，引用学术文献（Callan 1994, Mann & Thompson 1988）和工程实践数据（LangChain、OpenAI Cookbook、Pinecone）
  - 新增 `§ 5.3.1 为什么需要向量化？理论基础`：介绍 Distributional Semantics Hypothesis、Word2Vec、Sentence-BERT，详细对比 DashScope `text-embedding-v3` 与 bge-large-zh-v1.5、OpenAI text-embedding-3-large/small 的技术参数（成本、质量、延迟、可操作性），提供选择决策矩阵
  - 新增 `§ 4.1.1 GraphRAG 的概念来源与理论基础`：介绍 Microsoft Research 的 GraphRAG 概念（Edge et al. 2024）、三代 RAG 演进、本系统 GraphRAG 实现的差异（数据驱动领域图 vs. 文档抽取图）

- **README**
  - 新增"核心价值"第 5、6 条：强调设计理由清晰和可追溯性强
  - 新增"文档特色：深度解析设计理由"章节：明确本文档与其他技术文档的差异（深度解析 vs. 简单罗列）
  - 新增"设计理由快速索引"章节：提供按主题分类的设计理由快速查找表，包含章节链接和核心参考文献
  - 新增"参考文献快速查找"章节：按技术领域分类列出所有引用的学术论文、行业标准、技术博客，附带 URL
