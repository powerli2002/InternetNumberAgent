import os
from ast import literal_eval

from src.utils.logging_manager import logger
from src import BaseEntity

import pandas as pd


class OrgEntityFormatter(BaseEntity):
    def __init__(self,  date: str, config_path='config.yaml', enable_DB=True):
        '''
        组织机构实体格式化工具

        必须先运行 org_group.py 生成 org_group_with_name_and_sibling.csv

        必须先生成 AS 实体

        Parameters:

            date - 日期，格式为 YYYY-MM-DD。请注意，本类将根据该日期读取相应的数据文件（包括但不限于 RIR 文件等），因此可能需要根据数据需求自行更改而不是直接使用当前日期。

            config_path - 配置文件路径

            enable_DB - 是否启用数据库

        '''
        super().__init__(config_path, date, enable_DB)

        logger.info('正在读取 AS 实体信息...')
        self.df_as_info = pd.read_csv(os.path.join(self.target_dir, 'format',
                                                   f'as_entity_{self.date}.csv'), usecols=['asn', 'as_country', 'as_country_cn', 'v4Prefixes', 'v6Prefixes', 'org_name', 'org_name_cn', 'sibling_as', 'uuid'], dtype={'asn': int, 'uuid': str}, keep_default_na=False)
        # self.df_as_info['sibling_as'] = self.df_as_info['sibling_as'].apply(
        #     lambda x: x if pd.isna(x) else literal_eval(x))
        # print(self.df_as_info)
        self.df_as_info['v4Prefixes'] = self.df_as_info['v4Prefixes'].apply(
            lambda x: literal_eval(x) if x and pd.notna(x) else [])
        self.df_as_info['v6Prefixes'] = self.df_as_info['v6Prefixes'].apply(
            lambda x: literal_eval(x) if x and pd.notna(x) else [])
        logger.info('AS 实体信息读取完成')

    def run(self):
        '''
        运行组织机构实体生成

        '''
        logger.info('组织机构实体生成中...')
        self.__get_org_info()
        logger.info('组织机构实体生成完成')

    def __get_org_info(self):
        '''
        获取组织机构信息

        '''
        df_org_group = self.df_as_info.groupby('uuid').agg(  # 按 uuid 分组
            {
                'as_country': lambda x: x.mode()[0],
                'as_country_cn': lambda x: x.mode()[0],
                'org_name': 'first',
                'org_name_cn': 'first',
                'sibling_as': 'first',
                'v4Prefixes': 'sum',
                'v6Prefixes': 'sum'
            }
        ).reset_index()
        df_org_group.rename(columns={'as_country': 'org_country', 'as_country_cn': 'org_country_cn'}, inplace=True)
        df_org_group['sibling_as'] = df_org_group['sibling_as'].apply(
            lambda x: literal_eval(x) if pd.notna(x) and x else None)
        df_org_group['v4Prefixes'] = df_org_group['v4Prefixes'].apply(lambda x: list(set(x)) if x != 0 else None)
        df_org_group['v6Prefixes'] = df_org_group['v6Prefixes'].apply(lambda x: list(set(x))if x != 0 else None)
        # print(df_org_group['sibling_as'])
        df_org_group['sibling_as_num'] = df_org_group['sibling_as'].apply(lambda x: len(x) if x is not None else 0)
        df_org_group['v4Prefixes_num'] = df_org_group['v4Prefixes'].apply(lambda x: len(x) if x is not None else 0)
        df_org_group['v6Prefixes_num'] = df_org_group['v6Prefixes'].apply(lambda x: len(x) if x is not None else 0)
        # print(df_org_group)
        df_org_group.to_csv(os.path.join(self.target_dir, 'format', f'org_entity_{self.date}.csv'), index=False)
