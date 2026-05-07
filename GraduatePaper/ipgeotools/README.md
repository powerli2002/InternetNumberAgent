# IP Geo Tools

`ipgeotools/` 收纳与 IPv6 地理定位实验相关的外部工具、论文原型和主动探测工具快照。

- `Modugeo/`：ModuGeo 论文材料与模型假设参考。
- `cbgtool/`：CBG/NCR/NCR-CBG 主动三角定位参考实现。
- `scampertrace/`：基于 scamper 的 traceroute/rDNS 主动探测工具。

稳定实验系统不直接散落在这些目录中，而是通过 `src/agentic_ipv6_geo/` 的工具封装、provider 和统一配置调用这些能力。
