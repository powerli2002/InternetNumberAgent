# AI 仓库工作指南

## 目标

这份文档给 AI 和开发者提供同一套入口，目的是在最短时间内回答三个问题：
- 系统现在做什么。
- 这次需求应该改哪里。
- 改完后哪些文档必须同步更新。

## 阅读顺序
1. `../../README.md`：仓库总入口。
2. `../README.md`：文档总入口。
3. `../01-overview/system-overview.md`：理解系统能力和边界。
4. `../02-architecture/overall-architecture.md`：理解当前主干架构。
5. 按任务类型进入专题文档。

## 按任务找文档
- 改数据模型、表字段、导入逻辑：看 `../03-data/core-schema.md`
- 改 LangGraph、FusionAgent、上下文工程：看 `../02-architecture/overall-architecture.md`
- 改 NL2SQL：看 `../02-architecture/text2sql.md`
- 改 RAG、图查询、证据组织：看 `../02-architecture/query-pipelines.md`
- 改部署、配置、端口、启动脚本：看 `../04-operations/deployment.md`
- 改监控、日志、追踪：看 `../04-operations/observability.md`
- 改文档组织、AI 规范：看本目录下其他文档

## 按代码目录找位置
- `fusiondata/src/`：离线融合逻辑
- `agent/runtime/`：主编排与上下文构建
- `agent/services/http/`：API
- `agent/services/mcp/`：工具服务与客户端
- `agent/tools/`：NL2SQL / RAG / Neo4j / Note / Todo
- `agent/scripts/`：导入、建索引、排障脚本

## 工作规则
- 先看权威文档，再改代码，不要根据归档文档做判断。
- 保持改动最小，优先延续当前分层和命名。
- 发现文档过期时，要在同次任务中修正、归档或删除。
- 不要新增平行说明文档去“补丁式覆盖”旧文档。

## 交付前检查
- 代码改动是否与当前权威文档一致。
- 是否触发了文档同步条件。
- 是否误引用了 `docs/90-archive/` 中的历史方案。
