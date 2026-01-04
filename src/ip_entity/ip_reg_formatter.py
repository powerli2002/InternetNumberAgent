from src.utils.logging_manager import logger
from src import BaseEntity

import os
import ast
import ipaddress
import numpy as np
import pandas as pd
from collections import namedtuple


class IPRegFormatter(BaseEntity):
    def __init__(self, date: str, config_path='conf/config.yaml', enable_DB=True):
        '''
        IP 地址前缀分配实体格式化工具

        Parameters:

            date - 日期，格式为 YYYY-MM-DD。请注意，本类将根据该日期读取相应的数据文件（包括但不限于 RIR 文件等），因此可能需要根据数据需求自行更改而不是直接使用当前日期。

            config_path - 配置文件路径

            enable_DB - 是否启用数据库

        '''
        super().__init__(config_path, date, enable_DB)

    def run(self):
        ase = pd.read_csv(os.path.join(self.target_dir, 'format', f'as_entity_{self.date}.csv'),
                usecols=['org_handle', 'org_name', 'org_name_cn', 'uuid'], dtype=str)
        ase = ase[ase['org_handle'].notna()]
        ase.drop_duplicates(subset=['org_handle'])
        POINFO = namedtuple('POINFO', ['name', 'name_cn', 'uuid'])
        POINFO.__new__.__defaults__ = (None,) * len(POINFO._fields)
        handle_org_map = {}
        for handle, name, name_cn, uuid in zip(ase['org_handle'], ase['org_name'],
                                                           ase['org_name_cn'], ase['uuid']):
            handle_org_map[handle] = POINFO(name, name_cn, uuid)

        def format_country(x: str) -> str:
            if pd.notna(x):
                x = x.upper()
                if len(x) != 2:
                    if '#' not in x:
                        s = set(x.split('|'))
                        if len(s) == 1:
                            x = s.pop()
            return x


        # ip_inetnum_entity
        df_inetnum = pd.DataFrame()
        inetnum_list = ['apnic', 'ripe', 'afrinic']
        for rir in inetnum_list:
            logger.info(f'正在处理 {rir} 前缀 inetnum 信息')
            if rir != 'afrinic':
                df = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_inetnum_whois_info.csv', 
                                 usecols=['CIDR', 'netname', 'descr', 'country', 'source',
                                          'admin-c', 'tech-c', 'abuse-c', 'org'],
                                 dtype=str, keep_default_na=False, na_values=[''])
            else:
                # AFRINIC inetnum 无 CIDR 字段，需由 IP 地址范围转换得到，且无 abuse-c
                df = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_inetnum_whois_info.csv', 
                                 usecols=['inetnum', 'netname', 'descr', 'country',
                                          'source', 'admin-c', 'tech-c', 'org'],
                                 dtype=str, keep_default_na=False, na_values=[''])
                df.dropna(subset=['inetnum'], inplace=True)
                def ip_range_to_cidr(inetnum):
                    iprange = inetnum.split('-')
                    startip = ipaddress.IPv4Address(iprange[0])
                    endip = ipaddress.IPv4Address(iprange[1])
                    cidrs = [ipaddr for ipaddr in ipaddress.summarize_address_range(startip, endip)]
                    return str(cidrs[0])
                df['inetnum'] = df['inetnum'].apply(ip_range_to_cidr)
                df.rename(columns={'inetnum': 'CIDR'}, inplace=True)
                df['abuse-c'] = pd.Series(dtype=object)

            # 过滤未分配给该 RIR 或无有效信息的前缀
            df = df[df['CIDR'] != '0.0.0.0/0']
            if rir == 'apnic':
                df = df[~df['descr'].str.contains('not allocated', case=False, na=False)]
                df = df[~df['descr'].str.contains('not fully allocated', case=False, na=False)]
                df = df[~df['descr'].str.contains('early registration', case=False, na=False)]
            elif rir == 'ripe':
                df = df[~df['netname'].str.contains('NON-RIPE', case=False, na=False)]
            elif rir == 'afrinic':
                df = df[~df['descr'].str.contains('This block is allocated', case=False, na=False)]
                df = df[~df['descr'].str.contains('Allocation for Africa', case=False, na=False)]

            df = df[['CIDR', 'netname', 'descr', 'country', 'source', 'admin-c', 'tech-c', 'abuse-c', 'org']]
            # for col in ['netname', 'descr', 'country', 'source', 'admin-c', 'tech-c', 'abuse-c','org']:
            #     df[col] = df[col].apply(lambda x: '|'.join(ast.literal_eval(x)) if pd.notna(x) else x)
            df.dropna(subset=['CIDR'], inplace=True)
            df_inetnum = pd.concat([df_inetnum, df], ignore_index=True)

        df_inetnum['org_name'], df_inetnum['org_name_cn'], df_inetnum['org_uuid'] = \
            zip(*df_inetnum['org'].apply(lambda x: handle_org_map.get(x, POINFO())))
        df_inetnum['country'] = df_inetnum['country'].apply(format_country)
        df_inetnum.to_csv(os.path.join(self.target_dir, 'format', f'ip_inetnum_entity.csv'), index=False)
        if self.enable_DB:
            self.DB_Tool_instance.df_to_DB(df_inetnum, 'ip_inetnum_entity')


        # ip_rdap_entity
        df_rdap = pd.DataFrame()
        rdap_list = self.rir_list
        for rir in rdap_list:
            logger.info(f'正在处理 {rir} 前缀 RDAP 信息')
            df = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_ip_rdap_info.csv',
                             usecols=['CIDR', 'name', 'descr', 'country', 'administrative',
                                      'technical', 'abuse', 'registrant'],
                             dtype=str, keep_default_na=False, na_values=[''])
            df['source'] = rir
            # 去除 IPv6 前缀
            df = df[~df['CIDR'].str.contains(':', na=False)]
            df = df[~df['CIDR'].str.contains('-1', na=False)]
            df = df[df['CIDR'] != '0.0.0.0/0']
            df.rename(columns={'name': 'netname', 'registrant': 'org', 'administrative': 'admin-c',
                               'technical': 'tech-c', 'abuse': 'abuse-c'}, inplace=True)
            df = df[['CIDR', 'netname', 'descr', 'country', 'source', 'admin-c', 'tech-c', 'abuse-c', 'org']]
            df_rdap = pd.concat([df_rdap, df], ignore_index=True)

        def rm_multi(cidr):
            if '|' in cidr:
                cidr = cidr[0:cidr.find('|')]
            return cidr

        df_rdap['CIDR'] = df_rdap['CIDR'].apply(lambda x: np.nan if pd.isna(x) else rm_multi(x))
        df_rdap['org_name'], df_rdap['org_name_cn'], df_rdap['org_uuid'] = \
            zip(*df_rdap['org'].apply(lambda x: handle_org_map.get(x, POINFO())))
        df_rdap['country'] = df_rdap['country'].apply(format_country)
        df_rdap.to_csv(os.path.join(self.target_dir, 'format', f'ip_rdap_entity.csv'), index=False)
        if self.enable_DB:
            self.DB_Tool_instance.df_to_DB(df_rdap, 'ip_rdap_entity')


        # ip_route_entity
        df_route = pd.DataFrame()
        route_list = ['apnic', 'arin', 'ripe', 'afrinic']
        for rir in route_list:
            logger.info(f'正在处理 {rir} route 信息')
            if rir == 'afrinic':
                df = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_route_whois_info.csv',
                                 usecols=['route', 'descr', 'origin', 'source', 'mnt-by'],
                                 dtype=str, keep_default_na=False, na_values=[''])
                df['last-modified'] = pd.Series(dtype=object)
            else:
                df = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_route_whois_info.csv',
                                 usecols=['route', 'descr', 'origin', 'source', 'mnt-by', 'last-modified'],
                                 dtype=str, keep_default_na=False, na_values=[''])
            df.rename(columns={'route': 'CIDR'}, inplace=True)
            df = df[['CIDR', 'descr', 'origin', 'mnt-by', 'last-modified', 'source']]
            # for col in ['descr', 'origin', 'source', 'mnt-by', 'last-modified']:
            #     df[col] = df[col].apply(lambda x: '|'.join(ast.literal_eval(x)) if pd.notna(x) else x)
            df_route = pd.concat([df_route, df], ignore_index=True)
        df_route.drop_duplicates(subset=['CIDR', 'origin'], inplace=True)
        df_route['origin'] = df_route['origin'].str.replace(r'[^|0-9]+', '', regex=True)
        df_route.to_csv(os.path.join(self.target_dir, 'format', f'ip_route_entity.csv'), index=False)
        if self.enable_DB:
            self.DB_Tool_instance.df_to_DB(df_route, 'ip_route_entity')


        # ipv6_inetnum_entity
        df_inet6num = pd.DataFrame()
        inetnum_list = ['apnic', 'ripe', 'afrinic']
        for rir in inetnum_list:
            logger.info(f'正在处理 {rir} 前缀 inet6num 信息')
            if rir != 'afrinic':
                df = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_inet6num_whois_info.csv', 
                                 usecols=['inet6num', 'netname', 'descr', 'country', 'source',
                                          'admin-c', 'tech-c', 'abuse-c', 'org'],
                                 dtype=str, keep_default_na=False, na_values=[''])
                df = df[df['inet6num'] != '::/0']
            else:
                # AFRINIC inet6num 无 abuse-c
                df = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_inet6num_whois_info.csv', 
                                 usecols=['inet6num', 'netname', 'descr', 'country',
                                          'source', 'admin-c', 'tech-c', 'org'],
                                 dtype=str, keep_default_na=False, na_values=[''])
                df = df[df['inet6num'] != '0::/0']
                df['abuse-c'] = pd.Series(dtype=object)
            df.rename(columns={'inet6num': 'CIDR'}, inplace=True)

            # 过滤未分配给该 RIR 或无有效信息的前缀
            if rir == 'apnic':
                df = df[df['CIDR'] != '::/0']
            elif rir == 'ripe':
                df = df[~df['netname'].str.contains('NON-RIPE', case=False, na=False)]
                df = df[df['CIDR'] != '::/0']
            elif rir == 'afrinic':
                df = df[df['CIDR'] != '0::/0']

            df = df[['CIDR', 'netname', 'descr', 'country', 'source', 'admin-c', 'tech-c', 'abuse-c', 'org']]
            # for col in ['netname', 'descr', 'country', 'source', 'admin-c', 'tech-c', 'abuse-c', 'org']:
            #     df[col] = df[col].apply(lambda x: '|'.join(ast.literal_eval(x)) if pd.notna(x) else x)
            df_inet6num = pd.concat([df_inet6num, df], ignore_index=True)

        df_inet6num['org_name'], df_inet6num['org_name_cn'], df_inet6num['org_uuid'] = \
            zip(*df_inet6num['org'].apply(lambda x: handle_org_map.get(x, POINFO())))
        df_inet6num['country'] = df_inet6num['country'].apply(format_country)
        df_inet6num.to_csv(os.path.join(self.target_dir, 'format', f'ipv6_inetnum_entity.csv'), index=False)
        if self.enable_DB:
            self.DB_Tool_instance.df_to_DB(df_inet6num, 'ipv6_inetnum_entity')


        # ipv6_rdap_entity
        df_rdap6 = pd.DataFrame()
        rdap_list = self.rir_list
        for rir in rdap_list:
            logger.info(f'正在处理 {rir} 前缀 RDAP6 信息')
            if rir != 'arin':
                df = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_ip_rdap_info.csv', usecols=['handle',
                                 'name', 'descr', 'country', 'administrative', 'technical', 'abuse', 'registrant'],
                                 dtype=str, keep_default_na=False, na_values=[''])
                df.rename(columns={'handle': 'CIDR'}, inplace=True)
            else:
                df = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_ip_rdap_info.csv', usecols=['CIDR',
                                 'name', 'descr', 'country', 'administrative', 'technical', 'abuse', 'registrant'],
                                 dtype=str, keep_default_na=False, na_values=[''])
            df.dropna(subset=['CIDR'], inplace=True)
            df['source'] = rir
            # 去除 IPv4 前缀
            df = df[df['CIDR'].str.contains(':', na=False)]
            df = df[df['CIDR'] != '::/0']
            df.rename(columns={'name': 'netname', 'registrant': 'org', 'administrative': 'admin-c',
                               'technical': 'tech-c', 'abuse': 'abuse-c'}, inplace=True)
            df = df[['CIDR', 'netname', 'descr', 'country', 'source', 'admin-c', 'tech-c', 'abuse-c', 'org']]
            df_rdap6 = pd.concat([df_rdap6, df], ignore_index=True)

        df_rdap6.drop_duplicates(subset=['CIDR'], inplace=True)
        df_rdap6['org_name'], df_rdap6['org_name_cn'], df_rdap6['org_uuid'] = \
            zip(*df_rdap6['org'].apply(lambda x: handle_org_map.get(x, POINFO())))
        df_rdap6['country'] = df_rdap6['country'].apply(format_country)
        df_rdap6.to_csv(os.path.join(self.target_dir, 'format', f'ipv6_rdap_entity.csv'),
                       columns=['CIDR', 'netname', 'descr', 'country', 'source', 'admin-c', 'tech-c',
                                'abuse-c', 'org', 'org_name', 'org_name_cn', 'org_uuid'], index=False)
        if self.enable_DB:
            self.DB_Tool_instance.df_to_DB(df_rdap6, 'ipv6_rdap_entity')


        # ipv6_route_entity
        df_route6 = pd.DataFrame()
        route_list = ['apnic', 'arin', 'ripe', 'afrinic']
        for rir in route_list:
            logger.info(f'正在处理 {rir} route6 信息')
            if rir == 'afrinic':
                df = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_route6_whois_info.csv',
                                 usecols=['route6', 'descr', 'origin', 'source', 'mnt-by'],
                                 dtype=str, keep_default_na=False, na_values=[''])
                df['last-modified'] = pd.Series(dtype=object)
            else:
                df = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_route6_whois_info.csv',
                                 usecols=['route6', 'descr', 'origin', 'source', 'mnt-by', 'last-modified'],
                                 dtype=str, keep_default_na=False, na_values=[''])
            df.rename(columns={'route6': 'CIDR'}, inplace=True)
            df = df[['CIDR', 'descr', 'origin', 'mnt-by', 'last-modified', 'source']]
            # for col in ['descr', 'origin', 'source', 'mnt-by', 'last-modified']:
            #     df[col] = df[col].apply(lambda x: '|'.join(ast.literal_eval(x)) if pd.notna(x) else x)
            df_route6 = pd.concat([df_route6, df], ignore_index=True)
        df_route6.drop_duplicates(subset=['CIDR', 'origin'], inplace=True)
        df_route6['origin'] = df_route6['origin'].str.replace(r'[^|0-9]+', '', regex=True)
        df_route6.to_csv(os.path.join(self.target_dir, 'format', f'ipv6_route_entity.csv'), index=False)
        if self.enable_DB:
            self.DB_Tool_instance.df_to_DB(df_route6, 'ipv6_route_entity')
