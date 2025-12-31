import math
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from utils.logging_manager import logger


def load_ip_bgp_entity(csv_path: Path, limit: Optional[int] = None) -> pd.DataFrame:
    """读取 IPv4 BGP 实体数据，只保留分析所需字段。"""
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False, na_values=[""], nrows=limit)
    need_cols = ["prefix", "prefix_len", "bgp", "route", "country"]
    missing = [c for c in need_cols if c not in df.columns]
    if missing:
        raise ValueError(f"ip_bgp_entity 缺少字段: {missing}")
    return df[need_cols].copy()


def load_as_entity(csv_path: Path) -> Optional[pd.DataFrame]:
    """读取 AS 实体数据，用于补充组织信息。"""
    if not csv_path.exists():
        logger.warning("AS 实体文件不存在，跳过补充信息: %s", csv_path)
        return None
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False, na_values=[""])
    if "asn" not in df.columns:
        logger.warning("AS 实体文件缺少 asn 字段，跳过补充信息: %s", csv_path)
        return None
    keep_cols = [
        "asn",
        "org_name",
        "org_name_cn",
        "org_country",
        "org_country_cn",
        "uuid",
    ]
    exist_cols = [c for c in keep_cols if c in df.columns]
    return df[exist_cols].copy()


def load_country_entity(csv_path: Path) -> Optional[pd.DataFrame]:
    """读取国家实体，用于补充国家中文/英文名称。"""
    if not csv_path.exists():
        logger.warning("国家实体文件不存在，跳过补充信息: %s", csv_path)
        return None
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False, na_values=[""])
    if "country" not in df.columns:
        logger.warning("国家实体缺少 country 字段，跳过补充信息: %s", csv_path)
        return None
    keep_cols = ["country", "country_en", "country_cn", "region"]
    exist_cols = [c for c in keep_cols if c in df.columns]
    return df[exist_cols].copy()


def _pick_asn(row: pd.Series) -> Optional[int]:
    for key in ("bgp", "route"):
        val = row.get(key)
        if val is None or val == "" or str(val).lower() in ("nan", "none", "null"):
            continue
        try:
            return int(float(val))
        except Exception:
            continue
    return None


def _calc_p24_count(prefix_len: int) -> int:
    # 按 /24 粒度统计：小于 /24 的按 2^(24-len) 计数，大于 /24 的按 1 计数
    if prefix_len <= 24:
        return int(math.pow(2, 24 - prefix_len))
    return 1


