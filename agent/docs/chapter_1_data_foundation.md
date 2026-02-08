# Chapter 1: 领域数据融合与组织 (Data Foundation)

## [核心机制]

### 1.1 双轨并行架构：注册侧 vs 观测侧

系统的数据底座采用"注册侧 + 观测侧并行保留"原则，这是整个系统的设计哲学核心：

**注册侧（Registry）**：RIR/WHOIS/RDAP
- 来源：ARIN、RIPE、APNIC、LACNIC、AFRINIC 五大 RIR
- 特点：法定分配记录，权威但可能滞后
- 对应字段：`route`（来自 ip_route_entity）、`org_handle_prefix`

**观测侧（Observed）**：BGP 路由表
- 来源：RouteViews、RIPE RIS 等观测点
- 特点：实时网络传播，反映真实使用但可能有劫持
- 对应字段：`bgp`（来自 BGP Collector）、`org_handle_bgp`

**为什么并行而非覆盖**：
```sql
-- 典型冲突案例：注册归属与实际传播不一致
SELECT 
    prefix,
    route AS registry_asn,
    bgp AS observed_asn,
    org_name_prefix AS registry_org,
    org_name_bgp AS observed_org,
    CASE 
        WHEN route = bgp THEN '一致'
        ELSE '冲突'
    END AS consistency_check
FROM ip_bgp_entity
WHERE route IS NOT NULL AND bgp IS NOT NULL
  AND route != bgp
LIMIT 5;
```

输出示例：
```text
prefix          registry_asn  observed_asn  registry_org        observed_org         consistency_check
1.0.1.0/24      13335         23911        Cloudflare          Hurricane Electric   冲突
8.8.8.0/24      15169         15169        Google LLC          Google LLC           一致
```

### 1.2 16 张核心表设计原则

**实体化优先，非日志优先**：
- ❌ 不做：存储原始 WHOIS 文本、BGP Update 消息
- ✅ 应做：提取实体画像（AS/Prefix/Org），建立清晰关联关系

**表设计分层**：

```
[委托层] asn_entity, ipv4_entity, ipv6_entity
    ↓ 法定分配
[注册层] ip_inetnum_entity, ip_rdap_entity, ip_route_entity
    ↓ RIR 注册记录
[观测层] ip_bgp_entity, ipv6_bgp_entity
    ↓ BGP 观测
[实体聚合层] as_entity, org_entity, country_entity
    ↓ 多源融合
[应用层] website_entity, industry_entity
```

**关键关联链路**：
```sql
-- 链路 1: IP 前缀 → AS → 组织 → 国家
SELECT 
    ib.prefix,
    ib.bgp AS asn,
    ae.org_name,
    ae.org_country,
    ce.country_cn
FROM ip_bgp_entity ib
JOIN as_entity ae ON ib.bgp = ae.asn
JOIN country_entity ce ON ae.org_country = ce.country
WHERE ib.prefix >>= '8.8.8.8'::inet
LIMIT 1;
```

### 1.3 多值字段编码约定

**Python 列表字符串 → PostgreSQL Array**：

CSV 中存储的是 **Python 字面量字符串**：
```csv
asn,v4Peer,sibling_as
4134,"[174, 209, 3356, 7018]","[4809, 4811]"
```

导入流程（`scripts/load_all_csv.py` 核心逻辑）：

```python
import ast
from typing import Any, List

def parse_python_list(value: str) -> List[Any]:
    """
    解析 CSV 中的 Python 列表字符串为实际列表
    
    输入: "[174, 209, 3356]"
    输出: [174, 209, 3356]
    """
    if not value or value == "[]":
        return []
    try:
        parsed = ast.literal_eval(value)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, SyntaxError):
        return []

def convert_to_pg_array(py_list: List[Any], array_type: str) -> str:
    """
    将 Python 列表转为 PostgreSQL ARRAY 语法
    
    输入: [174, 209, 3356], 'bigint[]'
    输出: '{174,209,3356}'
    """
    if not py_list:
        return '{}'
    # PostgreSQL ARRAY 字面量格式
    elements = ','.join(str(item) for item in py_list)
    return f'{{{elements}}}'
```

