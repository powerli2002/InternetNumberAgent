from fusiondata.src.utils.db_tool import DB_Tool
from fusiondata.src.utils.config_loader import load_yaml_config
from fusiondata.src.utils.logging_manager import logger

import os
import ast
import json
import ipaddress
import pandas as pd


class EntityPersistence(DB_Tool):
    def __init__(self, config_path: str, date: str):
        super().__init__(config_path, date)
        config = load_yaml_config(config_path)
        self.target_dir = config.get("output_dir", "./fusiondata/data/")

    @staticmethod
    def rebr(s: str):
        try:
            if s is None:
                return None
            if isinstance(s, str) and s.strip().lower() in ("", "nan", "none", "null"):
                return None
            return [str(x) for x in ast.literal_eval(s)]
        except Exception:
            return None

    @staticmethod
    def parse_sibling_as(value):
        # 解析 sibling_as 列，保证类型为 bigint[] 或 None
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        if isinstance(value, str) and value.strip().lower() in (
            "",
            "nan",
            "none",
            "null",
        ):
            return None
        try:
            parsed = ast.literal_eval(value) if isinstance(value, str) else value
        except Exception:
            return None
        if isinstance(parsed, (int,)):
            return [int(parsed)]
        if isinstance(parsed, float):
            return [int(parsed)] if not pd.isna(parsed) else None
        if isinstance(parsed, (list, tuple, set)):
            result = []
            for item in parsed:
                try:
                    result.append(int(item))
                except Exception:
                    continue
            return result if result else None
        return None

    @staticmethod
    def normalize_cidr(value):
        """
        将前缀字符串规范化为网络地址形式。

        例如：
        - 193.23.230.0/21 -> 193.23.224.0/21
        - 非法或空值 -> None
        """
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        text = str(value).strip()
        if not text or text.lower() in ("", "nan", "none", "null"):
            return None
        try:
            return str(ipaddress.ip_network(text, strict=False))
        except Exception:
            return None

    def iter_csv(self, filename, chunksize=None, **kwargs):
        # chunksize 为空时返回单个 DataFrame，避免整体逻辑重复
        if chunksize and chunksize > 0:
            return pd.read_csv(filename, chunksize=chunksize, **kwargs)
        return [pd.read_csv(filename, **kwargs)]

    def as_entity_prst(self, filename=None, chunksize=None):
        if not filename:
            filename = os.path.join(
                self.target_dir, "format", f"as_entity_{self.date}.csv"
            )
        logger.info(f"AS 实体持久化 {filename}")
        first = True
        for df in self.iter_csv(
            filename, chunksize=chunksize, keep_default_na=False, na_values=[""]
        ):
            df = df[
                [
                    "asn",
                    "source",
                    "opq_id",
                    "date",
                    "status",
                    "descr",
                    "registration_date",
                    "last_change_date",
                    "org_handle",
                    "administrative",
                    "technical",
                    "abuse",
                    "is_ddos_provider",
                    "as_rank",
                    "as_longitude",
                    "as_latitude",
                    "org_id",
                    "org_rank",
                    "org_country",
                    "org_country_cn",
                    "uuid",
                    "org_name",
                    "sibling_as",
                    "org_name_cn",
                    "type",
                    "type_cn",
                    "geo_country_list",
                    "geo_city_list",
                    "geo_latitude_longitude",
                    "geo_country_list_num",
                    "geo_city_list_num",
                    "geo_latitude_longitude_num",
                    "descr_cn",
                    "website",
                    "as_country",
                    "as_country_cn",
                    "aut_name",
                    "admin_info",
                    "tech_info",
                    "abuse_info",
                    "import",
                    "export",
                    "import_as",
                    "export_as",
                    "v4Upstream",
                    "v4Peer",
                    "v4Downstream",
                    "v4Propagation",
                    "v4Prefixes",
                    "v6Upstream",
                    "v6Peer",
                    "v6Downstream",
                    "v6Propagation",
                    "v6Prefixes",
                    "is_route",
                ]
            ]
            df.replace(r"^\s*$", None, regex=True, inplace=True)
            df = df.convert_dtypes()
            for col in [
                "sibling_as",
                "geo_country_list",
                "geo_city_list",
                "geo_latitude_longitude",
                "import",
                "export",
                "import_as",
                "export_as",
                "v4Upstream",
                "v4Peer",
                "v4Downstream",
                "v4Propagation",
                "v4Prefixes",
                "v6Upstream",
                "v6Peer",
                "v6Downstream",
                "v6Propagation",
                "v6Prefixes",
            ]:
                df[col] = df[col].apply(lambda x: self.rebr(x) if pd.notna(x) else x)
            self.df_to_DB(
                df,
                "as_entity",
                ctype={
                    "asn": "integer",
                    "as_rank": "integer",
                    "org_rank": "integer",
                    "geo_country_list_num": "integer",
                    "geo_city_list_num": "integer",
                    "geo_latitude_longitude_num": "integer",
                    "as_longitude": "numeric(32,8)",
                    "as_latitude": "numeric(32,8)",
                    "is_ddos_provider": "boolean",
                    "admin_info": "json",
                    "tech_info": "json",
                    "abuse_info": "json",
                    "sibling_as": "text[]",
                    "geo_country_list": "text[]",
                    "geo_city_list": "text[]",
                    "geo_latitude_longitude": "text[]",
                    "import": "text[]",
                    "export": "text[]",
                    "import_as": "text[]",
                    "export_as": "text[]",
                    "v4Upstream": "text[]",
                    "v4Peer": "text[]",
                    "v4Downstream": "text[]",
                    "v4Propagation": "text[]",
                    "v4Prefixes": "text[]",
                    "v6Upstream": "text[]",
                    "v6Peer": "text[]",
                    "v6Downstream": "text[]",
                    "v6Propagation": "text[]",
                    "v6Prefixes": "text[]",
                    "is_route": "boolean",
                },
                primary=["asn"],
                truncate=first,
            )
            first = False

    def country_entity_prst(self, filename=None, chunksize=None):
        if not filename:
            filename = os.path.join(
                self.target_dir, "format", f"country_entity_{self.date}.csv"
            )
        logger.info(f"国家实体持久化 {filename}")
        first = True
        for df in self.iter_csv(
            filename, chunksize=chunksize, keep_default_na=False, na_values=[""]
        ):
            for col in ["asns", "route_asns", "v4Prefixes", "v6Prefixes", "orgs"]:
                df[col] = df[col].apply(lambda x: self.rebr(x) if pd.notna(x) else x)
            df = df.convert_dtypes()
            self.df_to_DB(
                df,
                "country_entity",
                ctype={
                    "population": "integer",
                    "Internet_users": "integer",
                    "Internet_users_percentage": "numeric(32,8)",
                    "GDP_per_capita(CNY)": "integer",
                    "asns_number": "integer",
                    "route_asns_number": "integer",
                    "v4Prefixes_number": "integer",
                    "v6Prefixes_number": "integer",
                    "orgs_number": "integer",
                    "asns": "text[]",
                    "route_asns": "text[]",
                    "v4Prefixes": "text[]",
                    "v6Prefixes": "text[]",
                    "orgs": "text[]",
                },
                primary=["country"],
                truncate=first,
            )
            first = False

    def org_entity_prst(self, filename=None, chunksize=None):
        if not filename:
            filename = os.path.join(
                self.target_dir, "format", f"org_entity_{self.date}.csv"
            )
        logger.info(f"组织机构实体持久化 {filename}")
        first = True
        for df in self.iter_csv(
            filename, chunksize=chunksize, keep_default_na=False, na_values=[""]
        ):
            df["uuid"].fillna("", inplace=True)
            df = df.convert_dtypes()
            for col in ["sibling_as", "v4Prefixes", "v6Prefixes"]:
                df[col] = df[col].apply(lambda x: self.rebr(x) if pd.notna(x) else x)
            self.df_to_DB(
                df,
                "org_entity",
                ctype={
                    "sibling_as": "text[]",
                    "v4Prefixes": "text[]",
                    "v6Prefixes": "text[]",
                    "sibling_as_num": "integer",
                    "v4Prefixes_num": "integer",
                    "v6Prefixes_num": "integer",
                },
                primary=["uuid"],
                truncate=first,
            )
            first = False

    def website_entity_prst(self, filename=None, chunksize=None):
        if not filename:
            filename = os.path.join(
                self.target_dir, "format", f"website_entity_base.csv"
            )
        domain_file = os.path.join(self.target_dir, "format", "domain_cn.csv")
        logger.info(f"网站服务实体持久化 {filename}")

        def format_ip(addrs):
            if addrs is None or (isinstance(addrs, float) and pd.isna(addrs)):
                return None
            if isinstance(addrs, str) and addrs.strip().lower() in (
                "",
                "nan",
                "none",
                "null",
            ):
                return None
            try:
                addrs = ast.literal_eval(addrs) if isinstance(addrs, str) else addrs
            except Exception:
                return None
            l = []
            for addr in addrs if isinstance(addrs, (list, tuple, set)) else []:
                try:
                    ipaddress.IPv4Address(addr)
                    l.append(addr)
                except Exception:
                    continue
            return l if l else None

        first = True
        for src_path, sep in [(domain_file, ","), (filename, ";")]:
            if not os.path.exists(src_path):
                logger.warning(f"网站实体数据文件不存在，跳过: {src_path}")
                continue
            for df in self.iter_csv(
                src_path,
                chunksize=chunksize,
                sep=sep,
                dtype=str,
                usecols=[
                    "url",
                    "title",
                    "key",
                    "description",
                    "industry",
                    "ip",
                    "ip_prefix",
                    "auth_ip",
                    "auth_ip_prefix",
                ],
            ):
                df = df[
                    [
                        "url",
                        "title",
                        "key",
                        "description",
                        "industry",
                        "ip",
                        "ip_prefix",
                        "auth_ip",
                        "auth_ip_prefix",
                    ]
                ]
                df.drop_duplicates(subset="url", inplace=True)
                df["ip"] = df["ip"].apply(format_ip)
                df["auth_ip"] = df["auth_ip"].apply(format_ip)
                for col in ["ip_prefix", "auth_ip_prefix"]:
                    df[col] = df[col].apply(
                        lambda x: self.rebr(x) if pd.notna(x) else x
                    )
                self.df_to_DB(
                    df,
                    "website_entity",
                    ctype={
                        "ip": "text[]",
                        "ip_prefix": "text[]",
                        "auth_ip": "text[]",
                        "auth_ip_prefix": "text[]",
                    },
                    primary=["url"],
                    truncate=first,
                )
                first = False

    def industry_entity_prst(self, filename=None, chunksize=None):
        if not filename:
            filename = os.path.join(
                self.target_dir, "format", f"industry_entity_{self.date}.csv"
            )
        logger.info(f"域名行业服务实体持久化 {filename}")
        first = True
        for df in self.iter_csv(filename, chunksize=chunksize, dtype=str):
            for col in [
                "ip",
                "ip_prefix",
                "ip_org",
                "auth_ip",
                "auth_ip_prefix",
                "auth_ip_org",
            ]:
                df[col] = df[col].apply(lambda x: self.rebr(x) if pd.notna(x) else x)
            for col in ["ip_asn", "auth_ip_asn"]:
                df[col] = df[col].apply(
                    lambda x: ast.literal_eval(x) if pd.notna(x) else x
                )

            self.df_to_DB(
                df,
                "industry_entity",
                ctype={
                    "ip": "text[]",
                    "ip_prefix": "text[]",
                    "ip_asn": "bigint[]",
                    "ip_org": "text[]",
                    "auth_ip": "text[]",
                    "auth_ip_prefix": "text[]",
                    "auth_ip_asn": "bigint[]",
                    "auth_ip_org": "text[]",
                },
                truncate=first,
            )
            first = False

    def ip_inetnum_entity_prst(self, filename=None, chunksize=None):
        if not filename:
            filename = os.path.join(self.target_dir, "format", f"ip_inetnum_entity.csv")
        logger.info(f"IP 地址前缀 inetnum 分配实体持久化 {filename}")
        first = True
        for df in self.iter_csv(
            filename,
            chunksize=chunksize,
            dtype=str,
            keep_default_na=False,
            na_values=[""],
        ):
            if "CIDR" in df.columns:
                df["CIDR"] = df["CIDR"].apply(self.normalize_cidr)
            elif "cidr" in df.columns:
                df["cidr"] = df["cidr"].apply(self.normalize_cidr)
            self.df_to_DB(df, "ip_inetnum_entity", truncate=first)
            first = False

    def ipv6_inetnum_entity_prst(self, filename=None, chunksize=None):
        if not filename:
            filename = os.path.join(
                self.target_dir, "format", f"ipv6_inetnum_entity.csv"
            )
        logger.info(f"IPv6 地址前缀 inetnum 分配实体持久化 {filename}")
        first = True
        for df in self.iter_csv(
            filename,
            chunksize=chunksize,
            dtype=str,
            keep_default_na=False,
            na_values=[""],
        ):
            if "CIDR" in df.columns:
                df["CIDR"] = df["CIDR"].apply(self.normalize_cidr)
            elif "cidr" in df.columns:
                df["cidr"] = df["cidr"].apply(self.normalize_cidr)
            self.df_to_DB(df, "ipv6_inetnum_entity", truncate=first)
            first = False

    def ip_rdap_entity_prst(self, filename=None, chunksize=None):
        if not filename:
            filename = os.path.join(self.target_dir, "format", f"ip_rdap_entity.csv")
        logger.info(f"IP 地址前缀 RDAP 分配实体持久化 {filename}")
        first = True
        for df in self.iter_csv(
            filename,
            chunksize=chunksize,
            dtype=str,
            keep_default_na=False,
            na_values=[""],
        ):
            if "CIDR" in df.columns:
                df["CIDR"] = df["CIDR"].apply(self.normalize_cidr)
            elif "cidr" in df.columns:
                df["cidr"] = df["cidr"].apply(self.normalize_cidr)
            self.df_to_DB(df, "ip_rdap_entity", truncate=first)
            first = False

    def ipv6_rdap_entity_prst(self, filename=None, chunksize=None):
        if not filename:
            filename = os.path.join(self.target_dir, "format", f"ipv6_rdap_entity.csv")
        logger.info(f"IPv6 地址前缀 RDAP 分配实体持久化 {filename}")
        first = True
        for df in self.iter_csv(
            filename,
            chunksize=chunksize,
            dtype=str,
            keep_default_na=False,
            na_values=[""],
        ):
            if "CIDR" in df.columns:
                df["CIDR"] = df["CIDR"].apply(self.normalize_cidr)
            elif "cidr" in df.columns:
                df["cidr"] = df["cidr"].apply(self.normalize_cidr)
            self.df_to_DB(df, "ipv6_rdap_entity", truncate=first)
            first = False

    def ip_route_entity_prst(self, filename=None, chunksize=None):
        if not filename:
            filename = os.path.join(self.target_dir, "format", f"ip_route_entity.csv")
        logger.info(f"IP 地址前缀 route 实体持久化 {filename}")
        first = True
        for df in self.iter_csv(
            filename,
            chunksize=chunksize,
            dtype=str,
            keep_default_na=False,
            na_values=[""],
        ):
            if "CIDR" in df.columns:
                df["CIDR"] = df["CIDR"].apply(self.normalize_cidr)
            elif "cidr" in df.columns:
                df["cidr"] = df["cidr"].apply(self.normalize_cidr)
            self.df_to_DB(df, "ip_route_entity", truncate=first)
            first = False

    def ipv6_route_entity_prst(self, filename=None, chunksize=None):
        if not filename:
            filename = os.path.join(self.target_dir, "format", f"ipv6_route_entity.csv")
        logger.info(f"IPv6 地址前缀 route 实体持久化 {filename}")
        first = True
        for df in self.iter_csv(
            filename,
            chunksize=chunksize,
            dtype=str,
            keep_default_na=False,
            na_values=[""],
        ):
            if "CIDR" in df.columns:
                df["CIDR"] = df["CIDR"].apply(self.normalize_cidr)
            elif "cidr" in df.columns:
                df["cidr"] = df["cidr"].apply(self.normalize_cidr)
            self.df_to_DB(df, "ipv6_route_entity", truncate=first)
            first = False

    def as_delegate_entity_prst(self, filename=None, chunksize=None):
        if not filename:
            filename = os.path.join(self.target_dir, "format", f"asn_entity.csv")
        logger.info(f"AS delegate 委托实体持久化 {filename}")
        first = True
        for df in self.iter_csv(
            filename, chunksize=chunksize, keep_default_na=False, na_values=[""]
        ):
            df = df.convert_dtypes()
            self.df_to_DB(df, "asn_entity", ["asn"], {"asn": "integer"}, truncate=first)
            first = False

    def ip_delegate_entity_prst(self, filename=None, chunksize=None):
        if not filename:
            filename = os.path.join(self.target_dir, "format", f"ipv4_entity.csv")
        logger.info(f"IP 地址前缀 delegate 委托实体持久化 {filename}")
        first = True
        for df in self.iter_csv(
            filename, chunksize=chunksize, keep_default_na=False, na_values=[""]
        ):
            if "prefix" in df.columns:
                df["prefix"] = df["prefix"].apply(self.normalize_cidr)
            df["sibling_as"] = df["sibling_as"].apply(self.parse_sibling_as)
            df = df.convert_dtypes()
            self.df_to_DB(
                df,
                "ipv4_entity",
                ["prefix"],
                {"prefix": "inet", "prefix_len": "integer", "sibling_as": "bigint[]"},
                truncate=first,
            )
            first = False
        self.query_by_sql(
            "CREATE INDEX IF NOT EXISTS ipv4_entity_idx ON ipv4_entity (prefix);"
        )

    def ipv6_delegate_entity_prst(self, filename=None, chunksize=None):
        if not filename:
            filename = os.path.join(self.target_dir, "format", f"ipv6_entity.csv")
        logger.info(f"IPv6 地址前缀 delegate 委托实体持久化 {filename}")
        first = True
        for df in self.iter_csv(
            filename, chunksize=chunksize, keep_default_na=False, na_values=[""]
        ):
            if "prefix" in df.columns:
                df["prefix"] = df["prefix"].apply(self.normalize_cidr)
            df["sibling_as"] = df["sibling_as"].apply(self.parse_sibling_as)
            df = df.convert_dtypes()
            self.df_to_DB(
                df,
                "ipv6_entity",
                ["prefix"],
                {"prefix": "inet", "prefix_len": "integer", "sibling_as": "bigint[]"},
                truncate=first,
            )
            first = False
        self.query_by_sql(
            "CREATE INDEX IF NOT EXISTS ipv6_entity_idx ON ipv6_entity (prefix);"
        )

    def ip_bgp_entity_prst(self, filename=None, chunksize=None):
        if not filename:
            filename = os.path.join(
                self.target_dir, "format", f"ip_bgp_entity_{self.date}.csv"
            )
        logger.info(f"IP 地址前缀 BGP 路由实体持久化 {filename}")
        first = True
        for df in self.iter_csv(
            filename,
            chunksize=chunksize,
            dtype=str,
            keep_default_na=False,
            na_values=[""],
        ):
            if "prefix" in df.columns:
                df["prefix"] = df["prefix"].apply(self.normalize_cidr)
            df["route"] = df["route"].apply(
                lambda x: [int(i) for i in x.split("|")]
                if pd.notna(x) and x != ""
                else []
            )
            df["admin_route"] = df["admin_route"].apply(
                lambda x: ([x] if pd.notna(x) else []) if not isinstance(x, list) else x
            )
            df["admin_route"] = [
                json.dumps(dict(zip(k, v)))
                for k, v in zip(df["route"], df["admin_route"])
            ]
            df["route"] = df["route"].apply(lambda x: x if x else None)
            df["admin_route"] = df["admin_route"].apply(
                lambda x: x if len(x) > 2 else None
            )
            df = df.convert_dtypes()
            df["domain"] = df["domain"].apply(
                lambda x: self.rebr(x) if pd.notna(x) else x
            )
            df["domain_auth"] = df["domain_auth"].apply(
                lambda x: self.rebr(x) if pd.notna(x) else x
            )
            self.df_to_DB(
                df,
                "ip_bgp_entity",
                ctype={
                    "prefix": "cidr",
                    "prefix_len": "integer",
                    "route": "bigint[]",
                    "bgp": "bigint",
                    "admin_route": "json",
                    "domain": "text[]",
                    "domain_num": "integer",
                    "domain_auth": "text[]",
                    "domain_auth_num": "integer",
                },
                primary=["prefix", "bgp"],
                truncate=first,
            )
            first = False
        self.query_by_sql(
            "CREATE INDEX IF NOT EXISTS ip_bgp_entity_idx ON ip_bgp_entity (prefix);"
        )

    def ipv6_bgp_entity_prst(self, filename=None, chunksize=None):
        if not filename:
            filename = os.path.join(
                self.target_dir, "format", f"ipv6_bgp_entity_{self.date}.csv"
            )
        logger.info(f"IPv6 地址前缀 BGP 路由实体持久化 {filename}")
        first = True
        for df in self.iter_csv(
            filename,
            chunksize=chunksize,
            dtype=str,
            keep_default_na=False,
            na_values=[""],
        ):
            if "prefix" in df.columns:
                df["prefix"] = df["prefix"].apply(self.normalize_cidr)
            df["route"] = df["route"].apply(
                lambda x: [int(i) for i in x.split("|")]
                if pd.notna(x) and x != ""
                else []
            )
            df["admin_route"] = df["admin_route"].apply(
                lambda x: ([x] if pd.notna(x) else []) if not isinstance(x, list) else x
            )
            df["admin_route"] = [
                json.dumps(dict(zip(k, v)))
                for k, v in zip(df["route"], df["admin_route"])
            ]
            df["route"] = df["route"].apply(lambda x: x if x else None)
            df["admin_route"] = df["admin_route"].apply(
                lambda x: x if len(x) > 2 else None
            )
            df = df.convert_dtypes()
            self.df_to_DB(
                df,
                "ipv6_bgp_entity",
                ctype={
                    "prefix": "cidr",
                    "prefix_len": "integer",
                    "route": "bigint[]",
                    "bgp": "bigint",
                    "admin_route": "json",
                },
                primary=["prefix", "bgp"],
                truncate=first,
            )
            first = False
        self.query_by_sql(
            "CREATE INDEX IF NOT EXISTS ipv6_bgp_entity_idx ON ipv6_bgp_entity (prefix);"
        )

    def drop_table(self, tablename):
        if not tablename:
            return
        print("\nWARNING: The following tables will be dropped.")
        print("This should NOT be done unless you know exactly what you are doing!")
        print(f" {tablename}")
        print("You are about to do something potentially harmful.")
        print("To continue type in the phrase 'Yes, do as I say!'")
        if input() == "Yes, do as I say!":
            logger.info(f"删除数据库表 {tablename}")
            self.query_by_sql(f"DROP TABLE IF EXISTS {tablename};")
        else:
            print("Abort.\n")
