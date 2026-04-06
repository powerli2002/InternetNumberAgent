"""根据 summary.md 提取的核心表字段，用于 NL2SQL 提示与校验。"""
# https://developers.llamaindex.ai/python/examples/index_structs/struct_indices/sqlindexdemo/
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Tuple

TABLE_SCHEMA = {
    "as_entity": [
        "asn",
        "source",
        "opq_id",
        "date",
        "status",
        "descr",
        "descr_cn",
        "aut_name",
        "website",
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
        "sibling_as",
        "administrative",
        "technical",
        "abuse",
        "admin_info",
        "tech_info",
        "abuse_info",
        "as_rank",
        "type",
        "type_cn",
        "is_ddos_provider",
        "is_route",
        "as_longitude",
        "as_latitude",
        "geo_country_list",
        "geo_city_list",
        "geo_latitude_longitude",
        "geo_country_list_num",
        "geo_city_list_num",
        "geo_latitude_longitude_num",
        "as_country",
        "as_country_cn",
        "import",
        "export",
        "import_as",
        "export_as",
        "v4upstream",
        "v4peer",
        "v4downstream",
        "v4propagation",
        "v4prefixes",
        "v6upstream",
        "v6peer",
        "v6downstream",
        "v6propagation",
        "v6prefixes",
    ],
    "asn_entity": ["asn", "source", "country", "opq_id", "date", "status", "org_name", "uuid"],
    "country_entity": [
        "country_en",
        "country",
        "country_cn",
        "region",
        "population",
        "internet_users",
        "internet_users_percentage",
        "gdp_per_capita_cny",
        "asns",
        "asns_number",
        "route_asns",
        "route_asns_number",
        "v4prefixes",
        "v4prefixes_number",
        "v6prefixes",
        "v6prefixes_number",
        "orgs",
        "orgs_number",
    ],
    "industry_entity": [
        "url",
        "parent",
        "title",
        "industry",
        "description",
        "key",
        "ip",
        "ip_prefix",
        "ip_asn",
        "ip_org",
        "auth_ip",
        "auth_ip_prefix",
        "auth_ip_asn",
        "auth_ip_org",
    ],
    "ip_bgp_entity": [
        "prefix",
        "prefix_len",
        "route",
        "bgp",
        "name",
        "descr",
        "admin_prefix",
        "admin_route",
        "admin_bgp",
        "org_handle_prefix",
        "org_name_prefix",
        "org_name_cn_prefix",
        "org_uuid_prefix",
        "org_handle_bgp",
        "org_name_bgp",
        "org_name_cn_bgp",
        "org_uuid_bgp",
        "country",
        "source",
        "date",
        "inetnum",
        "rdap",
        "rpki",
        "domain",
        "domain_num",
        "domain_auth",
        "domain_auth_num",
    ],
    "ip_inetnum_entity": ["cidr", "netname", "descr", "country", "source", "admin_c", "tech_c", "abuse_c", "org", "org_name", "org_name_cn", "org_uuid"],
    "ip_rdap_entity": ["cidr", "netname", "descr", "country", "source", "admin_c", "tech_c", "abuse_c", "org", "org_name", "org_name_cn", "org_uuid"],
    "ip_route_entity": ["cidr", "descr", "origin", "mnt_by", "last_modified", "source"],
    "ipv4_entity": ["prefix", "prefix_len", "source", "country", "org_id", "date", "status", "org_name", "sibling_as", "uuid"],
    "ipv6_bgp_entity": [
        "prefix",
        "prefix_len",
        "name",
        "descr",
        "route",
        "bgp",
        "admin_prefix",
        "admin_route",
        "admin_bgp",
        "org_handle_prefix",
        "org_name_prefix",
        "org_name_cn_prefix",
        "org_uuid_prefix",
        "org_handle_bgp",
        "org_name_bgp",
        "org_name_cn_bgp",
        "org_uuid_bgp",
        "country",
        "source",
        "date",
        "inetnum",
        "rdap",
        "rpki",
    ],
    "ipv6_entity": ["prefix", "prefix_len", "source", "country", "org_id", "date", "status", "org_name", "sibling_as", "uuid"],
    "ipv6_inetnum_entity": ["cidr", "netname", "descr", "country", "source", "admin_c", "tech_c", "abuse_c", "org", "org_name", "org_name_cn", "org_uuid"],
    "ipv6_rdap_entity": ["cidr", "netname", "descr", "country", "source", "admin_c", "tech_c", "abuse_c", "org", "org_name", "org_name_cn", "org_uuid"],
    "ipv6_route_entity": ["cidr", "descr", "origin", "mnt_by", "last_modified", "source"],
    "org_entity": ["uuid", "org_country", "org_country_cn", "org_name", "org_name_cn", "sibling_as", "v4prefixes", "v6prefixes", "sibling_as_num", "v4prefixes_num", "v6prefixes_num"],
    "website_entity": ["url", "title", "key", "description", "industry", "ip", "ip_prefix", "auth_ip", "auth_ip_prefix"],
}

