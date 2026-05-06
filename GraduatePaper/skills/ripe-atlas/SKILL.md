---
name: ripe-atlas
description: Use RIPE Atlas REST API for IPv6 active measurements, probe selection, traceroute result parsing, and safe credential handling. Use when implementing or debugging RIPE Atlas integrations, Atlas probes, measurements, traceroute, DNS measurements, credits, or API keys.
---

# RIPE Atlas

## 安全约束

- 不要把 RIPE Atlas API key、Basic Authorization、用户名、密码写入代码、配置、日志、计划或提交。
- 配置文件只保存环境变量名，例如 `RIPE_ATLAS_API_KEY` 或 `RIPE_ATLAS_AUTH_HEADER`。
- 日志中只记录认证方式是否存在，不记录认证值。出现异常时也要脱敏。
- 优先使用 Atlas 文档推荐的 `Authorization: Key YOUR-KEY`。若实验环境只能提供完整 Authorization header，则从 `RIPE_ATLAS_AUTH_HEADER` 读取。

## 文档入口

- API 总入口：[RIPE Atlas APIs](https://atlas.ripe.net/docs/apis/)
- REST API 基础：[Introduction](https://atlas.ripe.net/docs/apis/rest-api-manual/introduction/)
- 认证：[Authentication](https://atlas.ripe.net/docs/apis/rest-api-manual/authentication/)
- Key 管理：[Key Management](https://atlas.ripe.net/docs/apis/rest-api-manual/keys/)
- 创建测量：[Creating Measurements](https://atlas.ripe.net/docs/apis/rest-api-manual/measurements/creating-measurements/)
- 测量定义：[Measurement Definitions](https://atlas.ripe.net/docs/apis/rest-api-manual/measurements/creating-measurements/definitions/)
- 探针选择：[Probe Selection](https://atlas.ripe.net/docs/apis/rest-api-manual/measurements/creating-measurements/probe-selection/)
- 结果格式：[Measurement Result Format](https://atlas.ripe.net/docs/apis/measurement-result-format/)

## REST API 基础

- Base URL 固定为 `https://atlas.ripe.net/api/v2/`，只使用 HTTPS。
- 常用资源：
  - `GET /probes/`：查询 probe 元数据。
  - `POST /measurements/`：创建 ping/traceroute/DNS 等测量。
  - `GET /measurements/{id}/`：查看 measurement 元数据与状态。
  - `GET /measurements/{id}/latest/` 或 `GET /measurements/{id}/results/`：读取结果，具体字段随固件版本变化。
- 创建 measurement 需要具有创建权限的 API key；多数公开读请求可匿名。

## 创建 IPv6 Traceroute

最小 payload 结构：

```json
{
  "definitions": [
    {
      "target": "2001:db8::1",
      "description": "agentic-ipv6-geo trace",
      "type": "traceroute",
      "af": 6,
      "protocol": "ICMP",
      "is_oneoff": true,
      "resolve_on_probe": true
    }
  ],
  "probes": [
    {
      "requested": 3,
      "type": "countries",
      "value": "CN"
    }
  ]
}
```

成功响应通常包含 `{"measurements": [12345678]}`。后续用 measurement id 轮询状态和结果。

## 探针选择

Probe selection 每项包含 `requested`、`type`、`value`：

- `region`：如 `europe`、`asia`、`ripencc`。
- `countries`：ISO 国家码，逗号分隔，如 `CN,JP,SG`。
- `asn`：按 ASN 选择。
- `prefix`：按 IP 前缀选择。
- `probes`：指定 probe id，逗号分隔。
- `msm`：复用历史 measurement 的 probe 集合。

IPv6 实验优先加 `tags_include=["system-ipv6-works"]`，并过滤在线 probe。

## 结果解析

- 结果对象结构会随 probe 固件版本变化，解析器必须容错。
- traceroute 常见字段包括 `prb_id`、`from`、`src`、`dst_addr`、`result`。
- hop 通常在 `result` 数组中，每跳包含 `hop` 和 `result`；RTT 可能在每次尝试的 `rtt` 字段。
- 转为 CBG 约束时使用每个 probe 到目标的最小有效 RTT；若未到达目标，可记录最后可见 hop RTT，但 evidence 必须标明来源。

## 项目实现规范

- RIPE Atlas 只负责采集主动测量证据，不直接输出最终经纬度。
- Atlas 结果必须转成统一数据契约：probe id、probe 经纬度、目标 IP、hop、RTT、measurement id、采集时间、失败原因。
- 缺少 key、credits、在线 probe 或结果超时时，返回 `unavailable`，不要伪造探测结果。
- 真实请求默认关闭；只有配置 `active_probe.allow_live_measurements=true` 且认证存在时才允许创建 measurement。
