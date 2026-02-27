# 互联网号码资源查询系统（fusionprocessing）项目总结

本文档基于当前仓库与实际 CSV 结构，详细描述系统的数据格式、功能与数据库 16 张核心表之间的关联关系，便于面试展示与后续工程落地。

---

## 1. 系统定位与核心功能

**定位**：该仓库是“互联网号码资源查询系统”的数据融合处理层，负责将 RIR/WHOIS/RDAP、BGP 路由、DNS 解析与网站信息等多源数据清洗、融合、实体化，并写入 PostgreSQL 供上层服务检索与分析。

**核心功能**：

1. **互联网号码资源融合**：统一 AS、IP 前缀、组织、国家等互联网资源实体画像。
2. **路由与归属解析**：提取前缀归属 AS、BGP 观测 AS、上下游/对等关系等拓扑信息。
3. **多源实体对齐**：将 RIR 注册信息与 BGP 观测归属进行对比校验。
4. **域名/网站关联**：将域名或网站与 IP、前缀、AS、组织建立关联链路。
5. **可落库**：默认仅写入 16 张核心实体表，便于 API 检索、图谱建模与查询性能优化。

### 1.1 智能体目录分层（2026-02-06）

为降低耦合并统一工程规范，`agent/` 目录已按分层组织，并在 2026-02-25 完成 **LangGraph + MCP** 升级：

- `agent/core/`：配置、模型、提示词、LLM、追踪、Schema
- `agent/runtime/`：FusionAgent 运行时编排（LangGraph 主图）
- `agent/services/http/`：FastAPI 接口与线程消息存储
- `agent/services/mcp/`：FastMCP 工具服务与客户端
- `agent/cli/`：命令行入口

当前统一入口：

- MCP：`uvicorn agent.services.mcp.server:app --host 0.0.0.0 --port 2032`
- API：`uvicorn agent.services.http.server:app --host 0.0.0.0 --port 2025`
- CLI：`python -m agent.cli.main --once "你的问题"`

本地向量化实现已统一为 `HuggingFaceEmbedding`（RAG/NL2SQL 共用实现口径），但 Milvus 集合保持分离：`fusion_docs`（RAG）与 `nl2sql_index`（NL2SQL）。

图查询链路当前默认使用 `neo4j_llamaindex_query`：由 MCP 工具内部通过 LlamaIndex 读取 Neo4j schema、生成 Cypher 并执行；主编排不再预先生成 Cypher。

---

## 2. 数据格式与落库规则

### 2.1 文件与命名规则

- 核心 CSV 位于 `data/format/`。
- 多数表按日期生成快照（如 `as_entity_2024-08-12.csv`），数据库表名不带日期。
- 导入时只写入 16 张实体表；如存在多日期 CSV，需指定或选择最新日期文件。

### 2.2 字段编码约定

- **多值字段**：通常是 Python 列表字面量字符串（如 `"[1, 2, 3]"`），落库为数组类型（如 `text[]`、`bigint[]`）。
- **联系信息**：`admin_info/tech_info/abuse_info` 为 JSON 字符串，落库为 `json`。
- **IP 类型**：前缀字段为 `cidr/inet`，IP 列表以字符串数组保存。
- **列名规范化**：导入阶段统一执行 `lowercase + 特殊字符转下划线`（例如 `v4Prefixes -> v4prefixes`、`CIDR -> cidr`、`admin-c -> admin_c`）。
- **分隔符**：`website_entity_base.csv` 使用 `;` 分隔，其余多为 `,` 分隔。

### 2.3 运行时/辅助表（非 16 核心表）

以下表由智能体运行时创建，**不属于 16 张核心实体表**，用于对话与记忆持久化：

- `agent_threads`：对话线程元数据
- `agent_messages`：线程内消息记录
- `agent_episodic_memory`：情景记忆条目（重要对话片段）

---

## 3. 数据库 16 张核心表（字段与含义）

> 说明：以下字段为**数据库落库字段名**（已做列名规范化：小写+下划线）。数据库表名固定为下列 16 张。

### 3.1 `as_entity`

