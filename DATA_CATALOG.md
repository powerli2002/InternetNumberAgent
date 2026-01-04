# fusionprocessing 数据介绍文档（面向 Agent + RAG，v1）

本文档基于 `/home/back_data/fusionprocessing` 当前已有的代码与数据目录梳理，重点说明**已存在可用数据**、其**目录结构**、**文件格式/字段**、以及数据的**融合特点与注意事项**（便于后续做 Agent+RAG 的检索与结构化查询）。

---

## 1. 数据在项目中的位置与总体规模

项目的核心输出目录由 `conf/config.yaml` 指定：

- `output_dir: "./data/"`：融合后的实体数据输出根目录
- `rib_dir: "./bgp_data/data/"`：BGP RIB（经 `bgpdump` 解码后的 `|` 分隔文本）输入目录
- `rir_format_dir: "../rirdata/data/format/"`：RIR（WHOIS/RDAP/委托数据）解析后的输入目录（不在本仓库内，但本项目处理逻辑依赖它）

当前仓库内与数据相关的主要目录（约略大小）：

- `data/`：约 **32GB**（主要为 `data/format/` 的大体量 CSV 快照）
- `bgp_data/`：约 **6.9GB**（RIB 文本数据，按 RIS collector 分文件）
- `logs/`：约 **2.5MB**（程序运行日志）
- `rir_data/`：当前仅占位（`.gitkeep`）

---

## 2. 目录结构（数据视角）

```
fusionprocessing/
  data/
    format/          # 主要“实体表”输出（CSV；大量按日期快照）
    org_entity/      # AS↔组织 映射的中间结果（分 RIR 子目录）
    static/          # 静态字典/外部数据（CAIDA/翻译表/AS 类型等）
    utils/           # 国家/时区/ISO 等小型工具表
    export/          # 导出结果（例如 as_entity 的 CN 子集）
    diff.csv         # 额外生成的差异/抽样文件（字段与 as_entity 类似）
  bgp_data/
    data/            # RIB 文本（*.data），被 rib_parser/rib_formatter 读取
    bgpdump          # bgpdump 可执行文件（用于 MRT->文本）
    logs/            # 拉取/解码 BGP 数据过程日志
```

---

## 3. `data/format/`：核心实体数据（建议 RAG/检索主入口）

`data/format/` 下为本项目“融合后的标准化实体表”，绝大多数是 CSV；文件命名通常遵循：

- `xxx_entity_YYYY-MM-DD.csv`：按日期快照（同一实体多版本）
- `xxx_entity.csv` / `xxx_entity_base.csv`：不带日期的“当前/基线”版本

已观察到的快照范围：

- `as_entity_*`：5 个快照（`2024-07-14` ~ `2024-08-12`）
- `ip_bgp_entity_*`：5 个快照（`2024-07-14` ~ `2024-08-12`）
- `org_entity_*` / `country_entity_*` / `industry_entity_*`：各 5 个快照（`2024-07-14` ~ `2024-08-12`）
- `resolve_result_*`：88 个快照（`2024-07-16` ~ `2025-06-17`）
- `rib_data_*`：4 个快照（`2024-07-13` ~ `2024-09-30`）

当前目录统计（以 `data/format/` 实际文件为准，可能随时间变化）：

| 分组（按文件名前缀） | 文件数 | 合计大小 | 备注 |
| --- | ---: | ---: | --- |
| `as_entity` | 6 | ~14.1GB | 含 5 个日期快照 + `as_entity_base.csv` |
| `ip_bgp_entity` | 6 | ~4.2GB | 含 5 个日期快照 + `ip_bgp_entity.csv` |
| `resolve_result` | 88 | ~4.3GB | 高频快照（域名解析/补全） |
| `rib_data` | 4 | ~4.1GB | 早期快照体量大，最新快照较小 |
| `website_entity` | 1 | ~2.6GB | 分号分隔；首列为 index |
| `ip_inetnum_entity` | 1 | ~579MB | IPv4 inetnum 汇总 |
| `org_entity` | 5 | ~147.9MB | 组织画像快照 |
| `country_entity` | 5 | ~141.8MB | 国家画像快照 |
| `industry_entity` | 5 | ~386.8MB | 行业画像快照 |
| 其余（`ipv4_entity`、`ipv6_*` 等） | 若干 | ~数十~数百 MB | 体量相对较小 |

