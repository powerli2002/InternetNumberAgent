import ast
import io
import logging
import os
import sys
import time

import pandas as pd
import pytricia
from pandas._libs.lib import _NoDefault

from src import BaseEntity
from src.utils.logging_manager import init_logger


def create_logger() -> logging.Logger:
    """
    自用的日志模块

    Returns:

        logging.Logger - 日志实例

    """

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(filename)s[line:%(lineno)d] - %(levelname)s - %(message)s"
    )

    file_handler = logging.FileHandler(
        f'./logs/{time.strftime("%Y%m%d", time.localtime(time.time()))}.log', mode="w", encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    logging.getLogger("gensim").setLevel(logging.WARNING)

    return logger


# logger = init_logger()
logger = create_logger()


class DNSEntityFormatter(BaseEntity):
    def __init__(
        self,
        dns_data_dir: str,
        website_industry_dir: str,
        ipv4_prefix_dir: str,
        output_dir="./data/format/",
        date="2023-07-20",
        config_path="config.yaml",
        enable_DB=False,
    ) -> None:
        """
        网站实体格式化工具

        Parameters:

            dns_data_dir - 网站 DNS 爬取结果数据文件路径

            website_industry_dir - 网站归属行业数据文件路径

            ipv4_prefix_dir - IPv4 前缀列表文件路径

            output_dir - 输出文件夹路径

            date - 日期，格式为 YYYY-MM-DD

            config_path - 配置文件路径

            enable_DB - 是否启用数据库

        """

        super().__init__(config_path, date, enable_DB)
        self.dns_data_dir = dns_data_dir
        self.website_industry_dir = website_industry_dir
        self.ipv4_prefix_dir = ipv4_prefix_dir
        self.output_dir = output_dir

    def deal_with_bad_line(self, bad_line: list[str], sep: str) -> None:
        """
        处理输入 csv 中格式错误（分隔符过多）的行

        Parameters:

            bad_line - 一个字符串列表，表示由分隔符分隔的错误行的数据

        """

        logger.warning(f"坏行: {sep.join(bad_line)}")

    def csv_to_df(
        self,
        csv_path: str,
        meaning: str = "",
        sep=_NoDefault.no_default,
        header="infer",
        names=_NoDefault.no_default,
        usecols=None,
        dtype=None,
        converters=None,
        on_bad_lines="error",
    ) -> pd.DataFrame:
        """
        读取一个 csv 数据文件，生成 DataFrame (对 pd.read_csv() 的包装)

        Parameters:

            csv_path - csv 数据文件路径

            meaning - 该数据文件的含义（用于日志输出）

            sep, header, names, usecols, dtype, converters, on_bad_lines - 传递给 pd.read_csv() 的对应参数

        Returns:

            pd.DataFrame - 从 csv 数据文件读取出的 DataFrame

        """

        start_time = time.time()

        if not os.path.exists(csv_path):
            logger.error(f"数据文件 {csv_path} 不存在")
            sys.exit(1)

        # 读取 csv 数据文件
        df = pd.read_csv(
            csv_path,
            sep=sep,
            header=header,
            names=names,
            usecols=usecols,
            dtype=dtype,
            converters=converters,
            on_bad_lines=on_bad_lines,
        )

        end_time = time.time()
        logger.info(f"{meaning}读取完成，耗时: {round(end_time - start_time, 1)} 秒")

        return df

    def get_df_info(self, df: pd.DataFrame) -> str:
        """
        获取 DataFrame 的统计信息 (对 df.info() 的包装)

        Parameters:

            df - 目标 DataFrame

        Returns:

            str - 统计信息

        """

        buf = io.StringIO()
        df.info(verbose=True, buf=buf, memory_usage=True, show_counts=True)
        df_info = buf.getvalue().strip()
        buf.close()
        return df_info

    def run(self) -> None:
        """
        运行网站实体格式化工具

        """

        start_time = time.time()
        logger.info("网站实体处理开始")

        # 读取网站实体相关原始数据
        self.read_data()

        # 处理生成网站实体
        self.format_entity()

        # 调试信息，比较读取的网站数据与最终生成的网站实体
        # test_index = 'antena3.com'  # top_ip_preview.csv
        test_index = "youth.cn"  # total_preview.csv
        logger.info(f"网站 DNS 数据[{test_index}]: \n{self.df_dns_data.loc[test_index]}")
        logger.info(f"网站实体[{test_index}]: \n{self.df_website_entity.loc[test_index]}\n\n\n")

        # 输出处理完成的网站实体
        self.export_entity(self.df_website_entity)

        end_time = time.time()
        logger.info(f"网站实体处理完毕，总计耗时: {round(end_time - start_time, 1)} 秒")

    def read_data(self) -> None:
        """
        读取网站实体相关原始数据

        """

        start_time = time.time()
        logger.info("第一部分 - 数据读取开始")

        # 读取网站 DNS 爬取结果数据文件，生成 DataFrame
        self.df_dns_data = self.csv_to_df(
            csv_path=self.dns_data_dir,
            meaning="网站 DNS 爬取结果",
            sep=";",
            dtype={"url": str, "ip": str, "auth_ip": str, "title": str, "key": str, "description": str},
            converters={"ip": lambda x: ast.literal_eval(x), "auth_ip": lambda x: ast.literal_eval(x)},
            on_bad_lines="warn",
        )
        # 输出 DataFrame 统计信息
        logger.info(f"原始 DNS 数据 DataFrame 统计信息: \n{self.get_df_info(self.df_dns_data)}")
        # 对 url 列进行去重
        self.df_dns_data.drop_duplicates(subset=["url"], inplace=True)
        # 将 url 列设置为索引
        self.df_dns_data.set_index("url", inplace=True)
        # 删除 ip, auth_ip, title, key, description 列均为空的行
        self.df_dns_data.dropna(how="all", inplace=True)
        # 输出 DataFrame 统计信息
        logger.info(f"处理后 DNS 数据 DataFrame 统计信息: \n{self.get_df_info(self.df_dns_data)}")

        # 读取网站归属行业数据文件，生成 DataFrame
        self.df_website_industry = self.csv_to_df(
            csv_path=self.website_industry_dir,
            meaning="网站归属行业数据",
            header=None,
            names=["url", "industry"],
            dtype={"url": str, "industry": str},
        )
        # 对 url 列进行去重
        self.df_website_industry.drop_duplicates(subset=["url"], inplace=True)
        # 将 url 列设置为索引
        self.df_website_industry.set_index("url", inplace=True)
        # 输出网站归属行业有哪些种类
        logger.info(f'网站归属行业的种类有: {self.df_website_industry["industry"].unique()}')
        # 输出 DataFrame 统计信息
        logger.info(f"网站归属行业 DataFrame 统计信息: \n{self.get_df_info(self.df_website_industry)}")

        # 读取 IPv4 前缀数据文件，生成 DataFrame
        df_ipv4_prefix = self.csv_to_df(
            csv_path=self.ipv4_prefix_dir,
            meaning="IPv4 前缀数据",
            usecols=["prefix"],
            dtype={"prefix": str},
        )
        # 对 prefix 列进行去重
        df_ipv4_prefix.drop_duplicates(subset=["prefix"], inplace=True)
        # 输出 DataFrame 统计信息
        logger.info(f"IPv4 前缀 DataFrame 统计信息: \n{self.get_df_info(df_ipv4_prefix)}")

        # 创建 Pytricia 字典树用于查找数据中 IP 地址对应前缀
        self.pyt_ipv4_prefix = pytricia.PyTricia()
        for prefix in df_ipv4_prefix["prefix"]:
            self.pyt_ipv4_prefix.insert(prefix, True)
        logger.info(f"Pytricia 字典树前 10 项: \n{self.pyt_ipv4_prefix.keys()[:10]}")

        end_time = time.time()
        logger.info(f"第一部分 - 数据读取完毕，耗时: {round(end_time - start_time, 1)} 秒\n\n\n")

    def format_entity(self) -> None:
        logger.info("第二部分 - 网站实体格式化开始")
        start_time = time.time()

        # 创建网站实体 DataFrame
        new_entity_columns = ["title", "key", "description", "ip", "auth_ip"]
        self.df_website_entity = self.df_dns_data.reindex(columns=new_entity_columns)

        # 匹配网站归属行业数据
        self.match_industry()

        # 匹配网站 IP 地址和权威 IP 地址对应的前缀
        self.match_prefix()

        # 调整网站实体列的顺序
        website_entity_columns = [
            "title",
            "key",
            "description",
            # "archive_info",
            # "archive_company",
            "industry",
            "ip",
            "ip_prefix",
            "auth_ip",
            "auth_ip_prefix",
        ]
        self.df_website_entity = self.df_website_entity.reindex(columns=website_entity_columns)

        df_website_entity_info = self.get_df_info(self.df_website_entity)

        end_time = time.time()
        logger.info(f"第二部分 - 网站实体格式化结束, 耗时: {round(end_time - start_time, 1)} 秒")
        logger.info(f"self.df_website_entity.info(): \n{df_website_entity_info}\n\n\n")

    def match_industry(self) -> None:
        """
        处理网站实体中的'industry'字段，根据输入的网站归属行业数据匹配网站归属行业。
        """

        start_time = time.time()
        logger.info("网站归属行业匹配开始")

        # 开始精确匹配(使用 pd.merge() 合并)
        # pd.merge_asof() 只能模糊匹配数字型的值，因此无法对 URL 使用
        self.df_website_entity = pd.merge(
            self.df_website_entity, self.df_website_industry, how="left", left_index=True, right_index=True
        )

        """
        开始对归属行业空值进行处理(模糊匹配)
        1.尝试使用 thefuzz (fuzzywuzzy) 库匹配
        但是从 800w 域名列表中匹配出一个域名就需要 1-3 分钟，无法接受
        2.尝试使用 pytrie 库匹配(https://www.python100.com/html/111046.html)
        但是这玩意也不能模糊匹配啊，貌似只能前缀匹配
        3.尝试使用 wordninja 分词后 gensim 批量匹配(https://www.jb51.net/article/239151.htm)
        但是它需要创建一个大小是源数据长度×待匹配数据长度的 float32 型矩阵
        对 746w 行源数据来说，即使待匹配数据只有 3000 行，这个矩阵也需要 82.8 GiB 内存
        或许可以分块读取处理，但是没那么多时间了
        4.尝试使用 difflib 库中的 get_close_matches() 方法匹配
        设置 cutoff=0 时匹配一条也要一分多钟
        cutoff 变大匹配会变快，但终究是秒级以上的，没那么多时间匹配 800w 条
        """

        end_time = time.time()
        logger.info(f"网站归属行业匹配完毕，耗时: {round(end_time - start_time, 1)} 秒")

    def match_prefix(self) -> None:
        """
        处理网站实体中的'ip_prefix'和'auth_ip_prefix'字段，根据 IP 地址列表匹配生成 IP 地址前缀列表。

        """

        def get_prefixes(ip_list: list or None) -> list or None:
            """
            根据 IP 地址列表查询生成相应的 IP 地址前缀列表。

            Parameters:

                ip_list - 待查询的 IP 地址列表

            Returns:

                list or None - 对应的 IP 地址前缀列表(没有则返回 None)

            """
            try:
                if ip_list is None or len(ip_list) == 0:
                    return None
                else:
                    prefixes = set()
                    for ip in ip_list:
                        try:
                            # 根据 total.csv 匹配出的结果来看，应该不会有哪个 IP 地址能匹配出空字符串来
                            prefixes.add(self.pyt_ipv4_prefix.get_key(ip))
                        except ValueError as e:
                            # logger.error(f'{ip} 匹配错误: {e}')
                            # prefixes.add(ip)
                            pass
                    # logger.info(f'{ip_list} 匹配结果: {prefixes}')
                    return list(prefixes)
            except AttributeError as e:
                logger.error(f"{ip_list} 异常: {e}")
                sys.exit(1)

        start_time = time.time()
        logger.info("IP 地址前缀列表生成开始")
        self.df_website_entity["ip_prefix"] = self.df_website_entity["ip"].apply(get_prefixes)
        self.df_website_entity["auth_ip_prefix"] = self.df_website_entity["auth_ip"].apply(get_prefixes)
        # self.df_website_entity.drop(columns="auth_ip", inplace=True)
        end_time = time.time()
        logger.info(f"IP 地址前缀列表生成完毕，耗时: {round(end_time - start_time, 1)} 秒")

    def export_entity(self, df_website_entity: pd.DataFrame, name: str = "website_entity_base.csv") -> None:
        """
        将网站实体输出到 CSV 文件或 Postgre 数据库

        Parameters:

            df_website_entity - 网站实体 DataFrame

            name - 要保存的文件名，默认为"website_entity_base.csv"

        """

        start_time = time.time()
        logger.info("网站实体输出开始")

        if self.enable_DB:
            # TODO: 输出到 Postgre 数据库
            pass
        else:
            # 输出到 CSV 文件
            if not os.path.exists(self.output_dir):
                os.makedirs(self.output_dir)
            df_website_entity.to_csv(
                os.path.join(self.output_dir, name),
                sep=";",
                # na_rep="暂无",
            )

        end_time = time.time()
        logger.info(f"网站实体输出结束, 耗时: {round(end_time - start_time, 1)} 秒")

    def merge_missing_industry(self, website_entity_dir: str, complementary_industry_dir: str) -> None:
        """
        补全网站实体中缺失的归属行业

        Parameters:

            complementary_industry_dir - 待补充进去的归属行业数据文件路径

        """

        start_time = time.time()
        logger.info("开始补充网站归属行业")

        # 读取网站实体
        df_website_entity = self.csv_to_df(
            csv_path=website_entity_dir,
            meaning="网站实体数据",
            sep=";",
            dtype={
                "url": str,
                "title": str,
                "key": str,
                "description": str,
                "industry": str,
                "ip": str,
                "ip_prefix": str,
                "auth_ip": str,
                "auth_ip_prefix": str,
            },
        )
        # 输出 DataFrame 统计信息
        logger.info(f"网站实体 DataFrame 统计信息: \n{self.get_df_info(df_website_entity)}")

        # 读取待补充的归属行业数据
        df_complementary_industry = self.csv_to_df(
            csv_path=complementary_industry_dir,
            meaning="待补充的归属行业数据",
            dtype={"url": str, "industry": str},
        )

        # 将英文的分类转换为中文的归属行业
        industry_mapping = {
            "search-engine": "搜索导航",
            "programming": "网络科技",
            "shopping": "购物电商",
            "entertainment": "休闲娱乐",
            "sports": "体育健身",
            "social": "社交综合",
            "technology": "网络科技",
            "education": "教育教学",
            "business": "行业企业",
            "gaming": "休闲娱乐",
            "news": "新闻媒体",
        }
        df_complementary_industry["industry"] = df_complementary_industry["industry"].astype(str).map(industry_mapping)

        # 输出网站归属行业有哪些种类
        logger.info(f'待补充数据中的归属行业种类有: {df_complementary_industry["industry"].unique()}')
        # 输出 DataFrame 统计信息
        logger.info(f"待补充数据 DataFrame 统计信息: \n{self.get_df_info(df_complementary_industry)}")

        # 使用 pd.merge() 函数合并数据
        merged_df = pd.merge(df_website_entity, df_complementary_industry, on="url", how="left")

        # 使用补充数据填充空值
        merged_df["industry_x"].fillna(merged_df["industry_y"], inplace=True)

        # 删除多余的列
        merged_df.drop(["industry_y"], axis=1, inplace=True)
        merged_df.rename(columns={"industry_x": "industry"}, inplace=True)

        # 将 url 列设置为索引列
        merged_df.set_index("url", inplace=True)

        # 获取 DataFrame 的统计信息
        merged_df_info = self.get_df_info(merged_df)
        logger.info(f"merged_df.info(): \n{merged_df_info}")
        logger.info(f'补充后的完整归属行业有: {merged_df["industry"].unique()}')

        # 输出补充后的网站实体
        self.export_entity(merged_df)

        end_time = time.time()
        logger.info(f"网站归属行业补充结束, 耗时: {round(end_time - start_time, 1)} 秒")

    def merge_website_entity(self, website_entity_dir: str, website_entity_names: list) -> None:
        """
        合并指定的网站实体并输出

        Parameters:

            website_entity_dir - 网站实体数据文件路径

            website_entity_names - 网站实体数据文件名称列表

        """

        logger.info("网站实体合并开始")
        start_time = time.time()

        # 逐个读取网站实体
        df_website_entities = []
        for website_entity_name in website_entity_names:
            # 读取网站实体
            path = os.path.join(website_entity_dir, website_entity_name)
            df_website_entity = self.csv_to_df(
                csv_path=path,
                meaning=website_entity_name,
                sep=";",
                dtype={
                    "url": str,
                    "title": str,
                    "key": str,
                    "description": str,
                    "industry": str,
                    "ip": str,
                    "ip_prefix": str,
                    "auth_ip": str,
                    "auth_ip_prefix": str,
                },
            )

            # 输出 DataFrame 统计信息
            logger.info(f"网站实体 {website_entity_name} 统计信息: \n{self.get_df_info(df_website_entity)}")
            df_website_entities.append(df_website_entity)

        # 纵向连接 DataFrame
        df_merged_entity = pd.concat(df_website_entities, ignore_index=True)

        # 对 url 列进行去重
        df_merged_entity.drop_duplicates(subset=["url"], inplace=True)

        # 获取 DataFrame 的统计信息
        df_merged_entity_info = self.get_df_info(df_merged_entity)
        logger.info(f"df_merged_entity.info(): \n{df_merged_entity_info}")

        # 输出合并的网站实体
        self.export_entity(df_merged_entity)

        end_time = time.time()
        logger.info(f"网站实体合并完毕，耗时: {round(end_time - start_time, 1)} 秒")