- **主键**：`asn`
- **来源**：`data/format/as_entity_YYYY-MM-DD.csv`
- **字段说明**：
  - 基础：`source, opq_id, date, status`
  - 描述与名称：`descr, descr_cn, aut_name, website`
  - 注册信息：`registration_date, last_change_date`
  - 组织归属：`org_handle, org_id, org_rank, org_country, org_country_cn, uuid, org_name, org_name_cn, sibling_as`
  - 联系人：`administrative, technical, abuse, admin_info, tech_info, abuse_info`
  - AS画像：`as_rank, type, type_cn, is_ddos_provider, is_route`
  - 地理信息：`as_longitude, as_latitude, geo_country_list, geo_city_list, geo_latitude_longitude, geo_country_list_num, geo_city_list_num, geo_latitude_longitude_num, as_country, as_country_cn`
  - 路由策略：`import, export, import_as, export_as`
  - BGP 拓扑：`v4upstream, v4peer, v4downstream, v4propagation, v4prefixes, v6upstream, v6peer, v6downstream, v6propagation, v6prefixes`

### 3.2 `asn_entity`

- **主键**：`asn`
- **来源**：`data/format/asn_entity.csv`
- **字段说明**：`asn, source, country, opq_id, date, status, org_name, uuid`

### 3.3 `country_entity`

- **主键**：`country`（国家代码）
- **来源**：`data/format/country_entity_YYYY-MM-DD.csv`
- **字段说明**：
  - 基础：`country_en, country, country_cn, region`
  - 宏观统计：`population, internet_users, internet_users_percentage, gdp_per_capita_cny`
  - 聚合统计：`asns, asns_number, route_asns, route_asns_number, v4prefixes, v4prefixes_number, v6prefixes, v6prefixes_number, orgs, orgs_number`

### 3.4 `industry_entity`

- **主键**：无显式主键（以 `url`/`parent` 组合可唯一）
- **来源**：`data/format/industry_entity_YYYY-MM-DD.csv`
- **字段说明**：`url, parent, title, industry, description, key, ip, ip_prefix, ip_asn, ip_org, auth_ip, auth_ip_prefix, auth_ip_asn, auth_ip_org`

### 3.5 `ip_bgp_entity`

- **主键**：`prefix + bgp`
- **来源**：`data/format/ip_bgp_entity_YYYY-MM-DD.csv`
- **字段说明**：
  - 前缀与归属：`prefix, prefix_len, route, bgp`
  - 描述信息：`name, descr`
  - 联系人：`admin_prefix, admin_route, admin_bgp`
  - 组织归属：`org_handle_prefix, org_name_prefix, org_name_cn_prefix, org_uuid_prefix, org_handle_bgp, org_name_bgp, org_name_cn_bgp, org_uuid_bgp`
  - 标记字段：`country, source, date, inetnum, rdap, rpki`
  - 域名关联：`domain, domain_num, domain_auth, domain_auth_num`

### 3.6 `ip_inetnum_entity`

- **主键**：`cidr`
- **来源**：`data/format/ip_inetnum_entity.csv`
- **字段说明**：`cidr, netname, descr, country, source, admin_c, tech_c, abuse_c, org, org_name, org_name_cn, org_uuid`

### 3.7 `ip_rdap_entity`

- **主键**：`cidr`
- **来源**：`data/format/ip_rdap_entity.csv`
- **字段说明**：`cidr, netname, descr, country, source, admin_c, tech_c, abuse_c, org, org_name, org_name_cn, org_uuid`

### 3.8 `ip_route_entity`

- **主键**：`cidr`
- **来源**：`data/format/ip_route_entity.csv`
- **字段说明**：`cidr, descr, origin, mnt_by, last_modified, source`

### 3.9 `ipv4_entity`

- **主键**：`prefix`
- **来源**：`data/format/ipv4_entity.csv`
- **字段说明**：`prefix, prefix_len, source, country, org_id, date, status, org_name, sibling_as, uuid`

### 3.10 `ipv6_bgp_entity`

- **主键**：`prefix + bgp`
- **来源**：`data/format/ipv6_bgp_entity_YYYY-MM-DD.csv`
- **字段说明**：`prefix, prefix_len, name, descr, route, bgp, admin_prefix, admin_route, admin_bgp, org_handle_prefix, org_name_prefix, org_name_cn_prefix, org_uuid_prefix, org_handle_bgp, org_name_bgp, org_name_cn_bgp, org_uuid_bgp, country, source, date, inetnum, rdap, rpki`