**执行结果对比**：

Python 侧（导入前）：
```python
row = {
    'asn': 4134,
    'v4Peer': "[174, 209, 3356, 7018]",  # 字符串
    'sibling_as': "[4809, 4811]"
}
```

PostgreSQL 侧（导入后）：
```sql
SELECT asn, v4peer, sibling_as FROM as_entity WHERE asn = 4134;

-- 结果：
asn  | v4peer                | sibling_as
4134 | {174,209,3356,7018}   | {4809,4811}

-- 类型验证：
SELECT pg_typeof(v4peer) FROM as_entity LIMIT 1;
-- bigint[]
```

**联系信息字段（JSON 编码）**：

CSV 中存储 JSON 字符串：
```csv
asn,admin_info
4134,"{\"name\": \"Zhang San\", \"email\": \"admin@example.com\"}"
```

PostgreSQL 存储为 `jsonb`：
```sql
SELECT 
    asn,
    admin_info->>'name' AS admin_name,
    admin_info->>'email' AS admin_email
FROM as_entity 
WHERE admin_info IS NOT NULL 
LIMIT 1;

-- 结果：
asn  | admin_name | admin_email
4134 | Zhang San  | admin@example.com
```

## [代码映射]

### 2.1 数据处理主链路

**目录结构**：
```
src/
├── parse/          # RIR/WHOIS/BGP 原始数据解析
├── clean/          # 数据清洗与规范化
├── entity/         # 实体化逻辑
└── format/         # CSV 格式化器
```

**核心处理流程**（`src/utils/entity_persistence.py`）：

```python
class EntityPersistence:
    """
    实体持久化管理器
    
    核心职责：
    1. 识别 CSV 列与数据库列的映射关系
    2. 处理特殊字段（Python 列表、JSON、CIDR）
    3. 批量写入并处理冲突
    """
    
    def load_csv(self, table_name: str, csv_path: Path):
        """
        CSV 导入核心逻辑
        
        步骤：
        1. 读取 CSV 头，映射到表字段
        2. 逐行解析特殊字段（parse_array, parse_json）
        3. 使用 COPY 或 INSERT ... ON CONFLICT 批量写入
        """
        # 伪代码示意
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 特殊字段处理
                if 'v4Peer' in row:
                    row['v4Peer'] = self.parse_array(row['v4Peer'])
                if 'admin_info' in row:
                    row['admin_info'] = json.loads(row['admin_info'])
                # 插入数据库
                self.insert_row(table_name, row)
```

### 2.2 核心表结构（`database/core_schema.sql`）

**示例：`ip_bgp_entity` 表定义**

```sql
CREATE TABLE IF NOT EXISTS ip_bgp_entity (
    -- 前缀标识
    prefix cidr PRIMARY KEY,
    prefix_len integer,
    
    -- 双轨归属（核心）
    route bigint,        -- 注册归属 ASN (from ip_route_entity)
    bgp bigint,          -- 观测归属 ASN (from BGP collector)
    
    -- 描述信息
    name text,
    descr text,
    
    -- 联系人（三源）
    admin_prefix text,   -- 前缀注册联系人
    admin_route text,    -- 路由对象联系人
    admin_bgp text,      -- BGP 宣告 AS 联系人
    
    -- 组织归属（双轨）
    org_uuid_prefix uuid,   -- 前缀注册组织
    org_name_prefix text,
    org_name_cn_prefix text,
    org_uuid_bgp uuid,      -- BGP 宣告组织
    org_name_bgp text,
    org_name_cn_bgp text,
    
    -- 地理与来源
    country char(2),     -- ISO 3166-1 alpha-2
    source text,
    date date,
    
    -- 注册信息标记
    inetnum boolean,     -- 是否在 inetnum 中有记录
    rdap boolean,        -- 是否在 RDAP 中有记录
    rpki text,           -- RPKI 验证状态
    
    -- 域名关联
    domain text[],       -- 解析到此前缀的域名列表
    domain_num integer,
    domain_auth text[],  -- 权威 DNS 服务器在此前缀
    domain_auth_num integer
);

-- 索引策略（高频查询字段）
CREATE INDEX idx_ip_bgp_route ON ip_bgp_entity(route);
CREATE INDEX idx_ip_bgp_bgp ON ip_bgp_entity(bgp);
CREATE INDEX idx_ip_bgp_country ON ip_bgp_entity(country);
CREATE INDEX idx_ip_bgp_org_uuid_prefix ON ip_bgp_entity(org_uuid_prefix);
CREATE INDEX idx_ip_bgp_org_uuid_bgp ON ip_bgp_entity(org_uuid_bgp);
```

