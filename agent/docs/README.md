# 互联网号码资源问答系统 - 系统架构深度解析

> **目标读者**：准备技术面试的开发者、系统架构师、AI 工程师  
> **文档定位**：通过具体的输入输出（I/O）数据流，展示系统底层逻辑的绝对掌控

## 核心价值

这套文档将帮助你：

1. **掌握核心模块**：从数据融合到 GraphRAG、从 Multi-Agent 编排到 Text2SQL 安全防御
2. **理解 I/O 链路**：每个示例都展示 Raw Input → 中间处理 → Final Output 的完整数据流
3. **应对面试攻防**：每章末尾提供高频面试问题及技术深度回答要点
4. **代码映射明确**：关键逻辑都标注了对应的代码文件和行号

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
- 向量检索优化：表/列双重索引 + 磁盘缓存 + 内存缓存
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
