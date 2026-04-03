# 互联网域间路由知识谱系 Skill 拆分说明

## 生成目的
- 将《互联网域间路由安全监测与防御》**第三章（互联网域间路由知识谱系）**按细粒度子节拆分为独立 skill，便于在对话中按主题精确触发与检索。
- 减少单次加载的上下文体量，提高回答的针对性与可复用性。
- 为后续新增/替换章节内容提供低成本更新路径（按小节替换 references 即可）。

## 生成逻辑
1) 只处理第三章内容，其他章节不参与拆分。  
2) 从 `agent/knowledge/互联网域间路由安全监测与防御.docx` 提取正文段落，忽略目录（TOC）段落。  
3) 使用标题编号规则识别结构：
   - `3.x` 作为章节内小节（父级）  
   - `3.x.x` 作为细粒度子节（skill 最小单元）
4) 每个 `3.x.x` 子节生成一个 skill：
   - `skills/<skill-name>/SKILL.md`
   - `skills/<skill-name>/references/content.md`
5) 子节内容按文档原序抽取，保持原始表述与术语；表格与列表以纯文本形式保留。
6) 对目录中重复编号 `3.4.2` 的两个标题，按**完整标题文本**区分并生成不同 skill。

## 拆分结果（细粒度）
共生成 21 个 skill，分别对应第三章所有 `3.x.x` 子节：
- `as-number-allocation` → 3.1.1 AS号码分配
- `ip-address-allocation` → 3.1.2 IP地址分配
- `rir-registration-db` → 3.2.1 互联网号码注册信息库
- `irr-route-registry` → 3.2.2 互联网路由注册信息库
- `whois-protocol` → 3.2.3 WHOIS信息查询协议
- `rdap-protocol` → 3.2.4 RDAP注册数据访问协议
- `prefix-as-mapping` → 3.3.1 AS路由前缀映射
- `as-peer-relationships` → 3.3.2 AS Peer关系
- `route-propagation-paths` → 3.3.3 路由传播路径
- `prefix-visibility` → 3.3.4 路由前缀可见性
- `as-topology` → 3.3.5 AS级别网络拓扑
- `website-topic-classification` → 3.4.1 网站行业主题分类
- `website-ip-mapping` → 3.4.2 网站多源IP映射
- `authoritative-dns-ip-mapping` → 3.4.2 权威解析IP地址映射
- `as-relationship-inference` → 3.5.1 AS商业关系推断
- `as-organization-mapping` → 3.5.2 AS组织机构映射
- `as-type-classification` → 3.5.3 AS性质分类
- `as-ranking` → 3.5.4 AS等级排名
- `as-geo-territory` → 3.5.6 AS地理疆域
- `routing-ontology` → 3.6.1 域间路由知识本体
- `routing-knowledge-graph` → 3.6.2 域间路由知识图谱

## 目录结构
```
skills/<skill-name>/
├── SKILL.md
└── references/
    └── content.md
```

## 采用该拆分方案的理由
- **可检索性强**：每个子节作为最小知识单元，适合检索驱动的精确触发。
- **上下文精简**：避免整章加载导致 token 浪费，提升回答效率。
- **维护成本低**：局部更新不影响其他 skill，适合持续演进。