### 2.3 字段语义映射（`agent/core/schema.py`）

NL2SQL 使用的表结构元数据，附带业务语义提示：

```python
# 来自 agent/core/schema.py:98-126
TABLE_SCHEMA = {
    "ip_bgp_entity": [
        "prefix", "prefix_len", "route", "bgp",
        "name", "descr",
        "admin_prefix", "admin_route", "admin_bgp",
        "org_handle_prefix", "org_name_prefix", "org_name_cn_prefix", "org_uuid_prefix",
        "org_handle_bgp", "org_name_bgp", "org_name_cn_bgp", "org_uuid_bgp",
        "country", "source", "date",
        "inetnum", "rdap", "rpki",
        "domain", "domain_num", "domain_auth", "domain_auth_num"
    ]
}

# 关键：给 LLM 注入字段含义，避免误用
# 来自 agent/core/schema.py:165-173
TABLE_CONTEXT_HINTS = {
    "ip_bgp_entity": "country 使用 ISO 3166-1 alpha-2 代码。"
}
```

## [实战 I/O 示例]

### 示例 1：完整数据流水线（CSV → PostgreSQL → NL2SQL）

**步骤 1：Raw CSV 行（来自 RIR + BGP 融合）**

文件：`data/format/ip_bgp_entity_2024-08-12.csv`

```csv
prefix,prefix_len,route,bgp,org_name_prefix,org_name_bgp,country,domain,domain_num
1.0.1.0/24,24,13335,23911,Cloudflare Inc.,Hurricane Electric LLC,US,"[""one.one.one.one""]",1
8.8.8.0/24,24,15169,15169,Google LLC,Google LLC,US,"[""dns.google"", ""google-public-dns-a.google.com""]",2
```

**步骤 2：导入脚本处理（`scripts/load_all_csv.py`）**

```python
# 核心解析逻辑
def process_row(row: dict) -> dict:
    """
    字段转换示例
    
    输入（CSV dict）：
    {
        'prefix': '1.0.1.0/24',
        'route': '13335',
        'bgp': '23911',
        'domain': '["one.one.one.one"]'
    }
    
    输出（PostgreSQL-ready dict）：
    {
        'prefix': '1.0.1.0/24',     # CIDR 类型
        'route': 13335,              # bigint
        'bgp': 23911,
        'domain': ['one.one.one.one']  # text[]
    }
    """
    processed = {}
    
    # CIDR 字段：直接传递（PostgreSQL 自动转换）
    processed['prefix'] = row['prefix']
    
    # 整数字段
    processed['route'] = int(row['route']) if row['route'] else None
    processed['bgp'] = int(row['bgp']) if row['bgp'] else None
    
    # Python 列表 → PostgreSQL Array
    import ast
    domain_list = ast.literal_eval(row['domain']) if row['domain'] else []
    processed['domain'] = domain_list
    
    return processed
```

**步骤 3：PostgreSQL 存储结果**