### 3.1 AS 实体：`as_entity_base.csv` 与 `as_entity_YYYY-MM-DD.csv`

用途：以 ASN 为主键，融合 RIR 委托信息、RDAP/WHOIS 联系人、CAIDA rank/组织、AS 类型、地理与中文翻译、以及（在带日期版本中）RIB 拓扑与前缀信息。

来源与生成代码：

- 生成：`src/as_entity/as_entity_formatter.py`
- RIB 拓扑：`src/as_entity/rib_parser.py`（输出 `rib_data_YYYY-MM-DD.csv`）

文件与字段：

- `data/format/as_entity_base.csv`（44 列，**基础版**，不含 RIB 衍生字段）：
  - `asn, source, opq_id, date, status`：RIR 委托基础字段（日期字段通常为委托记录日期）
  - `descr, descr_cn, website, aut_name`：描述/翻译/网站/名称归一
  - `registration_date, last_change_date`：注册/变更时间（多来自 RDAP）
  - `org_handle, org_id, uuid, org_name, org_name_cn`：组织归属信息（`uuid` 为组织级主键）
  - `administrative, technical, abuse` + `admin_info, tech_info, abuse_info`：联系人 handle 与其结构化信息（通常为 JSON 字符串）
  - `as_rank, as_longitude, as_latitude`：CAIDA rank/地理（近似）
  - `type, type_cn`：AS 类型（如 ISP 等）
  - `geo_country_list/...`：AS 关联国家/城市/坐标（列表字段，见“数据特点”）
  - `import, export, import_as, export_as`：路由 import/export 规则（列表字段）

- `data/format/as_entity_YYYY-MM-DD.csv`（55 列，**完整版** = base + RIB 衍生字段）：
  - 在 base 基础上增加：
    - `v4Upstream, v4Peer, v4Downstream, v4Propagation, v4Prefixes`
    - `v6Upstream, v6Peer, v6Downstream, v6Propagation, v6Prefixes`
    - `is_route`：是否在 RIB 中观测到前缀/传播（布尔）

备注：

- `sibling_as`、`v4Prefixes` 等列在 CSV 中通常是“Python 列表字面量字符串”（例如 `"[123, 456]"` 或 `"['1.2.3.0/24']"`），读取后需 `ast.literal_eval` 才能当作数组使用。

### 3.2 AS 委托实体：`asn_entity.csv`

用途：RIR 委托维度的 ASN 清单（更轻量），并补充与组织 `uuid` 的映射。

- 文件：`data/format/asn_entity.csv`
- 字段：
  - `asn, source, country, opq_id, date, status, org_name, uuid`
- 生成：`src/ip_entity/ip_delegate_formatter.py`（同时生成 `ipv4_entity.csv`/`ipv6_entity.csv`）

### 3.3 IP/BGP 路由实体：`ip_bgp_entity_YYYY-MM-DD.csv` 与 `ip_bgp_entity.csv`

用途：以“路由前缀”为主键，融合：

- BGP RIB 中观测的归属 ASN（`bgp`）
- RIR route/inetnum/rdap 中注册的归属 ASN（`route`）与联系人/组织
- 前缀对应的域名（`domain`）与权威域名（`domain_auth`）信息（列表）

文件与字段：

- `data/format/ip_bgp_entity_YYYY-MM-DD.csv`（27 列，完整版）：
  - `prefix, prefix_len`：前缀与长度
  - `route`：注册归属 AS（可能为 `|` 分隔的 AS 集合字符串）
  - `bgp`：RIB 观测归属 AS（单个 ASN）
  - `name, descr`：网络名称/描述（多来自 inetnum/rdap）
  - `admin_prefix, admin_route, admin_bgp`：前缀/route/BGP 侧的管理联系人（handle/映射）
  - `org_handle_prefix/org_handle_bgp` 与 `org_name_* / org_name_cn_* / org_uuid_*`：组织信息（前缀侧与 bgp 侧）
  - `inetnum, rdap, rpki`：是否命中相应数据源/校验的信息标记（实现细节见 `src/ip_entity/ip_bgp_formatter.py`）
  - `domain, domain_num, domain_auth, domain_auth_num`：域名列表与数量（列表字段）