### 3.11 `ipv6_entity`

- **主键**：`prefix`
- **来源**：`data/format/ipv6_entity.csv`
- **字段说明**：`prefix, prefix_len, source, country, org_id, date, status, org_name, sibling_as, uuid`

### 3.12 `ipv6_inetnum_entity`

- **主键**：`cidr`
- **来源**：`data/format/ipv6_inetnum_entity.csv`
- **字段说明**：`cidr, netname, descr, country, source, admin_c, tech_c, abuse_c, org, org_name, org_name_cn, org_uuid`

### 3.13 `ipv6_rdap_entity`

- **主键**：`cidr`
- **来源**：`data/format/ipv6_rdap_entity.csv`
- **字段说明**：`cidr, netname, descr, country, source, admin_c, tech_c, abuse_c, org, org_name, org_name_cn, org_uuid`

### 3.14 `ipv6_route_entity`

- **主键**：`cidr`
- **来源**：`data/format/ipv6_route_entity.csv`
- **字段说明**：`cidr, descr, origin, mnt_by, last_modified, source`

### 3.15 `org_entity`

- **主键**：`uuid`
- **来源**：`data/format/org_entity_YYYY-MM-DD.csv`
- **字段说明**：`uuid, org_country, org_country_cn, org_name, org_name_cn, sibling_as, v4prefixes, v6prefixes, sibling_as_num, v4prefixes_num, v6prefixes_num`

### 3.16 `website_entity`

- **主键**：`url`
- **来源**：`data/format/website_entity_base.csv` + `data/format/domain_cn.csv`
- **字段说明**：`url, title, key, description, industry, ip, ip_prefix, auth_ip, auth_ip_prefix`

---

## 4. 表之间的关联关系（重点）

1. **AS ↔ 组织**
   - 关联键：`as_entity.uuid` ↔ `org_entity.uuid`
   - 说明：`as_entity` 中的 `sibling_as` 可被聚合进入 `org_entity` 的 `sibling_as` 列表。

2. **AS ↔ ASN 委托**
   - 关联键：`as_entity.asn` ↔ `asn_entity.asn`
   - 说明：`asn_entity` 提供委托基础信息，`as_entity` 为融合与画像结果。

3. **前缀 ↔ AS 归属（BGP/注册）**
   - 关联键：`ip_bgp_entity.route` / `ip_bgp_entity.bgp` ↔ `as_entity.asn`
   - 说明：`route` 表示注册归属 AS，`bgp` 表示观测归属 AS，可用于一致性核验。

4. **前缀 ↔ 组织**
   - 关联键：`ip_bgp_entity.org_uuid_prefix/org_uuid_bgp` ↔ `org_entity.uuid`
   - 说明：前缀的注册侧与 BGP 侧组织归属可能不同。

5. **前缀 ↔ 国家**
   - 关联键：`ip_bgp_entity.country` ↔ `country_entity.country`
   - 说明：提供国家维度的路由与归属聚合分析。

6. **IPv4/IPv6 委托 ↔ 组织/AS**
   - 关联键：`ipv4_entity.uuid`/`ipv6_entity.uuid` ↔ `org_entity.uuid`；`sibling_as` ↔ `as_entity.asn`
   - 说明：委托前缀与组织、AS 家族建立映射。

7. **INETNUM/RDAP/ROUTE 三类注册信息对齐**
   - 关联键：`cidr`
   - 说明：`ip_inetnum_entity`、`ip_rdap_entity`、`ip_route_entity`（IPv6 对应表）可通过 `cidr` 对齐进行差异比对。

8. **网站/域名 ↔ IP/前缀 ↔ AS**
   - 关联链路：`website_entity.ip/auth_ip` → IP 前缀（匹配 `ip_bgp_entity.prefix`）→ `bgp/route` → `as_entity`
   - 说明：由域名/网站解析结果向上追溯 ASN 与组织。

9. **行业域名 ↔ AS/组织**
   - 关联链路：`industry_entity.ip_asn` ↔ `as_entity.asn`；`industry_entity.ip_org/auth_ip_org` 可与 `org_entity.org_name` 进行文本匹配。