```sql
-- 验证导入结果
SELECT 
    prefix,
    route,
    bgp,
    org_name_prefix,
    org_name_bgp,
    domain,
    array_length(domain, 1) AS domain_count
FROM ip_bgp_entity
WHERE prefix IN ('1.0.1.0/24', '8.8.8.0/24');
```

**输出表格**：
```text
prefix       | route | bgp   | org_name_prefix   | org_name_bgp          | domain                                    | domain_count
-------------+-------+-------+-------------------+-----------------------+-------------------------------------------+-------------
1.0.1.0/24   | 13335 | 23911 | Cloudflare Inc.   | Hurricane Electric LLC| {one.one.one.one}                         | 1
8.8.8.0/24   | 15169 | 15169 | Google LLC        | Google LLC            | {dns.google,google-public-dns-a.google.com}| 2
```

**步骤 4：NL2SQL 查询（用户视角）**

用户输入：`查询 1.0.1.0/24 的注册归属和实际传播归属`

系统生成 SQL（来自 `agent/tools/nl2sql_tool.py:600-604`）：
```sql
SELECT 
    prefix,
    route AS registry_asn,
    bgp AS observed_asn,
    org_name_prefix AS registry_org,
    org_name_bgp AS observed_org,
    CASE 
        WHEN route = bgp THEN '一致'
        ELSE '不一致'
    END AS status
FROM ip_bgp_entity
WHERE prefix = '1.0.1.0/24'::cidr
LIMIT 200;
```

### 示例 2：多源冲突检测链路

**场景**：检测前缀归属不一致的案例，用于安全审计

```sql
-- 查询：BGP 劫持嫌疑前缀（注册与观测 ASN 不一致）
WITH conflict_prefixes AS (
    SELECT 
        prefix,
        route AS registry_asn,
        bgp AS observed_asn,
        org_name_prefix,
        org_name_bgp,
        country
    FROM ip_bgp_entity
    WHERE route IS NOT NULL 
      AND bgp IS NOT NULL
      AND route != bgp
)
SELECT 
    cp.*,
    ae_reg.org_country AS registry_country,
    ae_obs.org_country AS observed_country
FROM conflict_prefixes cp
LEFT JOIN as_entity ae_reg ON cp.registry_asn = ae_reg.asn
LEFT JOIN as_entity ae_obs ON cp.observed_asn = ae_obs.asn
WHERE ae_reg.org_country != ae_obs.org_country  -- 跨国传播异常
LIMIT 20;
```

**输出示例**：
```text
prefix          | registry_asn | observed_asn | org_name_prefix      | org_name_bgp         | registry_country | observed_country
----------------+--------------+--------------+----------------------+----------------------+------------------+-----------------
203.0.113.0/24  | 64512        | 65001        | Example Org A        | Example Org B        | US               | CN
198.51.100.0/24 | 64513        | 65002        | ISP Alpha            | ISP Beta             | GB               | RU
```

**分析价值**：
- 安全审计：识别潜在的 BGP 劫持或前缀泄漏
- 合规检查：发现跨境数据传输路径
- 运维分析：定位路由配置错误

### 示例 3：JSON 字段查询（联系人信息）

```sql
-- 查询：提取 AS 的技术联系人邮箱
SELECT 
    asn,
    org_name,
    tech_info->>'name' AS tech_contact_name,
    tech_info->>'email' AS tech_contact_email,
    tech_info->>'phone' AS tech_contact_phone
FROM as_entity
WHERE tech_info IS NOT NULL
  AND tech_info->>'email' LIKE '%@example.com'
LIMIT 10;
```

**输出**：
```text
asn   | org_name          | tech_contact_name | tech_contact_email       | tech_contact_phone
------+-------------------+-------------------+--------------------------+-------------------
4134  | CHINANET          | Zhang San         | tech@chinanet.cn         | +86-10-12345678
15169 | Google LLC        | John Doe          | noc@google.com           | +1-650-2530000
```

## [面试攻防]