- `data/format/ip_bgp_entity.csv`（18 列，轻量版）：
  - 去除部分中文名/uuid/rpki 等字段，适合快速检索或做 join 的“摘要表”。

IPv6 对应：

- `data/format/ipv6_bgp_entity_YYYY-MM-DD.csv`（23 列，字段与 IPv4 类似，但不含 `domain*` 列）

### 3.4 IP 分配/注册实体：`ip_inetnum_entity.csv`、`ip_rdap_entity.csv`、`ip_route_entity.csv`（及 IPv6 版本）

用途：将 RIR 原始 inetnum/rdap/route 对象整理为标准表，便于对前缀做“注册信息检索”和与组织映射。

- `data/format/ip_inetnum_entity.csv`（12 列）
- `data/format/ip_rdap_entity.csv`（12 列）
- `data/format/ip_route_entity.csv`（6 列）
- IPv6：`data/format/ipv6_inetnum_entity.csv`、`data/format/ipv6_rdap_entity.csv`、`data/format/ipv6_route_entity.csv`

字段（inetnum/rdap 两者一致）：

- `CIDR, netname, descr, country, source`
- `admin-c, tech-c, abuse-c`：联系人 handle
- `org`：组织 handle
- `org_name, org_name_cn, org_uuid`：由 `as_entity` 中 `org_handle→uuid` 映射补齐

生成：`src/ip_entity/ip_reg_formatter.py`

### 3.5 IP 委托实体：`ipv4_entity.csv`、`ipv6_entity.csv`

用途：RIR 委托维度的“前缀清单”。

- `data/format/ipv4_entity.csv` / `data/format/ipv6_entity.csv`（各 10 列）
- 字段：`prefix, prefix_len, source, country, org_id, date, status, org_name, sibling_as, uuid`

### 3.6 RIB 衍生数据：`rib_prefix_base.csv`、`rib_v6_prefix_base.csv`、`rib_data_YYYY-MM-DD.csv`

用途：

- `rib_prefix_base.csv` / `rib_v6_prefix_base.csv`：前缀→BGP 归属 ASN 的基础映射（2 列：`prefix, as`）
- `rib_data_YYYY-MM-DD.csv`：按 ASN 聚合的拓扑与前缀/传播信息（6 列：`v4Upstream, v4Peer, v4Propagation, v4Prefixes, v4Downstream, asn`；IPv6 信息在部分版本中可能另列或并入）

生成：

- 前缀映射：`src/ip_entity/rib_formatter.py`
- ASN 聚合：`src/as_entity/rib_parser.py`

### 3.7 组织实体：`org_entity_YYYY-MM-DD.csv`

用途：以组织 `uuid` 为主键，从 `as_entity_YYYY-MM-DD.csv` 聚合得到组织级画像。

- 文件：`data/format/org_entity_YYYY-MM-DD.csv`（11 列）
- 字段：`uuid, org_country, org_country_cn, org_name, org_name_cn, sibling_as, v4Prefixes, v6Prefixes, sibling_as_num, v4Prefixes_num, v6Prefixes_num`
- 生成：`src/org_entity/org_entity_formatter.py`

### 3.8 国家实体：`country_entity_YYYY-MM-DD.csv`

用途：以国家代码为主键，融合人口/互联网用户/GDP 等基础信息，并从 `as_entity` 汇总 ASN/前缀/组织数量与列表。

- 文件：`data/format/country_entity_YYYY-MM-DD.csv`（18 列）
- 生成：`src/country_entity/country_entity_formatter.py` + `data/utils/country_info.csv`

### 3.9 域名/网站/行业：`website_entity_base.csv`、`domain_cn.csv`、`resolve_result_YYYY-MM-DD.csv`、`industry_entity_YYYY-MM-DD.csv`

用途：承载“网站/域名 → IP → 前缀 → ASN/组织”的链路信息，可用于 RAG 的网站画像、行业归属、以及反查网络侧归属。

- `data/format/website_entity_base.csv`（**分号分隔**；10 列，首列为空为 index）
  - 列：`(index), url, title, key, description, industry, ip, ip_prefix, auth_ip, auth_ip_prefix`
  - `ip/auth_ip` 通常为 IP 列表（字符串形式）