---

## 5. 系统功能与面试展示切入点

- **IP 归属查询**：`IP → prefix → bgp/route → ASN → 组织/国家`
- **AS 画像展示**：`ASN → 组织 → BGP 上下游/对等 → 前缀集合 → 国家分布`
- **归属一致性核验**：`route ASN` 与 `bgp ASN` 不一致前缀识别
- **域名溯源**：`域名 → 解析 IP → 前缀 → ASN → 组织`
- **注册信息审计**：`inetnum/rdap/route` 三表对齐审计

---

## 6. Neo4j 图谱设计（AS 疆域分析）

**目标**：基于 `ip_bgp_entity` 的 IPv4 前缀国家归属，计算 AS 的“地理疆域”（国家级），并写入 Neo4j 便于多跳关系查询与图算法。

**节点设计**：

- `(:AS {asn, org_name, org_name_cn, org_country, org_country_cn, uuid, territory_country, territory_p24_count, total_p24_count, confidence})`
- `(:Country {country, country_en, country_cn, region})`

**关系设计**：

- `(:AS)-[:TERRITORY {country_p24_count, total_p24_count, confidence}]->(:Country)`

**数据来源**：

- `ip_bgp_entity_YYYY-MM-DD.csv`：`prefix_len` 转换为 `/24` 计数，按 `country` 聚合得到疆域\n- `as_entity_YYYY-MM-DD.csv`：补充组织名称、国家等属性\n- `country_entity_YYYY-MM-DD.csv`：补充国家中英文名称

**工具入口**：

- 生成 CSV：`agent/tools/as_territory_tools.py`（自动使用最新日期）\n- 写入 Neo4j：`agent/tools/as_territory_tools.py --load-neo4j`

---

## 7. 导入策略与注意事项

1. **结构化事实源仍为 16 张核心表**：默认先导入 PostgreSQL，再同步导入 Neo4j 图谱。
2. **日期快照只保留一份**：数据库表名不带日期，需选择最新或指定日期导入。
3. **无数据才重新导入**：如 16 表已存在且有数据，导入流程会跳过。
4. **多值字段需要解析**：例如 `sibling_as`、`geo_country_list`、`ip_prefix` 等。
5. **审计触发器默认关闭**：避免生成 `_audit` 表，确保仅保留 16 张核心表。
6. **网站 CSV 分隔符特殊**：`website_entity_base.csv` 为 `;` 分隔，首列为空需忽略。
7. **AS 疆域分析目前为国家级**：缺少省市级离线地理库，暂无法输出省/市置信度。
8. **RAG 增量写入默认去重**：`agent/tools/rag_tool.py` 在写入 Milvus 前按 `source + text` 哈希执行批内与存量去重，避免重复切片污染检索结果。
9. **chapter_5 示例路径已补齐**：仓库已包含 `agent/knowledge/bgp/hijack_detection.md`，可直接按文档复现索引构建示例。
10. **Compose 已移除自动 CSV 导入服务**：`docker/docker-compose.yml` 不再包含 `loader`，避免“每次启动都执行导入”；如需导入需手动执行 `python -m agent.scripts.load_all_csv`。
11. **NL2SQL Prompt 新增注释语义辅助**：`agent/core/schema.py` 会解析 `database/core_schema_comments.review.sql` 中的 `COMMENT ON TABLE/COLUMN`，并在 `agent/tools/nl2sql_tool.py` 组装表上下文时拼接“表说明 + 字段释义”辅助 SQL 生成。
12. **双库一致性导入已并入 `load_all_csv`**：默认执行 PostgreSQL + Neo4j，Neo4j 失败会重试一次，仍失败则回滚到旧快照（PG prepared transaction + Neo4j 单事务）。
13. **Neo4j 主图导入入口迁移**：标准入口为 `python -m agent.scripts.neo4j_graph_loader`；`agent.tools.neo4j_graph_loader` 仅保留兼容转调。
14. **MCP 图查询对外收敛**：仅暴露 `neo4j_llamaindex_query`，不再对外暴露 `neo4j_query`。

以上即为当前项目的完整数据格式、功能与表间关联说明，可直接用于面试项目讲解或后续 Agent/知识图谱落地。
