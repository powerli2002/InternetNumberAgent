from src.utils.logging_manager import logger
from src import BaseEntity

import os
import ast
import pandas as pd


class IPDelegateFormatter(BaseEntity):
    def __init__(self, date: str, config_path='conf/config.yaml', enable_DB=True):
        '''
        IP 地址前缀委托实体格式化工具

        Parameters:

            date - 日期，格式为 YYYY-MM-DD。请注意，本类将根据该日期读取相应的数据文件（包括但不限于 RIR 文件等），因此可能需要根据数据需求自行更改而不是直接使用当前日期。

            config_path - 配置文件路径

            enable_DB - 是否启用数据库

        '''
        super().__init__(config_path, date, enable_DB)

    def run(self):
        logger.info(f'开始处理 opq_id 信息')
        opq = pd.read_csv(f'{self.format_dir}{self.date}/asn.csv', usecols=['asn', 'opq_id'], dtype=str,
                          keep_default_na=False, na_values=[''])
        ase = pd.read_csv(os.path.join(self.target_dir, 'format', f'as_entity_{self.date}.csv'),
                          usecols=['asn', 'org_name', 'uuid'], dtype=str)
        df = opq.merge(ase, on='asn', how='outer')[['opq_id', 'org_name', 'uuid']].dropna(subset=['opq_id'])
        opq_org_map = {}
        for opq_id, org_name, uuid in zip(df['opq_id'], df['org_name'], df['uuid']):
            if opq_id in opq_org_map:
                opq_org_map[opq_id].append((org_name, uuid))
            else:
                opq_org_map[opq_id] = [(org_name, uuid)]
        for k in opq_org_map:
            opq_org_map[k] = max(set(opq_org_map[k]), key=opq_org_map[k].count)

        logger.info(f'开始处理委托 AS 信息')
        asn = pd.read_csv(f'{self.format_dir}{self.date}/asn.csv', dtype=str, keep_default_na=False, na_values=[''])
        asn['org_name'], asn['uuid'] = zip(*asn['opq_id'].apply(lambda x: opq_org_map.get(x, (None, None))))
        asn = asn[['asn', 'source', 'country', 'opq_id', 'date', 'status', 'org_name', 'uuid']]
        asn.to_csv(os.path.join(self.target_dir, 'format', f'asn_entity.csv'), index=False)
        if self.enable_DB:
            self.DB_Tool_instance.df_to_DB(asn, 'asn_entity', ['asn'], {'asn':'integer'})

        logger.info(f'开始处理委托 IPv4 信息')
        ipv4 = pd.read_csv(f'{self.format_dir}{self.date}/ipv4.csv', dtype=str, keep_default_na=False, na_values=[''])
        ipv4['org_name'], ipv4['uuid'] = zip(*ipv4['org_id'].apply(lambda x: opq_org_map.get(x, (None, None))))
        ipv4['sibling_as'] = None
        ipv4 = ipv4[['prefix', 'prefix_len', 'source', 'country', 'org_id', 'date', 'status', 'org_name', 'sibling_as', 'uuid']]
        ipv4.to_csv(os.path.join(self.target_dir, 'format', f'ipv4_entity.csv'), index=False)
        if self.enable_DB:
            self.DB_Tool_instance.df_to_DB(ipv4, 'ipv4_entity', ['prefix'], {'prefix':'inet', 'prefix_len':'integer', 'sibling_as': 'bigint[]'})
            self.DB_Tool_instance.query_by_sql('CREATE INDEX IF NOT EXISTS ipv4_entity_idx ON ipv4_entity (prefix);')

        logger.info(f'开始处理委托 IPv6 信息')
        ipv6 = pd.read_csv(f'{self.format_dir}{self.date}/ipv6.csv', dtype=str, keep_default_na=False, na_values=[''])
        ipv6['org_name'], ipv6['uuid'] = zip(*ipv6['org_id'].apply(lambda x: opq_org_map.get(x, (None, None))))
        ipv6['sibling_as'] = None
        ipv6 = ipv6[['prefix', 'prefix_len', 'source', 'country', 'org_id', 'date', 'status', 'org_name', 'sibling_as', 'uuid']]
        ipv6.to_csv(os.path.join(self.target_dir, 'format', f'ipv6_entity.csv'), index=False)
        if self.enable_DB:
            self.DB_Tool_instance.df_to_DB(ipv6, 'ipv6_entity', ['prefix'], {'prefix':'inet', 'prefix_len':'integer', 'sibling_as': 'bigint[]'})
            self.DB_Tool_instance.query_by_sql('CREATE INDEX IF NOT EXISTS ipv6_entity_idx ON ipv6_entity (prefix);')