- `data/format/domain_cn.csv`（10 列）
  - `url, title, industry, description, key, location, ip, ip_prefix, auth_ip, auth_ip_prefix`

- `data/format/resolve_result_YYYY-MM-DD.csv`（6 列；88 个快照）
  - `url, title, description, key, ip, auth_ip`

- `data/format/industry_entity_YYYY-MM-DD.csv`（14 列）
  - `url, parent, title, industry, description, key`
  - `ip, ip_prefix, ip_asn, ip_org`
  - `auth_ip, auth_ip_prefix, auth_ip_asn, auth_ip_org`
  - 生成：`src/dns_entity/industry_entity_formatter.py`（依赖 `domain_cn.csv`、`resolve_result_*`、`ip_bgp_entity_*`、`as_entity_*`）

---

## 4. `data/org_entity/`：AS ↔ 组织映射中间结果（含联系方式，注意敏感信息）

用途：将不同 RIR 的组织对象（org handle）进行聚类合并，并生成 `asn -> org(uuid)` 的映射，为 `as_entity` 中的 `uuid/org_name` 补全提供依据。

顶层文件：

- `data/org_entity/as_org_mapping.csv`（13 列）：核心映射结果（最终被 `as_entity_formatter` 使用）
  - `uuid`：组织主键（由 `org_name` 生成的 UUID5）
  - `asn`：ASN（每行一个 ASN；同一 `uuid` 会对应多行）
  - `sibling`：该组织下的 ASN 集合（列表字符串）
  - `handle/email/address/tel...`：组织联系方式（可能包含邮箱/电话/地址等）
- `data/org_entity/org_only.csv`（3 列）：组织去重摘要（`uuid, org_name, descr`）
- `data/org_entity/unsolved_as.txt`：未能映射到组织的 ASN 列表

RIR 子目录（`afrinic/ apnic/ arin/ lacnic/ ripe/`）常见文件：

- `{rir}_as_info_with_mail_key.csv`：按 ASN 的联系方式抽取与标准化（含 `*_email_key` 聚类键）
- `{rir}_org_handle_group.csv` / `{rir}_merged_org_handle_group.csv`：以 org handle 与 mail_key 为线索的聚类中间表
- `{rir}_final_merged.csv`：聚类后的组织对象（handle→name/sibling 等）
- `{rir}_unslove_mail_group.csv`：无法用 mail_key 处理的残余项

生成逻辑主要在：

- `src/org_entity/org_as.py`
- `src/org_entity/as_with_mail_key.py`

---

## 5. `data/static/`：静态字典与外部数据（CAIDA/翻译/分类）

典型文件与用途：

- `as_rank.csv` / `as_rank_20250330.csv`：CAIDA AS Rank（含 `rank/asnName/organization/country/degree/cone` 等）
- `asns.jsonl`：CAIDA AS Rank 的 JSONL 原始/近原始导出（单行一个 ASN）
- `org_data.csv`：CAIDA 组织维度数据（`orgId/orgName/rank/country/...`）
- `as_geo.csv`：ASN→国家/城市/经纬度（列表字段）
- `asdb.csv` / `asdb_2024-0130.csv`：ASN 分类（简版与多层分类版）
- `as_translate.csv` / `org_translate.csv`：描述/组织名中文翻译与修正
- `ddos_as.csv`：疑似 DDoS provider 的 ASN 列表（用于 `as_entity` 的 `is_ddos_provider`）
- `TLD.csv`、`NAICSlite.csv`：TLD/行业层级等小型字典

---

## 6. `data/utils/`：国家/时区/ISO 工具表

用于补全国家信息、映射中文国家名等：

- `data/utils/country_info.csv`
- `data/utils/iso3166.csv`
- `data/utils/timezones.csv`
- `data/utils/country_rir.csv`
- `data/utils/country-capital-lat-long-population.csv`

---

## 7. `bgp_data/data/`：BGP RIB 输入数据（大文件，按 collector 分片）

该目录包含若干 `rrcXX-bview.YYYYMMDD.HHMM.data` 文件（当前为 `20250612` 批次），单文件数百 MB。

当前目录内约：

