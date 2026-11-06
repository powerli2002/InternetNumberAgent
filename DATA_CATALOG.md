# 本地数据目录

PostgreSQL 保存系统的结构化事实，核心表定义见 [数据模型](docs/03-data/core-schema.md)。本文件仅列出本机文件及保留规则，导入命令见 [部署与运行](docs/04-operations/deployment.md)。

| 目录 | 内容与保留规则 |
|---|---|
| `services/fusiondata/data/format/` | 保留六类实体表最新的 `2024-08-12` 快照、最新 `rib_data_2024-09-30.csv` 和全部无日期基础表；`resolve_result_*` 是历史 DNS 采集，全部保留。 |
| `services/fusiondata/bgp_data/data/` | 原始 BGP RIB 文本，全部保留。 |
| `services/fusiondata/data/org_entity/` | 机构与 AS 映射及其来源，保留。 |
| `services/fusiondata/data/static/`、`services/fusiondata/data/utils/` | 外部数据、静态字典和辅助表，保留。 |
| `data/archives/derived_snapshots_20261106.tar.zst` | 旧日期实体表、旧 RIB 汇总和历史导出子集的无损归档。逐文件解压哈希核对通过后，移除对应散文件。私有归档不提交 Git。 |
| `database/db/`、`data/geoip/` | 本地地址数据库文件，保留。 |
| `mount/` | PostgreSQL、Neo4j、Milvus 数据卷及历史故障库副本，未删除。 |
| `GraduatePaper/data/`、`GraduatePaper/outputs/` | 实验输入、原始观测与结果，保留。 |
| `.langgraph_api/`、`services/agent/store/` | 会话状态和记忆存储，保留。其 checkpoint 文件属于会话状态。 |

本次检查未发现仓库内的训练模型权重；Python 环境里的 `.pth` 文件是包路径配置，不按模型权重处理。远端模型与其他项目权重未改动。

清理范围和归档校验值见 [清理清单](docs/04-operations/cleanup_manifest_20261106.json)。历史字段介绍保存在 [旧数据目录说明](docs/90-archive/data-catalog-20260104.md)。

需要旧日期文件时，先校验归档 SHA-256，再解压到单独目录；不要覆盖现有快照。归档位于本机，重装前仍须复制到保留磁盘。
