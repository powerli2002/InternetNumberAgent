# E02 rDNS 覆盖率提升实验

**状态**：规划中  
**优先级**：中（覆盖率太低可能直接放弃此路线，转为论文中的负面结果）  
**前置**：E01 已完成

## 问题

TrustGeo 数据集中 IPv6 PTR 命中率仅 1%（212/21088），rDNS 工具完全无法在评测中产生贡献。

## 待探索方向

- [ ] 换用权威 DNS resolver（如 8.8.8.8 / 114.114.114.114）重新采集
- [ ] 对已有 212 条 PTR 手工检验地理词命中率（评估词典质量）
- [ ] 统计命中省市分布，看是否有区域集中度
- [ ] 评估结论：若命中率无法提升到 5% 以上，作为"负面结果"写入论文（说明中国 IPv6 PTR 部署稀疏）

## 运行命令

```bash
UV_CACHE_DIR=.uv-cache uv run ipv6geo-collect-rdns \
  --input data/trustgeo_processed/targets.csv \
  --ip-version 6 --zdns-bin outputs/rdns_test/zdns \
  --resolver 8.8.8.8 \
  --output-jsonl experiments/E02_rdns_enhancement/zdns_google.jsonl \
  --output-rdns-csv experiments/E02_rdns_enhancement/rdns_google.csv \
  --summary experiments/E02_rdns_enhancement/summary_google.json
```
