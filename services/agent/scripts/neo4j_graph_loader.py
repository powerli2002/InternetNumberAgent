#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import psycopg2
from neo4j import GraphDatabase
from tqdm import tqdm

from agent.core.config import AgentConfig


def _normalize_value(value: Any) -> Any:
    """将不适合 Neo4j 属性的值转为可存储类型。"""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and not value.strip():
            return None
        return value
    if isinstance(value, (list, tuple)):
        if any(isinstance(item, (dict, list, tuple)) for item in value):
            return json.dumps(value, ensure_ascii=False)
        cleaned = [item for item in value if item is not None and str(item).strip() != ""]
        return cleaned or None
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _clean_props(row: Dict[str, Any]) -> Dict[str, Any]:
    """清理空值并规范化属性。"""
    props: Dict[str, Any] = {}
    for key, value in row.items():
        normalized = _normalize_value(value)
        if normalized is None:
            continue
        props[key] = normalized
    return props


def _to_asn_list(values: Any) -> List[int]:
    """将 ASN 列表字段标准化为整数列表。"""
    if not values:
        return []
    if isinstance(values, (list, tuple)):
        raw_list = values
    else:
        raw_list = [values]
    result: List[int] = []
    for item in raw_list:
        if item is None:
            continue
        text = str(item).strip().upper()
        if not text:
            continue
        if text.startswith("AS"):
            text = text[2:]
        try:
            result.append(int(text))
        except ValueError:
            continue
    return result


def _build_dsn(url: str) -> str:
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql://" + url.split("://", 1)[1]
    return url


def _stream_query(conn, query: str, fetch_size: int = 1000) -> Iterable[List[Dict[str, Any]]]:
    """使用服务端游标分批读取，避免一次性加载全部数据。"""
    from psycopg2.extras import RealDictCursor

    cursor = conn.cursor(
        name=f"cursor_{int(time.time() * 1000)}",
        cursor_factory=RealDictCursor,
    )
    cursor.itersize = fetch_size
    cursor.execute(query)
    try:
        while True:
            rows = cursor.fetchmany(fetch_size)
            if not rows:
                break
            batch = [dict(row) for row in rows]
            yield batch
    finally:
        cursor.close()


def _fetch_scalar(conn, query: str, params: Optional[tuple] = None) -> Optional[int]:
    """执行标量查询（如 COUNT）。"""
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        row = cursor.fetchone()
        if not row:
            return None
        return int(row[0]) if row[0] is not None else None


def _make_progress(total: Optional[int], desc: str, enabled: bool) -> Optional[tqdm]:
    """创建进度条，便于观察导入进度。"""
    if not enabled:
        return None
    return tqdm(total=total, desc=desc, unit="rows", dynamic_ncols=True, leave=True)


def _run_write(context, cypher: str, rows: List[Dict[str, Any]]) -> None:
    """兼容 session 与 tx 的统一写入入口。"""
    if hasattr(context, "execute_write"):
        context.execute_write(lambda tx: tx.run(cypher, rows=rows))
        return
    context.run(cypher, rows=rows)


def _run_statement(context, cypher: str) -> None:
    """兼容 session 与 tx 的统一语句执行入口。"""
    if hasattr(context, "execute_write"):
        context.execute_write(lambda tx: tx.run(cypher))
        return
    context.run(cypher)


