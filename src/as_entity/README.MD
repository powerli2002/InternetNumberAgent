# 生成 AS 实体

## 所需数据

- `ddos_as.csv`: 判断 AS 是否为 DDOS 服务提供方
- `asn.csv`: RIR delegate ASN 数据
- `org_data.csv`: CAIDA AS-ORG 数据
- `as_rank.csv`: CAIDA AS-RANK 数据
- `astype.txt`: CAIDA AS-TYPE 数据
- `new_org_result.csv`: AS-组织机构映射结果，[详见](org_group.py)
- `{rir}_as_rdap_info.csv`: 五大 RIR AS RDAP 数据
- `as_geo_dict.json`: AS 地理位置数据
- `as_name_dict.json`: AS 名称数据
- `{rir}_as_entity_rdap_info.csv`: 五大 RIR AS 联系人实体 RDAP 数据
- `{rir}_aut-num_whois_info.csv`: 五大 RIR AS WHOIS 数据
- RIPE/RouteVeiws BGP 路由数据

## 注意

`AS18344` 为联通AS，但标记为电信AS