### 问题 1：多源数据冲突怎么处理？

**回答要点 1**：**不做写入时强行归一**
```text
错误做法：if bgp != route: row['asn'] = choose_trusted_source(bgp, route)
正确做法：同时保留 route 和 bgp 两个字段，冲突由查询层决策
```

**回答要点 2**：**冲突在查询层或 verifier 子代理判定**
```python
# verifier 子代理判定逻辑（伪代码）
def verify_prefix_ownership(prefix: str) -> dict:
    row = db.query("SELECT route, bgp FROM ip_bgp_entity WHERE prefix = %s", prefix)
    if row['route'] == row['bgp']:
        return {
            "status": "consistent",
            "confidence": 0.95,
            "evidence": "Registry and BGP both point to same ASN"
        }
    else:
        return {
            "status": "conflict",
            "confidence": 0.60,
            "evidence": f"Registry: AS{row['route']}, BGP: AS{row['bgp']}",
            "recommendation": "Requires manual verification"
        }
```

**回答要点 3**：**冲突本身是高价值信号**
- 安全场景：BGP 劫持检测、前缀泄漏告警
- 合规场景：跨境传输路径审计
- 运维场景：路由配置错误定位

### 问题 2：为什么是 16 张核心表，而不是更多或更少？

**回答逻辑**：
- **太少（<10 张）**：无法区分注册信息（inetnum/rdap/route）的差异，丢失细粒度对比能力
- **太多（>30 张）**：引入大量中间表、临时表，NL2SQL 路由复杂度爆炸，检索效率下降
- **16 张平衡点**：
  - 委托层：3 张（asn_entity, ipv4_entity, ipv6_entity）
  - 注册层：6 张（ip_inetnum_entity, ip_rdap_entity, ip_route_entity 及 IPv6 对应）
  - 观测层：2 张（ip_bgp_entity, ipv6_bgp_entity）
  - 聚合层：3 张（as_entity, org_entity, country_entity）
  - 应用层：2 张（website_entity, industry_entity）

### 问题 3：CSV 中的 Python 列表字符串为什么不直接用 JSON Array？

**技术原因**：
1. **历史兼容**：上游数据处理脚本使用 Python，`str(list)` 输出的是 Python 字面量
2. **解析效率**：`ast.literal_eval()` 比 `json.loads()` 对 Python 字面量更宽容（支持单引号）
3. **PostgreSQL 兼容**：导入时统一转为 PostgreSQL ARRAY 类型，无论源是 Python 还是 JSON

**面试追问**：如果重构，会怎么改进？
```text
建议方案：
1. 上游统一输出 JSON 格式（"[1,2,3]" 而非 "[1, 2, 3]"）
2. 导入脚本统一使用 json.loads() 解析
3. 增加格式校验，拒绝非法格式的 CSV 行
```

### 问题 4：如何保证 CSV 导入的幂等性？

**回答要点**（参考 `scripts/load_all_csv.py`）：
```sql
-- 使用 ON CONFLICT 实现 UPSERT
INSERT INTO as_entity (asn, org_name, org_country, ...)
VALUES (4134, 'CHINANET', 'CN', ...)
ON CONFLICT (asn) DO UPDATE SET
    org_name = EXCLUDED.org_name,
    org_country = EXCLUDED.org_country,
    updated_at = NOW();
```

**优势**：
- 重复执行导入脚本不会出现主键冲突错误
- 自动更新最新数据，适配日期快照更新场景
- 保留 `updated_at` 时间戳，可追踪数据新鲜度

---

**技术深度总结**：
- 数据层采用"双轨并行"而非"单源覆盖"，保留冲突信息作为高价值信号
- CSV → PostgreSQL 转换链路需处理 Python 列表、JSON、CIDR 三类特殊编码
- 16 张表设计平衡了细粒度（多源对比）与复杂度（NL2SQL 可用性）
- 幂等性设计确保导入流程可重复执行、可增量更新