def _write_nodes(context, label: str, key: str, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    cypher = (
        f"UNWIND $rows AS row "
        f"MERGE (n:{label} {{{key}: row.{key}}}) "
        f"SET n += row"
    )
    _run_write(context, cypher, rows)


def _write_relationships(context, cypher: str, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    _run_write(context, cypher, rows)


def _create_constraints(context, include_website: bool, include_industry: bool) -> None:
    _run_statement(context, "CREATE CONSTRAINT IF NOT EXISTS FOR (a:AS) REQUIRE a.asn IS UNIQUE")
    _run_statement(context, "CREATE CONSTRAINT IF NOT EXISTS FOR (o:Org) REQUIRE o.uuid IS UNIQUE")
    _run_statement(context, "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Country) REQUIRE c.country IS UNIQUE")
    _run_statement(context, "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Prefix) REQUIRE p.cidr IS UNIQUE")
    if include_website:
        _run_statement(context, "CREATE CONSTRAINT IF NOT EXISTS FOR (w:Website) REQUIRE w.url IS UNIQUE")
    if include_industry:
        _run_statement(context, "CREATE CONSTRAINT IF NOT EXISTS FOR (i:Industry) REQUIRE i.name IS UNIQUE")


def _load_countries(pg_conn, session, batch_size: int, show_progress: bool) -> None:
    query = """
        SELECT
            country,
            country_cn,
            country_en,
            region,
            population,
            internet_users AS internet_users,
            internet_users_percentage AS internet_users_percentage,
            gdp_per_capita_cny AS gdp_per_capita_cny,
            asns_number,
            route_asns_number,
            v4prefixes_number AS v4prefixes_number,
            v6prefixes_number AS v6prefixes_number,
            orgs_number
        FROM country_entity;
    """
    total_rows = _fetch_scalar(pg_conn, "SELECT COUNT(*) FROM country_entity;")
    progress = _make_progress(total_rows, "Country", show_progress)
    total = 0
    for batch in _stream_query(pg_conn, query, batch_size):
        rows = [_clean_props(row) for row in batch if row.get("country")]
        _write_nodes(session, "Country", "country", rows)
        total += len(rows)
        if progress:
            progress.update(len(batch))
    if progress:
        progress.close()
    print(f"Country 节点写入完成: {total}")


def _load_orgs(pg_conn, session, batch_size: int, show_progress: bool) -> None:
    query = """
        SELECT
            uuid,
            org_country,
            org_country_cn,
            org_name,
            org_name_cn,
            sibling_as_num,
            v4prefixes_num AS v4prefixes_num,
            v6prefixes_num AS v6prefixes_num
        FROM org_entity;
    """
    total_rows = _fetch_scalar(pg_conn, "SELECT COUNT(*) FROM org_entity;")
    progress = _make_progress(total_rows, "Org", show_progress)
    total = 0
    for batch in _stream_query(pg_conn, query, batch_size):
        rows = [_clean_props(row) for row in batch if row.get("uuid")]
        _write_nodes(session, "Org", "uuid", rows)
        total += len(rows)
        if progress:
            progress.update(len(batch))
    if progress:
        progress.close()
    print(f"Org 节点写入完成: {total}")


def _load_as_nodes(
    pg_conn,
    session,
    batch_size: int,
    show_progress: bool,
    include_relations: bool,
) -> None:
    columns = [
        "asn",
        "source",
        "date",
        "status",
        "descr",
        "descr_cn",
        "registration_date",
        "last_change_date",
        "org_handle",
        "org_id",
        "org_rank",
        "org_country",
        "org_country_cn",
        "uuid",
        "org_name",
        "org_name_cn",
        "as_rank",
        "type",
        "type_cn",
        "as_country",
        "as_country_cn",
        "aut_name",
        "website",
        "is_ddos_provider",
        "is_route",
    ]
    if include_relations:
        columns.extend(
            [
                "v4upstream AS v4_upstream",
                "v4peer AS v4_peer",
                "v4downstream AS v4_downstream",
                "v6upstream AS v6_upstream",
                "v6peer AS v6_peer",
                "v6downstream AS v6_downstream",
            ]
        )
    query = f"SELECT {', '.join(columns)} FROM as_entity;"
    total_rows = _fetch_scalar(pg_conn, "SELECT COUNT(*) FROM as_entity;")
    progress = _make_progress(total_rows, "AS", show_progress)
    total = 0
    rel_rows: List[Dict[str, Any]] = []
    rel_map = {
        "v4_upstream": "V4_UPSTREAM",
        "v4_peer": "V4_PEER",
        "v4_downstream": "V4_DOWNSTREAM",
        "v6_upstream": "V6_UPSTREAM",
        "v6_peer": "V6_PEER",
        "v6_downstream": "V6_DOWNSTREAM",
    } if include_relations else {}
    for batch in _stream_query(pg_conn, query, batch_size):
        rows: List[Dict[str, Any]] = []
        for row in batch:
            asn = row.get("asn")
            if asn is None:
                continue
            props = _clean_props({k: v for k, v in row.items() if k not in rel_map})
            rows.append(props)
            if include_relations:
                for key, rel_type in rel_map.items():
                    targets = _to_asn_list(row.get(key))
                    for target_asn in targets:
                        rel_rows.append({"from_asn": asn, "to_asn": target_asn, "rel": rel_type})
                        if len(rel_rows) >= batch_size:
                            _flush_as_relations(session, rel_rows)
                            rel_rows = []
        _write_nodes(session, "AS", "asn", rows)
        total += len(rows)
        if progress:
            progress.update(len(batch))
    if include_relations and rel_rows:
        _flush_as_relations(session, rel_rows)
    if progress:
        progress.close()
    print(f"AS 节点写入完成: {total}")


def _flush_as_relations(session, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    # 使用动态关系类型无法直接参数化，按类型分组写入
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["rel"], []).append(row)
    for rel_type, rel_rows in grouped.items():
        rel_cypher = (
            "UNWIND $rows AS row "
            "MERGE (a:AS {asn: row.from_asn}) "
            "MERGE (b:AS {asn: row.to_asn}) "
            f"MERGE (a)-[:{rel_type}]->(b)"
        )
        _write_relationships(session, rel_cypher, rel_rows)


def _load_asn_nodes(pg_conn, session, batch_size: int, show_progress: bool) -> None:
    query = """
        SELECT
            asn,
            source,
            country,
            date,
            status,
            org_name,
            uuid
        FROM asn_entity;
    """
    total_rows = _fetch_scalar(pg_conn, "SELECT COUNT(*) FROM asn_entity;")
    progress = _make_progress(total_rows, "ASN", show_progress)
    total = 0
    for batch in _stream_query(pg_conn, query, batch_size):
        rows = [_clean_props(row) for row in batch if row.get("asn") is not None]
        _write_nodes(session, "AS", "asn", rows)
        total += len(rows)
        if progress:
            progress.update(len(batch))
    if progress:
        progress.close()
    print(f"ASN 节点补充完成: {total}")


def _load_as_org_relations(pg_conn, session, batch_size: int, show_progress: bool) -> None:
    query = """
        SELECT asn, uuid, org_name, org_name_cn
        FROM as_entity
        WHERE uuid IS NOT NULL;
    """
    total_rows = _fetch_scalar(pg_conn, "SELECT COUNT(*) FROM as_entity WHERE uuid IS NOT NULL;")
    progress = _make_progress(total_rows, "AS-Org", show_progress)
    total = 0
    rel_rows: List[Dict[str, Any]] = []
    for batch in _stream_query(pg_conn, query, batch_size):
        for row in batch:
            if row.get("asn") is None or not row.get("uuid"):
                continue
            rel_rows.append(_clean_props(row))
            if len(rel_rows) >= batch_size:
                _flush_as_org(session, rel_rows)
                total += len(rel_rows)
                rel_rows = []
        if progress:
            progress.update(len(batch))
    if rel_rows:
        _flush_as_org(session, rel_rows)
        total += len(rel_rows)
    if progress:
        progress.close()
    print(f"AS-Org 关系写入完成: {total}")


def _flush_as_org(session, rows: List[Dict[str, Any]]) -> None:
    cypher = (
        "UNWIND $rows AS row "
        "MERGE (a:AS {asn: row.asn}) "
        "MERGE (o:Org {uuid: row.uuid}) "
        "SET o.org_name = coalesce(o.org_name, row.org_name), "
        "    o.org_name_cn = coalesce(o.org_name_cn, row.org_name_cn) "
        "MERGE (a)-[:BELONGS_TO]->(o)"
    )
    _write_relationships(session, cypher, rows)


def _load_as_country_relations(pg_conn, session, batch_size: int, show_progress: bool) -> None:
    query = """
        SELECT asn, as_country AS country, 'as_country' AS source
        FROM as_entity
        WHERE as_country IS NOT NULL
        UNION ALL
        SELECT asn, org_country AS country, 'org_country' AS source
        FROM as_entity
        WHERE org_country IS NOT NULL;
    """
    total_rows = _fetch_scalar(
        pg_conn,
        "SELECT (SELECT COUNT(*) FROM as_entity WHERE as_country IS NOT NULL) + "
        "(SELECT COUNT(*) FROM as_entity WHERE org_country IS NOT NULL);",
    )
    progress = _make_progress(total_rows, "AS-Country", show_progress)
    total = 0
    rel_rows: List[Dict[str, Any]] = []
    for batch in _stream_query(pg_conn, query, batch_size):
        for row in batch:
            if row.get("asn") is None or not row.get("country"):
                continue
            rel_rows.append(_clean_props(row))
            if len(rel_rows) >= batch_size:
                _flush_as_country(session, rel_rows)
                total += len(rel_rows)
                rel_rows = []
        if progress:
            progress.update(len(batch))
    if rel_rows:
        _flush_as_country(session, rel_rows)
        total += len(rel_rows)
    if progress:
        progress.close()
    print(f"AS-Country 关系写入完成: {total}")


def _flush_as_country(session, rows: List[Dict[str, Any]]) -> None:
    cypher = (
        "UNWIND $rows AS row "
        "MERGE (a:AS {asn: row.asn}) "
        "MERGE (c:Country {country: row.country}) "
        "MERGE (a)-[r:LOCATED_IN {source: row.source}]->(c)"
    )
    _write_relationships(session, cypher, rows)


def _load_org_country_relations(pg_conn, session, batch_size: int, show_progress: bool) -> None:
    query = """
        SELECT uuid, org_country AS country
        FROM org_entity
        WHERE org_country IS NOT NULL;
    """
    total_rows = _fetch_scalar(pg_conn, "SELECT COUNT(*) FROM org_entity WHERE org_country IS NOT NULL;")
    progress = _make_progress(total_rows, "Org-Country", show_progress)
    total = 0
    rel_rows: List[Dict[str, Any]] = []
    for batch in _stream_query(pg_conn, query, batch_size):
        for row in batch:
            if not row.get("uuid") or not row.get("country"):
                continue
            rel_rows.append(_clean_props(row))
            if len(rel_rows) >= batch_size:
                _flush_org_country(session, rel_rows)
                total += len(rel_rows)
                rel_rows = []
        if progress:
            progress.update(len(batch))
    if rel_rows:
        _flush_org_country(session, rel_rows)
        total += len(rel_rows)
    if progress:
        progress.close()
    print(f"Org-Country 关系写入完成: {total}")


def _flush_org_country(session, rows: List[Dict[str, Any]]) -> None:
    cypher = (
        "UNWIND $rows AS row "
        "MERGE (o:Org {uuid: row.uuid}) "
        "MERGE (c:Country {country: row.country}) "
        "MERGE (o)-[:LOCATED_IN]->(c)"
    )
    _write_relationships(session, cypher, rows)


def _load_prefix_from_bgp(pg_conn, session, batch_size: int, version: int, show_progress: bool) -> None:
    table = "ip_bgp_entity" if version == 4 else "ipv6_bgp_entity"
    query = f"""
        SELECT
            prefix AS cidr,
            prefix_len,
            name,
            descr,
            route,
            bgp,
            country,
            source,
            date,
            inetnum AS bgp_inetnum,
            rdap AS bgp_rdap,
            rpki AS bgp_rpki,
            org_uuid_prefix,
            org_uuid_bgp,
            org_name_prefix,
            org_name_bgp,
            org_name_cn_prefix,
            org_name_cn_bgp
        FROM {table};
    """
    total_rows = _fetch_scalar(pg_conn, f"SELECT COUNT(*) FROM {table};")
    progress = _make_progress(total_rows, f"Prefix BGP v{version}", show_progress)
    total_nodes = 0
    rel_as_bgp: List[Dict[str, Any]] = []
    rel_as_route: List[Dict[str, Any]] = []
    rel_org_reg: List[Dict[str, Any]] = []
    rel_org_obs: List[Dict[str, Any]] = []
    rel_country: List[Dict[str, Any]] = []

    for batch in _stream_query(pg_conn, query, batch_size):
        nodes: List[Dict[str, Any]] = []
        for row in batch:
            cidr = row.get("cidr")
            if not cidr:
                continue
            props = _clean_props(row)
            props["version"] = version
            nodes.append(props)

            bgp_asn = row.get("bgp")
            if bgp_asn is not None:
                rel_as_bgp.append({"cidr": cidr, "asn": int(bgp_asn), "source": table})
            for route_asn in _to_asn_list(row.get("route")):
                rel_as_route.append({"cidr": cidr, "asn": route_asn, "source": table})

            if row.get("org_uuid_prefix"):
                rel_org_reg.append({"cidr": cidr, "uuid": row["org_uuid_prefix"], "source": "prefix"})
            if row.get("org_uuid_bgp"):
                rel_org_obs.append({"cidr": cidr, "uuid": row["org_uuid_bgp"], "source": "bgp"})

            if row.get("country"):
                rel_country.append({"cidr": cidr, "country": row["country"], "source": table})

            if len(nodes) >= batch_size:
                _write_nodes(session, "Prefix", "cidr", nodes)
                total_nodes += len(nodes)
                nodes = []

            if len(rel_as_bgp) >= batch_size:
                _flush_prefix_as(session, rel_as_bgp, "BGP_ORIGIN")
                rel_as_bgp = []
            if len(rel_as_route) >= batch_size:
                _flush_prefix_as(session, rel_as_route, "REG_ORIGIN")
                rel_as_route = []
            if len(rel_org_reg) >= batch_size:
                _flush_prefix_org(session, rel_org_reg, "REGISTERED_TO")
                rel_org_reg = []
            if len(rel_org_obs) >= batch_size:
                _flush_prefix_org(session, rel_org_obs, "OBSERVED_ORG")
                rel_org_obs = []
            if len(rel_country) >= batch_size:
                _flush_prefix_country(session, rel_country)
                rel_country = []
        if progress:
            progress.update(len(batch))

        if nodes:
            _write_nodes(session, "Prefix", "cidr", nodes)
            total_nodes += len(nodes)
        if rel_as_bgp:
            _flush_prefix_as(session, rel_as_bgp, "BGP_ORIGIN")
        if rel_as_route:
            _flush_prefix_as(session, rel_as_route, "REG_ORIGIN")
        if rel_org_reg:
            _flush_prefix_org(session, rel_org_reg, "REGISTERED_TO")
        if rel_org_obs:
            _flush_prefix_org(session, rel_org_obs, "OBSERVED_ORG")
        if rel_country:
            _flush_prefix_country(session, rel_country)

    if progress:
        progress.close()
    print(f"Prefix(BGP v{version}) 节点写入完成: {total_nodes}")


def _load_prefix_from_delegate(pg_conn, session, batch_size: int, version: int, show_progress: bool) -> None:
    table = "ipv4_entity" if version == 4 else "ipv6_entity"
    query = f"""
        SELECT
            prefix AS cidr,
            prefix_len,
            source AS delegate_source,
            country AS delegate_country,
            org_id AS delegate_org_id,
            date AS delegate_date,
            status AS delegate_status,
            org_name AS delegate_org_name,
            sibling_as AS delegate_sibling_as,
            uuid AS delegate_org_uuid
        FROM {table};
    """
    total_rows = _fetch_scalar(pg_conn, f"SELECT COUNT(*) FROM {table};")
    progress = _make_progress(total_rows, f"Prefix 委托 v{version}", show_progress)
    total_nodes = 0
    rel_org: List[Dict[str, Any]] = []
    rel_country: List[Dict[str, Any]] = []
    for batch in _stream_query(pg_conn, query, batch_size):
        nodes: List[Dict[str, Any]] = []
        for row in batch:
            cidr = row.get("cidr")
            if not cidr:
                continue
            props = _clean_props(row)
            props["version"] = version
            nodes.append(props)
            if row.get("delegate_org_uuid"):
                rel_org.append({"cidr": cidr, "uuid": row["delegate_org_uuid"], "source": "delegate"})
            if row.get("delegate_country"):
                rel_country.append({"cidr": cidr, "country": row["delegate_country"], "source": table})

            if len(nodes) >= batch_size:
                _write_nodes(session, "Prefix", "cidr", nodes)
                total_nodes += len(nodes)
                nodes = []
            if len(rel_org) >= batch_size:
                _flush_prefix_org(session, rel_org, "REGISTERED_TO")
                rel_org = []
            if len(rel_country) >= batch_size:
                _flush_prefix_country(session, rel_country)
                rel_country = []
        if progress:
            progress.update(len(batch))
        if nodes:
            _write_nodes(session, "Prefix", "cidr", nodes)
            total_nodes += len(nodes)
        if rel_org:
            _flush_prefix_org(session, rel_org, "REGISTERED_TO")
        if rel_country:
            _flush_prefix_country(session, rel_country)
    if progress:
        progress.close()
    print(f"Prefix(委托 v{version}) 节点写入完成: {total_nodes}")


def _update_prefix_registry(
    pg_conn,
    session,
    batch_size: int,
    table: str,
    prefix_label: str,
    total_rows: Optional[int],
    show_progress: bool,
) -> None:
    total = 0
    progress = _make_progress(total_rows, f"Registry {prefix_label}", show_progress)
    for batch in _stream_query(pg_conn, table, batch_size):
        rows = [_clean_props(row) for row in batch if row.get("cidr")]
        cypher = (
            "UNWIND $rows AS row "
            "MERGE (p:Prefix {cidr: row.cidr}) "
            f"SET p += row"
        )
        _write_relationships(session, cypher, rows)
        total += len(rows)
        if progress:
            progress.update(len(batch))
    if progress:
        progress.close()
    print(f"Prefix 注册信息更新完成: {prefix_label} {total}")


def _flush_prefix_as(session, rows: List[Dict[str, Any]], rel_type: str) -> None:
    cypher = (
        "UNWIND $rows AS row "
        "MERGE (p:Prefix {cidr: row.cidr}) "
        "MERGE (a:AS {asn: row.asn}) "
        f"MERGE (p)-[r:{rel_type}]->(a) "
        "SET r.source = row.source"
    )
    _write_relationships(session, cypher, rows)


def _flush_prefix_org(session, rows: List[Dict[str, Any]], rel_type: str) -> None:
    cypher = (
        "UNWIND $rows AS row "
        "MERGE (p:Prefix {cidr: row.cidr}) "
        "MERGE (o:Org {uuid: row.uuid}) "
        f"MERGE (p)-[r:{rel_type}]->(o) "
        "SET r.source = row.source"
    )
    _write_relationships(session, cypher, rows)


def _flush_prefix_country(session, rows: List[Dict[str, Any]]) -> None:
    cypher = (
        "UNWIND $rows AS row "
        "MERGE (p:Prefix {cidr: row.cidr}) "
        "MERGE (c:Country {country: row.country}) "
        "MERGE (p)-[r:IN_COUNTRY {source: row.source}]->(c)"
    )
    _write_relationships(session, cypher, rows)


def _load_registry_info(pg_conn, session, batch_size: int, show_progress: bool) -> None:
    inetnum_v4 = """
        SELECT
            cidr AS cidr,
            netname AS inetnum_netname,
            descr AS inetnum_descr,
            country AS inetnum_country,
            source AS inetnum_source,
            admin_c AS inetnum_admin_c,
            tech_c AS inetnum_tech_c,
            abuse_c AS inetnum_abuse_c,
            org AS inetnum_org,
            org_name AS inetnum_org_name,
            org_name_cn AS inetnum_org_name_cn,
            org_uuid AS inetnum_org_uuid
        FROM ip_inetnum_entity;
    """
    rdap_v4 = """
        SELECT
            cidr AS cidr,
            netname AS rdap_netname,
            descr AS rdap_descr,
            country AS rdap_country,
            source AS rdap_source,
            admin_c AS rdap_admin_c,
            tech_c AS rdap_tech_c,
            abuse_c AS rdap_abuse_c,
            org AS rdap_org,
            org_name AS rdap_org_name,
            org_name_cn AS rdap_org_name_cn,
            org_uuid AS rdap_org_uuid
        FROM ip_rdap_entity;
    """
    route_v4 = """
        SELECT
            cidr AS cidr,
            descr AS route_descr,
            origin AS route_origin,
            mnt_by AS route_mnt_by,
            last_modified AS route_last_modified,
            source AS route_source
        FROM ip_route_entity;
    """
    inetnum_v6 = inetnum_v4.replace("ip_inetnum_entity", "ipv6_inetnum_entity")
    rdap_v6 = rdap_v4.replace("ip_rdap_entity", "ipv6_rdap_entity")
    route_v6 = route_v4.replace("ip_route_entity", "ipv6_route_entity")

    _update_prefix_registry(
        pg_conn,
        session,
        batch_size,
        inetnum_v4,
        "inetnum_v4",
        _fetch_scalar(pg_conn, "SELECT COUNT(*) FROM ip_inetnum_entity;"),
        show_progress,
    )
    _update_prefix_registry(
        pg_conn,
        session,
        batch_size,
        rdap_v4,
        "rdap_v4",
        _fetch_scalar(pg_conn, "SELECT COUNT(*) FROM ip_rdap_entity;"),
        show_progress,
    )
    _update_prefix_registry(
        pg_conn,
        session,
        batch_size,
        route_v4,
        "route_v4",
        _fetch_scalar(pg_conn, "SELECT COUNT(*) FROM ip_route_entity;"),
        show_progress,
    )
    _update_prefix_registry(
        pg_conn,
        session,
        batch_size,
        inetnum_v6,
        "inetnum_v6",
        _fetch_scalar(pg_conn, "SELECT COUNT(*) FROM ipv6_inetnum_entity;"),
        show_progress,
    )
    _update_prefix_registry(
        pg_conn,
        session,
        batch_size,
        rdap_v6,
        "rdap_v6",
        _fetch_scalar(pg_conn, "SELECT COUNT(*) FROM ipv6_rdap_entity;"),
        show_progress,
    )
    _update_prefix_registry(
        pg_conn,
        session,
        batch_size,
        route_v6,
        "route_v6",
        _fetch_scalar(pg_conn, "SELECT COUNT(*) FROM ipv6_route_entity;"),
        show_progress,
    )


def _load_website_nodes(pg_conn, session, batch_size: int, show_progress: bool) -> None:
    query = """
        SELECT url, title, key, description, industry, ip_prefix, auth_ip_prefix
        FROM website_entity;
    """
    total_rows = _fetch_scalar(pg_conn, "SELECT COUNT(*) FROM website_entity;")
    progress = _make_progress(total_rows, "Website", show_progress)
    total = 0
    for batch in _stream_query(pg_conn, query, batch_size):
        rows = [_clean_props(row) for row in batch if row.get("url")]
        _write_nodes(session, "Website", "url", rows)
        total += len(rows)
        if progress:
            progress.update(len(batch))
    if progress:
        progress.close()
    print(f"Website 节点写入完成: {total}")


def _load_website_prefix_relations(pg_conn, session, batch_size: int, show_progress: bool) -> None:
    query = """
        SELECT url, ip_prefix, auth_ip_prefix
        FROM website_entity;
    """
    total_rows = _fetch_scalar(pg_conn, "SELECT COUNT(*) FROM website_entity;")
    progress = _make_progress(total_rows, "Website-Prefix", show_progress)
    total = 0
    rel_rows: List[Dict[str, Any]] = []
    rel_rows_auth: List[Dict[str, Any]] = []
    for batch in _stream_query(pg_conn, query, batch_size):
        for row in batch:
            url = row.get("url")
            if not url:
                continue
            for prefix in row.get("ip_prefix") or []:
                if prefix:
                    rel_rows.append({"url": url, "cidr": prefix})
            for prefix in row.get("auth_ip_prefix") or []:
                if prefix:
                    rel_rows_auth.append({"url": url, "cidr": prefix})
            if len(rel_rows) >= batch_size:
                _flush_website_prefix(session, rel_rows, "RESOLVES_TO")
                total += len(rel_rows)
                rel_rows = []
            if len(rel_rows_auth) >= batch_size:
                _flush_website_prefix(session, rel_rows_auth, "AUTH_RESOLVES_TO")
                total += len(rel_rows_auth)
                rel_rows_auth = []
        if progress:
            progress.update(len(batch))
    if rel_rows:
        _flush_website_prefix(session, rel_rows, "RESOLVES_TO")
        total += len(rel_rows)
    if rel_rows_auth:
        _flush_website_prefix(session, rel_rows_auth, "AUTH_RESOLVES_TO")
        total += len(rel_rows_auth)
    if progress:
        progress.close()
    print(f"Website-Prefix 关系写入完成: {total}")


def _flush_website_prefix(session, rows: List[Dict[str, Any]], rel_type: str) -> None:
    cypher = (
        "UNWIND $rows AS row "
        "MERGE (w:Website {url: row.url}) "
        "MERGE (p:Prefix {cidr: row.cidr}) "
        f"MERGE (w)-[:{rel_type}]->(p)"
    )
    _write_relationships(session, cypher, rows)


def _load_industry_graph(
    pg_conn,
    session,
    batch_size: int,
    org_name_map: Dict[str, str],
    show_progress: bool,
) -> None:
    query = """
        SELECT
            url,
            parent,
            title,
            industry,
            description,
            key,
            ip_prefix,
            ip_asn,
            ip_org,
            auth_ip_prefix,
            auth_ip_asn,
            auth_ip_org
        FROM industry_entity;
    """
    total_rows = _fetch_scalar(pg_conn, "SELECT COUNT(*) FROM industry_entity;")
    progress = _make_progress(total_rows, "Industry", show_progress)
    total_websites = 0
    rel_rows_industry: List[Dict[str, Any]] = []
    rel_rows_parent: List[Dict[str, Any]] = []
    rel_rows_as: List[Dict[str, Any]] = []
    rel_rows_org: List[Dict[str, Any]] = []
    rel_rows_prefix: List[Dict[str, Any]] = []
    rel_rows_prefix_auth: List[Dict[str, Any]] = []

    for batch in _stream_query(pg_conn, query, batch_size):
        website_rows: List[Dict[str, Any]] = []
        industry_rows: List[Dict[str, Any]] = []
        for row in batch:
            url = row.get("url")
            industry = row.get("industry")
            parent = row.get("parent")
            if url:
                website_rows.append(_clean_props({"url": url, "title": row.get("title"), "description": row.get("description"), "industry": industry}))
                total_websites += 1
            if industry:
                industry_rows.append(_clean_props({"name": industry}))
            if parent:
                industry_rows.append(_clean_props({"name": parent}))
                if industry:
                    rel_rows_parent.append({"parent": parent, "child": industry})

            if url and industry:
                rel_rows_industry.append({"url": url, "industry": industry})

            for prefix in row.get("ip_prefix") or []:
                if url and prefix:
                    rel_rows_prefix.append({"url": url, "cidr": prefix})
            for prefix in row.get("auth_ip_prefix") or []:
                if url and prefix:
                    rel_rows_prefix_auth.append({"url": url, "cidr": prefix})

            for asn in row.get("ip_asn") or []:
                if url and asn is not None:
                    rel_rows_as.append({"url": url, "asn": int(asn), "source": "ip_asn"})
            for asn in row.get("auth_ip_asn") or []:
                if url and asn is not None:
                    rel_rows_as.append({"url": url, "asn": int(asn), "source": "auth_ip_asn"})

            for org_name in row.get("ip_org") or []:
                if url and org_name:
                    uuid = org_name_map.get(org_name)
                    if uuid:
                        rel_rows_org.append({"url": url, "uuid": uuid, "source": "ip_org"})
            for org_name in row.get("auth_ip_org") or []:
                if url and org_name:
                    uuid = org_name_map.get(org_name)
                    if uuid:
                        rel_rows_org.append({"url": url, "uuid": uuid, "source": "auth_ip_org"})

            if len(website_rows) >= batch_size:
                _write_nodes(session, "Website", "url", website_rows)
                website_rows = []
            if len(industry_rows) >= batch_size:
                _write_nodes(session, "Industry", "name", industry_rows)
                industry_rows = []

            if len(rel_rows_industry) >= batch_size:
                _flush_website_industry(session, rel_rows_industry)
                rel_rows_industry = []
            if len(rel_rows_parent) >= batch_size:
                _flush_industry_parent(session, rel_rows_parent)
                rel_rows_parent = []
            if len(rel_rows_as) >= batch_size:
                _flush_website_as(session, rel_rows_as)
                rel_rows_as = []
            if len(rel_rows_org) >= batch_size:
                _flush_website_org(session, rel_rows_org)
                rel_rows_org = []
            if len(rel_rows_prefix) >= batch_size:
                _flush_website_prefix(session, rel_rows_prefix, "RESOLVES_TO")
                rel_rows_prefix = []
            if len(rel_rows_prefix_auth) >= batch_size:
                _flush_website_prefix(session, rel_rows_prefix_auth, "AUTH_RESOLVES_TO")
                rel_rows_prefix_auth = []
        if progress:
            progress.update(len(batch))

        if website_rows:
            _write_nodes(session, "Website", "url", website_rows)
        if industry_rows:
            _write_nodes(session, "Industry", "name", industry_rows)

    if rel_rows_industry:
        _flush_website_industry(session, rel_rows_industry)
    if rel_rows_parent:
        _flush_industry_parent(session, rel_rows_parent)
    if rel_rows_as:
        _flush_website_as(session, rel_rows_as)
    if rel_rows_org:
        _flush_website_org(session, rel_rows_org)
    if rel_rows_prefix:
        _flush_website_prefix(session, rel_rows_prefix, "RESOLVES_TO")
    if rel_rows_prefix_auth:
        _flush_website_prefix(session, rel_rows_prefix_auth, "AUTH_RESOLVES_TO")

    if progress:
        progress.close()
    print(f"Industry 数据写入完成，Website 节点补充: {total_websites}")


def _flush_website_industry(session, rows: List[Dict[str, Any]]) -> None:
    cypher = (
        "UNWIND $rows AS row "
        "MERGE (w:Website {url: row.url}) "
        "MERGE (i:Industry {name: row.industry}) "
        "MERGE (w)-[:IN_INDUSTRY]->(i)"
    )
    _write_relationships(session, cypher, rows)


def _flush_industry_parent(session, rows: List[Dict[str, Any]]) -> None:
    cypher = (
        "UNWIND $rows AS row "
        "MERGE (p:Industry {name: row.parent}) "
        "MERGE (c:Industry {name: row.child}) "
        "MERGE (p)-[:PARENT_OF]->(c)"
    )
    _write_relationships(session, cypher, rows)


def _flush_website_as(session, rows: List[Dict[str, Any]]) -> None:
    cypher = (
        "UNWIND $rows AS row "
        "MERGE (w:Website {url: row.url}) "
        "MERGE (a:AS {asn: row.asn}) "
        "MERGE (w)-[r:HOSTED_BY_AS]->(a) "
        "SET r.source = row.source"
    )
    _write_relationships(session, cypher, rows)


def _flush_website_org(session, rows: List[Dict[str, Any]]) -> None:
    cypher = (
        "UNWIND $rows AS row "
        "MERGE (w:Website {url: row.url}) "
        "MERGE (o:Org {uuid: row.uuid}) "
        "MERGE (w)-[r:HOSTED_BY_ORG]->(o) "
        "SET r.source = row.source"
    )
    _write_relationships(session, cypher, rows)


def _build_org_name_map(pg_conn) -> Dict[str, str]:
    query = "SELECT uuid, org_name, org_name_cn FROM org_entity;"
    mapping: Dict[str, str] = {}
    with pg_conn.cursor() as cursor:
        cursor.execute(query)
        for uuid, org_name, org_name_cn in cursor.fetchall():
            if org_name and org_name not in mapping:
                mapping[org_name] = uuid
            if org_name_cn and org_name_cn not in mapping:
                mapping[org_name_cn] = uuid
    return mapping


def _run_import_pipeline(pg_conn, context, args, show_progress: bool) -> None:
    """执行图谱导入主流程。"""
    _create_constraints(context, args.include_website, args.include_industry)

    _load_countries(pg_conn, context, args.batch_size, show_progress)
    _load_orgs(pg_conn, context, args.batch_size, show_progress)
    _load_as_nodes(
        pg_conn,
        context,
        args.batch_size,
        show_progress,
        include_relations=not args.skip_as_relations,
    )
    _load_asn_nodes(pg_conn, context, args.batch_size, show_progress)

    _load_as_org_relations(pg_conn, context, args.batch_size, show_progress)
    _load_org_country_relations(pg_conn, context, args.batch_size, show_progress)
    _load_as_country_relations(pg_conn, context, args.batch_size, show_progress)

    _load_prefix_from_bgp(pg_conn, context, args.batch_size, version=4, show_progress=show_progress)
    _load_prefix_from_bgp(pg_conn, context, args.batch_size, version=6, show_progress=show_progress)
    _load_prefix_from_delegate(pg_conn, context, args.batch_size, version=4, show_progress=show_progress)
    _load_prefix_from_delegate(pg_conn, context, args.batch_size, version=6, show_progress=show_progress)
    _load_registry_info(pg_conn, context, args.batch_size, show_progress)

    if args.include_website:
        _load_website_nodes(pg_conn, context, args.batch_size, show_progress)
        _load_website_prefix_relations(pg_conn, context, args.batch_size, show_progress)
    if args.include_industry:
        org_name_map = _build_org_name_map(pg_conn)
        _load_industry_graph(pg_conn, context, args.batch_size, org_name_map, show_progress)


@dataclass
class Neo4jImportOptions:
    """Neo4j 图导入参数。"""

    batch_size: int = 1000
    include_website: bool = False
    include_industry: bool = False
    no_progress: bool = False
    skip_as_relations: bool = False
    single_transaction: bool = False


def run_import_pipeline(pg_conn, context, options: Neo4jImportOptions) -> None:
    """在给定 Neo4j context（session/tx）内执行图导入主流程。"""
    show_progress = not options.no_progress
    _run_import_pipeline(pg_conn, context, options, show_progress)


def run_import(
    pg_conn,
    *,
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    options: Neo4jImportOptions,
) -> None:
    """执行一次 Neo4j 导入（支持单事务模式）。"""
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    try:
        with driver.session() as session:
            if options.single_transaction:
                tx = session.begin_transaction()
                try:
                    run_import_pipeline(pg_conn, tx, options)
                    tx.commit()
                    print("Neo4j 单事务导入完成，已提交。")
                except Exception:
                    tx.rollback()
                    print("Neo4j 单事务导入失败，已回滚。")
                    raise
            else:
                run_import_pipeline(pg_conn, session, options)
    finally:
        driver.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Neo4j 图谱导入（Postgres 数据源）")
    parser.add_argument("--postgres-url", default=None, help="Postgres 连接串")
    parser.add_argument("--neo4j-uri", default=None, help="Neo4j Bolt URI")
    parser.add_argument("--neo4j-user", default=None, help="Neo4j 用户名")
    parser.add_argument("--neo4j-password", default=None, help="Neo4j 密码")
    parser.add_argument("--batch-size", type=int, default=1000, help="每批写入大小")
    parser.add_argument("--include-website", action="store_true", help="导入 website_entity（数量较大）")
    parser.add_argument("--include-industry", action="store_true", help="导入 industry_entity 并构建行业关系")
    parser.add_argument("--no-progress", action="store_true", help="禁用进度条输出")
    parser.add_argument("--skip-as-relations", action="store_true", help="跳过 AS 上下游/对等关系导入")
    parser.add_argument(
        "--single-transaction",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="是否以单个 Neo4j 事务执行整批导入（失败自动整批回滚）",
    )
    args = parser.parse_args()

    cfg = AgentConfig.load()
    postgres_url = args.postgres_url or cfg.postgres_url
    if not postgres_url:
        raise RuntimeError("未配置 Postgres 连接串")
    postgres_url = _build_dsn(postgres_url)

    neo4j_uri = args.neo4j_uri or cfg.neo4j_uri
    neo4j_user = args.neo4j_user or cfg.neo4j_user
    neo4j_password = args.neo4j_password or cfg.neo4j_password

    pg_conn = psycopg2.connect(postgres_url)
    try:
        run_import(
            pg_conn,
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_password=neo4j_password,
            options=Neo4jImportOptions(
                batch_size=max(1, int(args.batch_size)),
                include_website=bool(args.include_website),
                include_industry=bool(args.include_industry),
                no_progress=bool(args.no_progress),
                skip_as_relations=bool(args.skip_as_relations),
                single_transaction=bool(args.single_transaction),
            ),
        )
    finally:
        pg_conn.close()


if __name__ == "__main__":
    main()