# NL2SQL 提示补充：字段语义与取值约定（避免国家字段误用）
TABLE_CONTEXT_HINTS = {
    "as_entity": "as_country 使用 ISO 3166-1 alpha-2 代码（如 CN），as_country_cn 为中文国家名（如 中国）。v4prefixes/v6prefixes 是数组，表示该 AS 宣告或关联的前缀列表；统计 AS 的 IPv4/IPv6 宣告规模时，优先按 as_country 过滤并使用 cardinality(v4prefixes/v6prefixes)。",
    "asn_entity": "country 使用 ISO 3166-1 alpha-2 代码（如 CN）。",
    "country_entity": "country 为 ISO 3166-1 alpha-2 代码，country_cn 为中文国家名。",
    "ip_bgp_entity": "country 使用 ISO 3166-1 alpha-2 代码。route 是注册侧归属 ASN 数组，bgp 是观测侧归属 ASN；涉及 BGP 前缀宣告分布时，可按 bgp 或对 route 做数组展开统计，不要把数组列直接与标量做等值连接。",
    "ipv4_entity": "country 使用 ISO 3166-1 alpha-2 代码。",
    "ipv6_entity": "country 使用 ISO 3166-1 alpha-2 代码。",
    "org_entity": "org_country 使用 ISO 3166-1 alpha-2 代码，org_country_cn 为中文国家名。",
}


_TABLE_COMMENT_RE = re.compile(r'^COMMENT ON TABLE public\."([^"]+)" IS \'(.*)\';\s*$')
_COLUMN_COMMENT_RE = re.compile(r'^COMMENT ON COLUMN public\."([^"]+)"\."([^"]+)" IS \'(.*)\';\s*$')
_SCHEMA_COMMENTS_FILE = Path(__file__).resolve().parents[2] / "database" / "core_schema_comments.review.sql"


def _normalize_identifier(name: str) -> str:
    """将数据库标识符标准化为小写下划线风格。"""
    text = str(name).strip().lower()
    text = re.sub(r"[^0-9a-z_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def _compact_comment(raw_text: str, max_len: int = 96) -> str:
    """
    压缩注释文本，避免 prompt 过长。

    处理策略：
    1) 还原 SQL 字符串中的转义单引号；
    2) 去掉“示例”尾注，仅保留语义描述；
    3) 控制最大长度，超过则截断。
    """
    text = raw_text.replace("''", "'").strip()
    marker = "(示例:"
    marker_index = text.find(marker)
    if marker_index >= 0:
        text = text[:marker_index].rstrip(" 。.")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    return f"{text[:max_len].rstrip()}..."


def _load_review_comments(path: Path) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
    """
    从 core_schema_comments.review.sql 解析表/字段注释。

    返回：
    - table_comments: {table -> comment}
    - column_comments: {table -> {column -> comment}}
    """
    table_comments: Dict[str, str] = {}
    column_comments: Dict[str, Dict[str, str]] = {}

    if not path.exists():
        return table_comments, column_comments

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return table_comments, column_comments

    for line in lines:
        stmt = line.strip()
        if not stmt or stmt.startswith("--"):
            continue

        table_match = _TABLE_COMMENT_RE.match(stmt)
        if table_match:
            table_name, raw_comment = table_match.groups()
            table_comments[_normalize_identifier(table_name)] = _compact_comment(raw_comment)
            continue

        column_match = _COLUMN_COMMENT_RE.match(stmt)
        if column_match:
            table_name, column_name, raw_comment = column_match.groups()
            normalized_table = _normalize_identifier(table_name)
            normalized_column = _normalize_identifier(column_name)
            table_columns = column_comments.setdefault(normalized_table, {})
            table_columns[normalized_column] = _compact_comment(raw_comment)

    return table_comments, column_comments


# 从评审注释文件加载的表/字段语义注释，用于 NL2SQL prompt 辅助信息。
TABLE_REVIEW_COMMENTS, COLUMN_REVIEW_COMMENTS = _load_review_comments(_SCHEMA_COMMENTS_FILE)
