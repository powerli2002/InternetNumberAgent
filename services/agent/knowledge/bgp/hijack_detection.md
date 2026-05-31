# BGP 劫持检测方法

## 定义

BGP 劫持是指恶意 AS 宣告他人拥有的 IP 前缀，导致流量被错误路由。

## 检测方法

### 1. 注册信息对比

对比 RIR 注册的归属 AS 与 BGP 观测到的宣告 AS，不一致时可能存在劫持。

数据表：`ip_bgp_entity`  
关键字段：`route`（注册 ASN）、`bgp`（观测 ASN）

### 2. RPKI 验证

使用 Resource Public Key Infrastructure 验证前缀宣告的合法性。

查询示例：

```sql
SELECT prefix, rpki
FROM ip_bgp_entity
WHERE rpki = 'Invalid';
```

### 3. 历史路由分析

分析前缀宣告的历史变化，突然的 AS 变更可能是劫持信号。