def build_as_territory(df_ip_bgp: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """基于 IPv4 前缀国家归属计算 AS 疆域（国家级）。"""
    df = df_ip_bgp.copy()
    df["asn"] = df.apply(_pick_asn, axis=1)
    df = df[df["asn"].notna()].copy()
    df["asn"] = df["asn"].astype(int)
    df["prefix_len"] = pd.to_numeric(df["prefix_len"], errors="coerce")
    df = df[df["prefix_len"].notna()].copy()
    df["prefix_len"] = df["prefix_len"].astype(int)
    df["country"] = df["country"].replace({"": None})
    df = df[df["country"].notna()].copy()
    df["p24_count"] = df["prefix_len"].apply(_calc_p24_count)

    detail = (
        df.groupby(["asn", "country"], as_index=False)["p24_count"]
        .sum()
        .rename(columns={"p24_count": "country_p24_count"})
    )
    totals = detail.groupby("asn", as_index=False)["country_p24_count"].sum()
    totals = totals.rename(columns={"country_p24_count": "total_p24_count"})
    detail = detail.merge(totals, on="asn", how="left")
    detail["confidence"] = detail["country_p24_count"] / detail["total_p24_count"]

    summary = (
        detail.sort_values(["asn", "country_p24_count"], ascending=[True, False])
        .groupby("asn", as_index=False)
        .head(1)
        .rename(columns={"country": "territory_country", "country_p24_count": "territory_p24_count"})
    )

    return summary.reset_index(drop=True), detail.reset_index(drop=True)


def build_as_territory_from_csv(
    csv_path: Path,
    chunksize: int = 200000,
    limit: Optional[int] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """分块读取 CSV 进行 AS 疆域统计，降低内存占用。"""
    usecols = ["prefix", "prefix_len", "bgp", "route", "country"]
    counts: dict[tuple[int, str], int] = {}

    read_kwargs = {
        "dtype": str,
        "keep_default_na": False,
        "na_values": [""],
        "usecols": usecols,
        "chunksize": chunksize,
    }
    if limit:
        read_kwargs["nrows"] = limit

    for chunk in pd.read_csv(csv_path, **read_kwargs):
        chunk["asn"] = chunk.apply(_pick_asn, axis=1)
        chunk = chunk[chunk["asn"].notna()].copy()
        if chunk.empty:
            continue
        chunk["asn"] = chunk["asn"].astype(int)
        chunk["prefix_len"] = pd.to_numeric(chunk["prefix_len"], errors="coerce")
        chunk = chunk[chunk["prefix_len"].notna()].copy()
        if chunk.empty:
            continue
        chunk["prefix_len"] = chunk["prefix_len"].astype(int)
        chunk["country"] = chunk["country"].replace({"": None})
        chunk = chunk[chunk["country"].notna()].copy()
        if chunk.empty:
            continue
        chunk["p24_count"] = chunk["prefix_len"].apply(_calc_p24_count)

        grouped = chunk.groupby(["asn", "country"], as_index=False)["p24_count"].sum()
        for _, row in grouped.iterrows():
            key = (int(row["asn"]), row["country"])
            counts[key] = counts.get(key, 0) + int(row["p24_count"])

    if not counts:
        detail = pd.DataFrame(columns=["asn", "country", "country_p24_count", "total_p24_count", "confidence"])
        summary = pd.DataFrame(columns=["asn", "territory_country", "territory_p24_count", "total_p24_count", "confidence"])
        return summary, detail

    detail = pd.DataFrame(
        [(asn, country, cnt) for (asn, country), cnt in counts.items()],
        columns=["asn", "country", "country_p24_count"],
    )
    totals = detail.groupby("asn", as_index=False)["country_p24_count"].sum()
    totals = totals.rename(columns={"country_p24_count": "total_p24_count"})
    detail = detail.merge(totals, on="asn", how="left")
    detail["confidence"] = detail["country_p24_count"] / detail["total_p24_count"]

    summary = (
        detail.sort_values(["asn", "country_p24_count"], ascending=[True, False])
        .groupby("asn", as_index=False)
        .head(1)
        .rename(columns={"country": "territory_country", "country_p24_count": "territory_p24_count"})
    )

    return summary.reset_index(drop=True), detail.reset_index(drop=True)


def enrich_summary(summary: pd.DataFrame, as_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if as_df is None:
        return summary
    as_df = as_df.copy()
    as_df["asn"] = pd.to_numeric(as_df["asn"], errors="coerce")
    as_df = as_df[as_df["asn"].notna()].copy()
    as_df["asn"] = as_df["asn"].astype(int)
    merged = summary.merge(as_df, on="asn", how="left")
    return merged.drop_duplicates(subset=["asn"])


def build_neo4j_datasets(
    summary: pd.DataFrame,
    detail: pd.DataFrame,
    as_df: Optional[pd.DataFrame] = None,
    country_df: Optional[pd.DataFrame] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """构造 Neo4j 需要的节点与关系数据。"""
    as_nodes = enrich_summary(summary, as_df)
    as_nodes = as_nodes[
        [
            "asn",
            "territory_country",
            "territory_p24_count",
            "total_p24_count",
            "confidence",
        ]
        + [c for c in ("org_name", "org_name_cn", "org_country", "org_country_cn", "uuid") if c in as_nodes.columns]
    ].copy()

    if country_df is not None:
        country_nodes = country_df.copy()
    else:
        country_nodes = pd.DataFrame({"country": sorted(detail["country"].unique().tolist())})

    territory_rels = detail.rename(
        columns={"country": "country_code"}
    )["asn country_code country_p24_count total_p24_count confidence".split()].copy()

    return as_nodes, country_nodes, territory_rels


def load_to_neo4j(
    uri: str,
    user: str,
    password: str,
    as_nodes: pd.DataFrame,
    country_nodes: pd.DataFrame,
    territory_rels: pd.DataFrame,
    batch_size: int = 1000,
) -> None:
    """写入 Neo4j（AS、Country、TERRITORY 关系）。"""
    def chunk_rows(df: pd.DataFrame, size: int):
        for start in range(0, len(df), size):
            chunk = df.iloc[start:start + size].copy()
            chunk = chunk.where(pd.notna(chunk), None)
            yield chunk.to_dict("records")

    try:
        from neo4j import GraphDatabase
    except Exception:
        GraphDatabase = None

    if GraphDatabase is None:
        # 兼容未安装 neo4j 驱动的环境，改用 HTTP 接口
        import base64
        import json
        from urllib import request

        def to_http_uri(bolt_uri: str) -> str:
            if bolt_uri.startswith("bolt://"):
                bolt_uri = bolt_uri.replace("bolt://", "http://", 1)
            if ":" in bolt_uri.rsplit("/", 1)[-1]:
                host, _ = bolt_uri.rsplit(":", 1)
                return f"{host}:7474"
            return bolt_uri

        http_uri = to_http_uri(uri).rstrip("/") + "/db/neo4j/tx/commit"
        auth = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("utf-8")
        headers = {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        }

        def run_http(statement: str, params: Optional[dict] = None) -> None:
            payload = {"statements": [{"statement": statement, "parameters": params or {}}]}
            data = json.dumps(payload).encode("utf-8")
            req = request.Request(http_uri, data=data, headers=headers, method="POST")
            with request.urlopen(req, timeout=60) as resp:
                if resp.status not in (200, 201):
                    raise RuntimeError(f"Neo4j HTTP 写入失败: {resp.status}")
                body = resp.read().decode("utf-8")
                result = json.loads(body) if body else {}
                if result.get("errors"):
                    raise RuntimeError(f"Neo4j HTTP 写入错误: {result['errors']}")

        logger.warning("未安装 neo4j 驱动，使用 HTTP 接口写入")
        run_http("CREATE CONSTRAINT IF NOT EXISTS FOR (a:AS) REQUIRE a.asn IS UNIQUE")
        run_http("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Country) REQUIRE c.country IS UNIQUE")

        for rows in chunk_rows(as_nodes, batch_size):
            run_http(
                "UNWIND $rows AS row "
                "MERGE (a:AS {asn: row.asn}) "
                "SET a += row",
                {"rows": rows},
            )

        for rows in chunk_rows(country_nodes, batch_size):
            run_http(
                "UNWIND $rows AS row "
                "MERGE (c:Country {country: row.country}) "
                "SET c += row",
                {"rows": rows},
            )

        for rows in chunk_rows(territory_rels, batch_size):
            run_http(
                "UNWIND $rows AS row "
                "MATCH (a:AS {asn: row.asn}) "
                "MATCH (c:Country {country: row.country_code}) "
                "MERGE (a)-[r:TERRITORY]->(c) "
                "SET r.country_p24_count = row.country_p24_count, "
                "    r.total_p24_count = row.total_p24_count, "
                "    r.confidence = row.confidence",
                {"rows": rows},
            )
    else:
        with GraphDatabase.driver(uri, auth=(user, password)) as driver:
            with driver.session() as session:
                # 建约束，避免重复
                session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (a:AS) REQUIRE a.asn IS UNIQUE")
                session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Country) REQUIRE c.country IS UNIQUE")

                for rows in chunk_rows(as_nodes, batch_size):
                    session.run(
                        "UNWIND $rows AS row "
                        "MERGE (a:AS {asn: row.asn}) "
                        "SET a += row",
                        rows=rows,
                    )

                for rows in chunk_rows(country_nodes, batch_size):
                    session.run(
                        "UNWIND $rows AS row "
                        "MERGE (c:Country {country: row.country}) "
                        "SET c += row",
                        rows=rows,
                    )

                for rows in chunk_rows(territory_rels, batch_size):
                    session.run(
                        "UNWIND $rows AS row "
                        "MATCH (a:AS {asn: row.asn}) "
                        "MATCH (c:Country {country: row.country_code}) "
                        "MERGE (a)-[r:TERRITORY]->(c) "
                        "SET r.country_p24_count = row.country_p24_count, "
                        "    r.total_p24_count = row.total_p24_count, "
                        "    r.confidence = row.confidence",
                        rows=rows,
                    )

    logger.info("Neo4j 写入完成: AS=%s, Country=%s, Territory=%s",
                len(as_nodes), len(country_nodes), len(territory_rels))
