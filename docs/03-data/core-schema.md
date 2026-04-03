# 核心数据模型

## 基本原则
- 默认落库目标只有 16 张核心实体表。
- CSV 文件可以带日期快照，但数据库表名固定不带日期。
- PostgreSQL 是事实源，Milvus 与 Neo4j 可从结构化数据和文档重新构建。
- IP 单点不作为图谱核心节点，统一以 Prefix 为核心实体。

## 导入与字段约束
- 多值字段通常以 Python 列表字符串保存，导入时解析为数组类型。
- `admin_info`、`tech_info`、`abuse_info` 为 JSON 字符串，落库为 `json/jsonb`。
- 导入阶段统一做列名规范化：小写化并把特殊字符转为下划线。
- `website_entity_base.csv` 使用 `;` 分隔，和 `domain_cn.csv` 合并时需要单独处理。
- RIR 注册归属与 BGP 观测归属需要并行保留，不做强行合并。

## 16 张核心表

| 表名 | 作用 | 关键字段 | 主要关联 |
| --- | --- | --- | --- |
| `as_entity` | AS 画像融合 | `asn`, `aut_name`, `uuid`, `v4peer` | AS ↔ Org / Country / Prefix |
| `asn_entity` | ASN 委托基础 | `asn`, `country`, `org_name` | ASN ↔ AS |
| `country_entity` | 国家维度聚合 | `country`, `asns_number`, `v4prefixes_number` | Country ↔ AS / Org / Prefix |
| `industry_entity` | 网站行业聚合 | `url`, `industry`, `ip_asn` | Website ↔ AS / Prefix |
| `ip_bgp_entity` | IPv4 前缀 BGP 归属 | `prefix`, `route`, `bgp`, `country` | Prefix ↔ AS / Org / Country |
| `ip_inetnum_entity` | IPv4 WHOIS 信息 | `cidr`, `netname`, `org` | Prefix Registry 属性 |
| `ip_rdap_entity` | IPv4 RDAP 信息 | `cidr`, `netname`, `org` | Prefix Registry 属性 |
| `ip_route_entity` | IPv4 route 对象 | `cidr`, `origin`, `mnt_by` | Prefix Registry 属性 |
| `ipv4_entity` | IPv4 委托前缀 | `prefix`, `org_id`, `uuid` | Prefix ↔ Org / AS |
| `ipv6_bgp_entity` | IPv6 前缀 BGP 归属 | `prefix`, `route`, `bgp` | Prefix ↔ AS / Org |
| `ipv6_entity` | IPv6 委托前缀 | `prefix`, `org_id`, `uuid` | Prefix ↔ Org / AS |
| `ipv6_inetnum_entity` | IPv6 WHOIS 信息 | `cidr`, `netname` | Prefix Registry 属性 |
| `ipv6_rdap_entity` | IPv6 RDAP 信息 | `cidr`, `netname` | Prefix Registry 属性 |
| `ipv6_route_entity` | IPv6 route 对象 | `cidr`, `origin` | Prefix Registry 属性 |
| `org_entity` | 组织画像 | `uuid`, `org_name`, `v4prefixes` | Org ↔ AS / Prefix |
| `website_entity` | 网站基础信息 | `url`, `ip`, `ip_prefix`, `auth_ip` | Website ↔ Prefix / AS |

## 核心关系
- `as_entity.asn` ↔ `asn_entity.asn`
- `as_entity.uuid` ↔ `org_entity.uuid`
- `ipv4_entity.uuid` / `ipv6_entity.uuid` ↔ `org_entity.uuid`
- `ip_bgp_entity.route` / `ip_bgp_entity.bgp` ↔ `as_entity.asn`
- `ip_bgp_entity.org_uuid_prefix` / `org_uuid_bgp` ↔ `org_entity.uuid`
- `ip_bgp_entity.country` ↔ `country_entity.country`
- `website_entity.ip_prefix` / `auth_ip_prefix` ↔ Prefix 相关表

## 注册侧与观测侧的边界
- 注册侧：`inetnum`、`rdap`、`route`、`ipv4_entity`、`ipv6_entity` 等表反映权威分配与注册信息。
- 观测侧：`ip_bgp_entity`、`ipv6_bgp_entity`、`as_entity` 中的 BGP 拓扑字段反映路由观测结果。
- 两侧应同时保留，用于一致性分析、冲突识别和归属解释。

## 运行时表说明
以下表不是 16 张核心表，只是智能体运行时附属表：
- `agent_threads`
- `agent_messages`
- `agent_episodic_memory`
- LangGraph checkpoint 相关表

## 当前权威来源
- 结构化表与导入脚本：`agent/scripts/load_all_csv.py`
- 统一 DDL：`database/core_schema.sql`
- 融合处理：`fusiondata/src/`

涉及表结构或字段语义变更时，应优先更新本文件。
