# fusionprocessing - Agent 入口规范

## 角色定位
- 本仓库当前目标是构建“互联网号码资源问答系统”MVP：以 `services/fusiondata/` 为融合处理层，将 RIR/WHOIS/RDAP、BGP、DNS/网站等多源数据清洗对齐后写入 PostgreSQL 16 张核心表，并由 `FusionAgent` 统一调度 NL2SQL、RAG 与图查询，生成带证据的回答。
- PostgreSQL 是事实源，Milvus 与 Neo4j 属于可重建的派生索引；回答必须能回溯到 SQL 结果、文档片段或图谱关系。

## 当前代码结构
- 四个产品服务统一收纳在 `services/` 下；三个 Python 包仍以顶层包名 `agent`、`fusiondata`、`backend` 导入，靠把 `services/` 加入 `PYTHONPATH`（`deploy/` 脚本已自动设置，手动执行 `python -m agent.*` 前先 `export PYTHONPATH=services`）。
- `services/fusiondata/src/`：数据清洗、实体化、格式化流水线。
- `services/fusiondata/setup.py`：融合处理入口。
- `services/agent/runtime/`：FusionAgent、LangGraph 主编排、上下文构建。
- `services/agent/services/http/`：HTTP API 服务。
- `services/agent/services/mcp/`：FastMCP 工具服务与客户端。
- `services/agent/tools/`：NL2SQL、RAG、Neo4j、Note、Todo 等底层工具。
- `services/agent/scripts/`：导入、建索引、评测、排障脚本。
- `services/backend/`：认证、线程、过程事件、artifact、OpenSandbox 接入。
- `services/webapp/`：正式产品前端。
- `conf/`：配置与 `.env`。
- `database/`：核心表 DDL 与注释。
- `docs/`：当前权威文档与 AI 指南。
- `scratch/`：技能卡片与个人笔记等非运行必需内容。

## 硬约束
- 默认落库目标只有 16 张核心实体表；不要引入 `*_audit`、原始镜像表或额外中间表，除非用户明确要求。
- CSV 多为日期快照，数据库表名不带日期；导入时选择最新或指定日期。
- 多值字段以 Python 列表字符串存储，导入时解析为数组类型。
- `admin_info`、`tech_info`、`abuse_info` 为 JSON 字符串，落库为 `json/jsonb`。
- 图谱以 Prefix 为核心实体，不把 IP 单点作为核心节点。
- `website_entity_base.csv` 使用 `;` 分隔，且首列可能为空。
- 代码实现禁止无明确需求的回退策略；流程不成立时应直接报错并暴露决策点。
- 注释必须使用简体中文；复杂逻辑先写清思路再实现。

## 文档入口
- 总入口：`docs/README.md`
- 系统功能：`docs/01-overview/system-overview.md`
- 当前架构：`docs/02-architecture/overall-architecture.md`
- 查询链路：`docs/02-architecture/query-pipelines.md`
- Text2SQL：`docs/02-architecture/text2sql.md`
- 数据模型：`docs/03-data/core-schema.md`
- 部署运行：`docs/04-operations/deployment.md`
- 观测排障：`docs/04-operations/observability.md`、`docs/04-operations/troubleshooting.md`
- AI 协作：`docs/05-ai/repo-guide.md`
- Harness 规范：`docs/05-ai/harness-programming.md`
- 文档治理：`docs/05-ai/documentation-governance.md`
- 历史文档：`docs/90-archive/`（不作为当前实现依据）

## Harness 编程规范摘要
- `AGENTS.md` 只保留硬约束和索引，不承载大段实现细节。
- 开始修改前，先读 `docs/README.md`，再按任务类型进入对应权威文档。
- 优先修改已有文档，不随意新增平行说明。
- 同一主题只能有一个当前权威文档；其余内容要么合并，要么归档。
- 文档必须服务两类读者：先让人快速理解系统功能，再让 AI 能按文档定位代码和约束。
- 历史方案可以保留到 `docs/90-archive/`，但必须显式标注非当前实现。

## 文档治理摘要
- 修改文档时禁止“增量补丁式追加”更新记录；应直接重写正文，保证整篇文档始终为最新状态。
- 若代码与文档冲突，以代码为准，并在同次任务中修正文档。
- 发现过期文档时，不绕过、不搁置，必须在当前任务内完成修正、归档或删除。
- 重大改动至少同步检查：系统总览、架构、数据模型、部署运行、AI 指南。
- 只要代码修改影响命令、脚本入口、默认解释器、配置加载方式或运行前置条件，必须在同次任务同步修改对应权威文档；禁止只改代码和命令实现、不改文档。
- `docs/90-archive/` 仅用于保留历史背景，不得作为设计或实现决策依据。

## 重大修改必须同步文档
- 数据模型、表结构、字段语义、导入逻辑、核心关系发生变化。
- FusionAgent 路由、LangGraph 编排、MCP 工具、记忆或上下文工程发生变化。
- 部署方式、配置项、端口、存储路径、依赖服务发生变化。
- 重要脚本入口、运行命令或排障流程发生变化。

至少同步检查以下位置：
- `docs/README.md`
- `docs/02-architecture/overall-architecture.md`
- `docs/03-data/core-schema.md`
- `docs/04-operations/deployment.md`
- `docs/05-ai/documentation-governance.md`

涉及运行命令或脚本入口时，额外强制检查：
- 根 `README.md`
- 对应主题的 `docs/04-operations/*.md`

根目录 `summary.md` 仅保留兼容性入口，当前数据模型权威内容以 `docs/03-data/core-schema.md` 为准。

## Weights & Biases 配置

**API Key**：存储于 `~/.netrc` 或本机环境变量 `WANDB_API_KEY`，勿提交到公开仓库。

**登录命令**：
```bash
/opt/conda3/envs/netloc/bin/wandb login "$WANDB_API_KEY"
```

Project 信息：
- Team：powerli_team（提交时务必确认）
- Project：GraduateProject
- 项目地址：https://wandb.ai/powerli_team/GraduateProject

W&B Skills 安装：

```bash
# 仅当前项目
npx skills add wandb/skills --skill '*' --yes

# 全局（所有项目）
npx skills add wandb/skills --skill '*' --yes --global

# 绑定到指定 Agent（如 Claude Code）
npx skills add wandb/skills --agent claude-code --skill '*' --yes --global
```
