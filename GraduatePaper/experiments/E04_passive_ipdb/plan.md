# E04 被动 IPDB 可用性实验

**状态**：规划中  
**优先级**：低（本地缺少数据库文件，短期难以推进）

## 问题

PassiveIpDbGeoTool 当前 Coverage=0%，原因：
1. 本地无 `GeoCN.mmdb`
2. PHP 运行环境未配置
3. `aiwen.txt` 只支持 IPv4

## 选项

- [ ] **选项A**：下载并集成 GeoCN.mmdb（需确认许可证）
- [ ] **选项B**：使用 ip2location-lite IPv6 数据库（开源）
- [ ] **选项C**：作为论文中的"局限性"说明，不强求覆盖率

## 结论预判

如果 GeoCN.mmdb 可用，IPv6 城市级覆盖预计 ≥60%（参考 GeoCN 文档），
可显著提升被动工具的贡献，降低调度成本。
