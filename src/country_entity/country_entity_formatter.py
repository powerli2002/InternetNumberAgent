from src.utils.logging_manager import logger
from src import BaseEntity

import os
from ast import literal_eval

import pandas as pd


class CountryEntityFormatter(BaseEntity):
    def __init__(self,  date: str, config_path='config.yaml', enable_DB=True):
        '''
        国家实体格式化工具

        Parameters:

            date - 日期，格式为 YYYY-MM-DD。请注意，本类将根据该日期读取相应的数据文件（包括但不限于 RIR 文件等），因此可能需要根据数据需求自行更改而不是直接使用当前日期。

            config_path - 配置文件路径

            enable_DB - 是否启用数据库

        '''
        super().__init__(config_path, date, enable_DB)
        self.col_list = ['country', 'country_cn', 'population(2016)', 'Internet_users', 'Internet_users_percentage', 'region', 'GDP_per_capita(CNY)', 'orgs', 'orgs_number', 'asns_number', 'asns',
                         'v4Prefixes_number', 'v4Prefixes', 'v6Prefixes_number', 'v6Prefixes']

    def run(self):
        df_base = self.__base_country_info()
        df_as_country = self.__country_as_entity_info()
        df_res = pd.merge(df_base, df_as_country, on='country', how='left')
        df_res = self.append_country_cn_in_df(df_res)

        for col in df_res.columns:
            if col.endswith('_number'):
                df_res[col] = df_res[col].fillna(0).astype(int)

        # df_res = df_res[self.col_list]
        df_res.to_csv(os.path.join(self.target_dir, 'format', f'country_entity_{self.date}.csv'), index=False)
        logger.info('国家实体生成完成')

    def __base_country_info(self) -> pd.DataFrame:

        logger.info('正在读取国家基本信息...')
        df_country_info = pd.read_csv('data/utils/country_info.csv', na_filter=False)
        df_country_info.rename(columns={'Country': 'country_en', 'ISO-3166 Code': 'country', 'Population': 'population',
                               'Users': 'Internet_users', 'User %': 'Internet_users_percentage', 'Region': 'region', 'GDP(CNY)': 'GDP_per_capita(CNY)'}, inplace=True)
        logger.info('读取国家基本信息完成')

        return df_country_info

    def __country_as_entity_info(self) -> pd.DataFrame:
        '''
        读取AS实体信息并提取其国家信息

        '''
        logger.info('正在读取AS实体信息...')
        as_entity_file = os.path.join(self.target_dir, 'format', f'as_entity_{self.date}.csv')
        df_as_entity = pd.read_csv(as_entity_file, usecols=['asn', 'source', 'as_country', 'uuid', 'org_country', 'v4Prefixes', 'v6Prefixes', 'is_route'], dtype={
            'asn': int}, keep_default_na=False)

        df_as_entity['v4Prefixes'] = df_as_entity['v4Prefixes'].apply(
            lambda x: literal_eval(x) if x and pd.notna(x) else [])
        df_as_entity['v6Prefixes'] = df_as_entity['v6Prefixes'].apply(
            lambda x: literal_eval(x) if x and pd.notna(x) else [])

        logger.info('获取前缀和ASN数据...')
        df_as_country_list = []
        for country, df in df_as_entity.groupby('as_country'):
            df_as_country_dict = {}
            df_as_country_dict['country'] = country
            df_as_country_dict['asns'] = df['asn'].tolist()
            df_as_country_dict['asns_number'] = len(df)
            df_is_route = df[df['is_route'] == True]
            df_as_country_dict['route_asns'] = df_is_route['asn'].tolist()
            df_as_country_dict['route_asns_number'] = len(df_is_route)

            v4_set = set()
            for prefix_list in df['v4Prefixes'].dropna().tolist():
                if prefix_list:
                    v4_set.update(prefix_list)

            df_as_country_dict['v4Prefixes'] = list(v4_set)
            df_as_country_dict['v4Prefixes_number'] = len(df_as_country_dict['v4Prefixes'])

            v6_set = set()
            for prefix_list in df['v6Prefixes'].dropna().tolist():
                if prefix_list:
                    v6_set.update(prefix_list)

            df_as_country_dict['v6Prefixes'] = list(v6_set)
            df_as_country_dict['v6Prefixes_number'] = len(df_as_country_dict['v6Prefixes'])
            df_as_country_list.append(df_as_country_dict)

        df_as_country = pd.DataFrame(df_as_country_list)
        logger.info('获取前缀和ASN数据完成')

        logger.info('获取组织机构数据...')
        df_org_country_list = []
        for country, df in df_as_entity.groupby('org_country'):
            df_org_country_dict = {}
            df_org_country_dict['country'] = country
            df_org_country_dict['orgs'] = df['uuid'].dropna().drop_duplicates().tolist()
            df_org_country_dict['orgs_number'] = len(df_org_country_dict['orgs'])
            df_org_country_list.append(df_org_country_dict)

        df_org_country = pd.DataFrame(df_org_country_list)
        logger.info('获取组织机构数据完成')

        df_as_country = pd.merge(df_as_country, df_org_country, on='country', how='left')

        return df_as_country
