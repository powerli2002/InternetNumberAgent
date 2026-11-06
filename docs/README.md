# 文档总入口

本文档体系按“先理解系统，再落地运行，最后指导 AI 干活”的顺序组织。除 `docs/90-archive/` 外，其余文档均为当前实现的有效文档。

## 阅读顺序
1. `01-overview/system-overview.md`：先理解系统解决什么问题、有哪些能力、边界在哪里。
2. `02-architecture/overall-architecture.md`：再看当前代码架构、运行链路与模块职责。
3. `02-architecture/query-pipelines.md`：理解 NL2SQL、RAG、Neo4j 查询如何协同。
4. `03-data/core-schema.md`：查看 16 张核心表、字段语义和导入规则。
5. `04-operations/*.md`：按需查看部署、监控、UI 接入与排障。
6. `05-ai/*.md`：阅读 AI 工作指南、Harness 规范和文档治理规则。

## 目录说明

### `01-overview/`
- `system-overview.md`：系统目标、能力边界、典型场景、目录索引。

### `02-architecture/`
- `overall-architecture.md`：当前主干架构与代码目录。
- `query-pipelines.md`：查询路由与证据生成链路。
- `python-sandbox.md`：Python 沙箱、CSV 数据传递、artifact 回收与命名规则。
- `text2sql.md`：Text2SQL 专题。

### `03-data/`
- `core-schema.md`：16 张核心表、字段约束、导入规则、运行时表边界。
- 本机文件位置及历史快照恢复见根目录 `DATA_CATALOG.md`。

### `04-operations/`
- `deployment.md`：部署、启动、导入、索引构建、常用命令。
- `configuration.md`：环境变量、LLM 后端、本地存储与运行配置。
- `evaluation.md`：自动评测与 LangSmith 写回流程。
- `observability.md`：LangSmith、日志、运行时观测。
- `troubleshooting.md`：常见故障与防护规则。
- `agent-chat-ui.md`：产品前端与兼容 Agent Chat UI 接入。

### `05-ai/`
- `repo-guide.md`：AI 如何按任务快速理解仓库。
- `harness-programming.md`：Harness 设计与编程规范。
- `documentation-governance.md`：文档生命周期与清理规则。

### `90-archive/`
- 历史方案、旧笔记、面试材料、过期章节。
- 只保留背景信息，不作为当前实现依据。

## 维护规则
- 一个主题只保留一份当前权威文档。
- 文档修改时直接改正文，不追加“更新补丁条目”。
- 代码与文档冲突时，以代码为准，并在同次任务中修正文档。
