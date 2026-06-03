# 测试计划（重构版）

本目录测试目标：验证 FusionAgent 的路由调度与工具执行能力，采用“自然语言问题 + 可验证标准答案”的方式。

## 执行方式

1. 非 live（本地纯逻辑）：
```bash
PYTHONPATH=. ./.venv/bin/pytest -q -m "not live"
```

2. live（连接 PostgreSQL / Neo4j / Milvus / MCP）：
```bash
FUSION_RUN_LIVE=1 PYTHONPATH=. ./.venv/bin/pytest -q -m live
```

## 模块与用例数量

1. MCP 目录与健康检查：3 条
2. NL2SQL（自然语言 -> SQL 结果）：3 条
3. Neo4j（图查询结果）：3 条
4. RAG（自然语言检索）：3 条 + 空查询 1 条
5. NoteTool：3 条 + limit 1 条
6. TodoTool：3 条
7. 路由调度（分类/降级/依赖/执行分发）：4 条

总计 21 条测试。

## 标准答案来源

1. NL2SQL：标准答案来自 PostgreSQL 直查。
2. Neo4j：标准答案来自 Neo4j 直查。
3. RAG：标准答案来自本地 RAGTool 直连 Milvus。
4. Note/Todo：标准答案来自隔离测试数据。
5. 路由调度：标准答案来自固定输入状态与预期路由行为。

## RAG 用例执行策略

1. RAG live 用例在模块开始会做“就绪探测”。
2. 若 Milvus 向量维度与当前 embedding 不一致、或 MCP `rag_search` 依赖未安装，则该模块 `skip`，不强制失败。
3. 这样可以把“环境问题”与“功能回归问题”分离，避免误报。