- `*.data` 文件 21 个
- 最大单文件约 728MB（`rrc00-bview.20250612.0000.data`）

在代码中这些文件被当作文本读取，行格式被假定为 `|` 分隔，且：

- `route[5]` 为前缀
- `route[6]` 为 ASPath（空格分隔 ASN 序列）

使用位置：

- `src/as_entity/rib_parser.py`：生成 `data/format/rib_data_YYYY-MM-DD.csv`（按 ASN 聚合拓扑/前缀）
- `src/ip_entity/rib_formatter.py`：生成 `data/format/rib_prefix_base.csv`（前缀→bgp ASN）

备注：

- `bgp_data/bgpdump` 为辅助工具（将 MRT/RIB 转为文本）；`bgp_data/get_bgp_data.py` 可能用于拉取/解码数据（仓库内存在该脚本）。

---

## 8. 数据特点与注意事项（做 Agent+RAG 时尤其重要）

### 8.1 多源融合、字段语义“同名不同源”

同一概念可能来自多个来源并在字段中并存，例如：

- `route`（注册归属 AS，来自 route-whois / RDAP originAS） vs `bgp`（观测归属 AS，来自 RIB）
- `org_handle_prefix`（前缀侧组织） vs `org_handle_bgp`（BGP 侧组织/AS 侧组织）

Agent 侧做解释/推理时应明确“注册/观测”差异。

### 8.2 大量列表字段以字符串存储

常见列：`sibling_as`、`v4Prefixes`、`domain`、`geo_country_list`、`import/export` 等。

表现形式：CSV 单元格里是 Python 字面量字符串（如 `"['a', 'b']"`、`\"[1, 2, 3]\"`），需要解析后才能用于过滤/统计/倒排。

### 8.3 文件分隔符与索引列不统一

- 大多数为逗号分隔 CSV
- `website_entity_base.csv` 为分号分隔，且首列为空（pandas 导出 index）
- `data/export/as_entity_CN_2024-07-22.csv` 也带 index 列（首列为空）

### 8.4 规模很大，建议“结构化库 + 向量库”混合

`as_entity_*`、`website_entity_base.csv`、`resolve_result_*` 等体量很大；建议：

- 结构化查询（过滤/聚合/join）：PostgreSQL（仓库内已有持久化逻辑：`src/utils/entity_persistence.py`）
- 语义检索（描述/标题/行业/组织名等）：向量库（以 ASN/前缀/域名/组织为文档粒度）

### 8.5 含联系方式等潜在敏感信息

`data/org_entity/*` 与 `as_entity*` 可能包含邮箱、电话、地址等字段。用于 RAG 时应评估脱敏策略与访问控制。

---

## 9. 面向 Agent+RAG 的“可索引对象”建议（落地口径）

建议将以下对象作为 RAG 的文档粒度（Document），并将关键字段作为 metadata：

- ASN 文档：来自 `data/format/as_entity_YYYY-MM-DD.csv`
  - 主键：`asn`
  - 文本：`aut_name/descr/descr_cn/type/type_cn/org_name/org_name_cn`
  - 元数据：`as_country/source/is_route/is_ddos_provider/org(uuid/org_country)`
- 前缀文档：来自 `data/format/ip_bgp_entity_YYYY-MM-DD.csv`（IPv4+IPv6）
  - 主键：`prefix`
  - 文本：`name/descr`
  - 元数据：`bgp/route/country/source/org_uuid_prefix/org_uuid_bgp/rpki`
- 组织文档：来自 `data/format/org_entity_YYYY-MM-DD.csv` + `data/org_entity/org_only.csv`
  - 主键：`uuid`
  - 文本：`org_name/org_name_cn/descr`
  - 元数据：`org_country/sibling_as_num/v4Prefixes_num/v6Prefixes_num`
- 域名/网站文档：来自 `data/format/domain_cn.csv`、`data/format/industry_entity_YYYY-MM-DD.csv`
  - 主键：`url`
  - 文本：`title/description/key/industry`
  - 元数据：`ip_asn/ip_org/auth_ip_asn/auth_ip_org`

---

## 10. 附：已存在导出数据

- `data/export/as_entity_CN_2024-07-22.csv`：`as_country == 'CN'` 的 AS 实体子集（带 index 列）
