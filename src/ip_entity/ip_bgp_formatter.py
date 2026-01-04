from src.utils.logging_manager import logger
from src import BaseEntity

import os
import re
import ast
import json
import pytricia
import ipaddress
import pandas as pd
from IPy import IP
from collections import namedtuple


class IPBGPFormatter(BaseEntity):
    def __init__(self, date: str, config_path='conf/config.yaml', enable_DB=True):
        '''
        IP 地址前缀路由实体格式化工具

        Parameters:

            date - 日期，格式为 YYYY-MM-DD。请注意，本类将根据该日期读取相应的数据文件（包括但不限于 RIR 文件等），因此可能需要根据数据需求自行更改而不是直接使用当前日期。

            config_path - 配置文件路径

            enable_DB - 是否启用数据库

        '''
        super().__init__(config_path, date, enable_DB)

    def run(self):
        if not os.path.isfile(os.path.join(self.target_dir, 'format', f'as_entity_{self.date}.csv')):
            logger.error('未找到 AS 实体数据，请先运行 as_entity_formatter.py 或检查 date 配置')
            return
        if not os.path.isfile(os.path.join(self.target_dir, 'format', f'website_entity_base.csv')):
            logger.error('未找到网站服务实体数据，请先运行 dns_entity_formatter.py')
            return

        file_list = [re.sub('[^-0-9]', '', f) for f in os.listdir(os.path.join(self.target_dir, 'format'))
                     if f.startswith('rib_data') and f.endswith('.csv')]
        latest = sorted(file_list, key=lambda x: tuple(x.split('-')), reverse=True)[1]
        rib_data_filepath = os.path.join(self.target_dir, 'format', f'rib_data_{latest}.csv')

        def format_rib(df):
            df['prefix'] = df['prefix'].apply(lambda x: ast.literal_eval(x) if pd.notna(x) else None)
            # df['bgp'] = df['bgp'].apply(lambda x: str(x) if pd.notna(x) else x)
            df_bgp = df[['prefix', 'bgp']].explode('prefix')
            def format_addr(addr):
                try:
                    IP(addr)
                    return addr
                except:
                    return None
            df_bgp['prefix'] = df_bgp['prefix'].apply(lambda x: format_addr(x) if pd.notna(x) else None)
            return df_bgp

        rib_filepath = os.path.join(self.target_dir, 'format', 'rib_prefix_base.csv')
        if os.path.isfile(rib_data_filepath):
            logger.info(f'开始加载 RIB 数据文件 {rib_data_filepath}')
            df = pd.read_csv(rib_data_filepath, usecols=['v4Prefixes', 'asn'], dtype=str) \
                .dropna().replace('nan', None).rename(columns={'v4Prefixes':'prefix', 'asn':'bgp'})
            df_bgp = format_rib(df)
        elif os.path.isfile(rib_filepath):
            logger.info(f'开始加载 RIB 数据文件 {rib_filepath}')
            df_bgp = pd.read_csv(rib_filepath, dtype=str)
            df_bgp.rename(columns={'as': 'bgp'}, inplace=True)
        else:
            logger.error('未找到 RIB 数据，请等待 rib_data 数据或先运行 rib_formatter.py')
            return

        if len(df_bgp) > 800000:
            df_bgp = df_bgp[df_bgp['prefix'] != '0.0.0.0/0']
            df_bgp.drop_duplicates(subset=['prefix'], ignore_index=True, inplace=True)
            df_bgp['prefix_len'] = df_bgp['prefix'].apply(lambda x: x[x.find('/')+1:])
            df_bgp.drop_duplicates(inplace=True)
            df_bgp = self.__origin_as_info(df_bgp)
            df_bgp = self.__name_descr_info(df_bgp)
            df_bgp = self.__admin_org_info(df_bgp)
            df_bgp = df_bgp[['prefix', 'prefix_len', 'name', 'descr', 'route', 'bgp',
                            'admin_prefix', 'admin_route', 'admin_bgp',
                            'org_handle_prefix', 'org_name_prefix', 'org_name_cn_prefix', 'org_uuid_prefix',
                            'org_handle_bgp', 'org_name_bgp', 'org_name_cn_bgp', 'org_uuid_bgp',
                            'country', 'source', 'date', 'inetnum', 'rdap']]
            df_bgp = self.__rpki_info(df_bgp)
            df_bgp = self.__domain_auth_info(df_bgp)
            logger.info('开始导出 IPv4 地址前缀路由实体信息')
            df_bgp.to_csv(os.path.join(self.target_dir, 'format', f'ip_bgp_entity_{self.date}.csv'), index=False)
            df_bgp.to_csv(os.path.join(self.target_dir, 'format', f'ip_bgp_entity.csv'), index=False,
                        columns=['prefix', 'name', 'descr', 'route', 'bgp', 'admin_prefix', 'admin_route', 'admin_bgp',
                                'org_handle_prefix', 'org_name_prefix', 'org_handle_bgp', 'org_name_bgp',
                                'country', 'source', 'domain', 'domain_num', 'domain_auth', 'domain_auth_num'])
            if self.enable_DB:
                self.__to_postgres(df_bgp)
            logger.info('IPv4 地址前缀路由实体信息处理导出完成')
        else:
            logger.error('RIB 数据 IPv4 路由前缀条数不足 800,000，放弃 IPv4 路由实体格式化')

        rib_filepath = os.path.join(self.target_dir, 'format', 'rib_v6_prefix_base.csv')
        if os.path.isfile(rib_data_filepath):
            logger.info(f'开始加载 RIB 数据文件 {rib_data_filepath}')
            df = pd.read_csv(rib_data_filepath, usecols=['v6Prefixes', 'asn'], dtype=str) \
                .dropna().replace('nan', None).rename(columns={'v6Prefixes':'prefix', 'asn':'bgp'})
            df_bgp = format_rib(df)
        elif os.path.isfile(rib_filepath):
            logger.info(f'开始加载 IPv6 RIB 数据文件 {rib_filepath}')
            df_bgp = pd.read_csv(rib_filepath, dtype=str)
            df_bgp.rename(columns={'as': 'bgp'}, inplace=True)
        else:
            logger.error('未找到 IPv6 RIB 数据，请等待 rib_data 数据或先运行 rib_formatter.py')
            return

        if len(df_bgp) > 150000:
            df_bgp = df_bgp[df_bgp['prefix'] != '::/0']
            df_bgp.drop_duplicates(subset=['prefix'], ignore_index=True, inplace=True)
            df_bgp['prefix_len'] = df_bgp['prefix'].apply(lambda x: x[x.find('/')+1:])
            df_bgp = self.__origin_as_info(df_bgp, v6=True)
            df_bgp = self.__name_descr_info(df_bgp, v6=True)
            df_bgp = self.__admin_org_info(df_bgp)
            df_bgp = df_bgp[['prefix', 'prefix_len', 'name', 'descr', 'route', 'bgp',
                            'admin_prefix', 'admin_route', 'admin_bgp',
                            'org_handle_prefix', 'org_name_prefix', 'org_name_cn_prefix', 'org_uuid_prefix',
                            'org_handle_bgp', 'org_name_bgp', 'org_name_cn_bgp', 'org_uuid_bgp',
                            'country', 'source', 'date', 'inetnum', 'rdap']]
            df_bgp = self.__rpki_info(df_bgp, v6=True)
            logger.info('开始导出 IPv6 地址前缀路由实体信息')
            df_bgp.to_csv(os.path.join(self.target_dir, 'format', f'ipv6_bgp_entity_{self.date}.csv'), index=False)
            if self.enable_DB:
                self.__to_postgres(df_bgp, v6=True)
            logger.info('IPv6 地址前缀路由实体信息处理导出完成')
        else:
            logger.error('RIB 数据 IPv6 路由前缀条数不足 150,000，放弃 IPv6 路由实体格式化')

    def __origin_as_info(self, df_bgp: pd.DataFrame, v6: bool = False) -> pd.DataFrame:
        '''
        获取注册归属 AS 信息

        Parameters:

            df_bgp - 路由前缀与路由归属 AS 信息

        Returns:

            pd.DataFrame - 增加注册归属 AS 后的前缀信息

        '''
        logger.info('开始加载注册归属 AS 信息')
        pyt_origin = pytricia.PyTricia() if not v6 else pytricia.PyTricia(128)
        for rir in self.rir_list:
            if rir != 'lacnic':
                # LACNIC 无 route_whois 数据
                df = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_route_whois_info.csv',
                                 usecols=['route', 'origin'], dtype=str) if not v6 else \
                     pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_route6_whois_info.csv',
                                 usecols=['route6', 'origin'], dtype=str)
            if rir == 'arin' or rir == 'lacnic':
                # ARIN 与 LACNIC 有 rdap 数据
                ip = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_ip_rdap_info.csv',
                                 usecols=['CIDR', 'originAS'], dtype=str)
                # 去除 IPv6/4 前缀
                if not v6:
                    ip = ip[~ip['CIDR'].str.contains(':', na=False)]
                    ip.rename(columns={'CIDR': 'route', 'originAS': 'origin'}, inplace=True)
                else:
                    ip = ip[ip['CIDR'].str.contains(':', na=False)]
                    ip.rename(columns={'CIDR': 'route6', 'originAS': 'origin'}, inplace=True)
                ip = ip[ip['origin'].notna()]
                # ARIN 既有 route_whois 数据又有 rdap 数据，合并
                df = pd.concat([df, ip], ignore_index=True) if rir == 'arin' else ip
            for prefix, asn in zip(df['route'] if not v6 else df['route6'], df['origin']):
                # 以注册/归属数据前缀建立前缀树
                if pd.notna(asn):
                    try:
                        if pyt_origin.has_key(prefix):
                            # route_whois 中存在多条相同前缀对应不同 AS
                            # 若该前缀已有对应 AS，追加 '|' 分隔后重新插入
                            origin = pyt_origin.get(prefix)
                            if not set(asn.split('|')).issubset(set(origin.split('|'))):
                                origin += '|' + asn
                        else:
                            origin = asn
                        pyt_origin[prefix] = origin
                    except:
                        continue

        logger.info('开始处理注册归属 AS 信息')
        df_bgp['route'] = df_bgp['prefix'].apply(pyt_origin.get)

        # route_whois 与 rdap 中存在 ['ASxx']、ASxx、asxx 等多种格式，去除数字、分隔符以外的字符
        df_bgp['route'] = df_bgp['route'].str.replace(r'[^|0-9]+', '', regex=True)
        return df_bgp

    def __name_descr_info(self, df_bgp: pd.DataFrame, v6: bool = False) -> pd.DataFrame:
        '''
        获取网络名称、描述、国家、归属源信息，同时获取前缀对应管理人与组织机构信息

        Parameters:

            df_bgp - 路由前缀与归属 AS 信息

        Returns:

            pd.DataFrame - 增加网络名称、描述、国家、归属源等后的前缀信息

        '''
        PINFO = namedtuple('PINFO', ['name', 'descr', 'admin', 'org'])
        PINFO.__new__.__defaults__ = (None,) * len(PINFO._fields)

        logger.info('开始加载 inetnum 前缀分配信息')
        pyt_inetnum = pytricia.PyTricia() if not v6 else pytricia.PyTricia(128)
        inetnum_list = ['apnic', 'ripe', 'afrinic']
        for rir in inetnum_list:
            if rir != 'afrinic':
                df = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_inetnum_whois_info.csv', 
                                 usecols=['CIDR', 'netname', 'descr', 'admin-c', 'org'],
                                 dtype=str, keep_default_na=False, na_values=['']) if not v6 else \
                     pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_inet6num_whois_info.csv', 
                                 usecols=['inet6num', 'netname', 'descr', 'admin-c', 'org'],
                                 dtype=str, keep_default_na=False, na_values=[''])
            else:
                # AFRINIC inetnum 无 CIDR 字段，需由 IP 地址范围转换得到；inet6num 无 netname 字段
                if not v6:
                    df = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_inetnum_whois_info.csv', 
                                    usecols=['inetnum', 'netname', 'descr', 'admin-c', 'org'],
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
                else:
                    df = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_inet6num_whois_info.csv', 
                                     usecols=['inet6num', 'descr', 'admin-c', 'org'],
                                     dtype=str, keep_default_na=False, na_values=[''])
                    df['netname'] = pd.Series(dtype=object)

            # 过滤未分配给该 RIR 或无有效信息的前缀
            df = df[df['CIDR'] != '0.0.0.0/0'] if not v6 else df[~df['inet6num'].str.contains('::/0', na=False)]
            if rir == 'apnic':
                df = df[~df['descr'].str.contains('|'.join([
                    'not allocated', 'not fully allocated', 'early registration']), case=False, na=False)]
            elif rir == 'ripe':
                df = df[~df['netname'].str.contains('NON-RIPE', case=False, na=False)]
                df['admin-c'] = df['admin-c'].replace({"['DUMY-RIPE']": None})
            elif rir == 'afrinic':
                df = df[~df['descr'].str.contains('|'.join([
                    'This block is allocated', 'Allocation for Africa']), case=False, na=False)]

            # 将列表格式转为 | 分隔格式
            # for column in ['netname', 'descr', 'admin-c', 'org']:
            #     df[column] = df[column].apply(lambda x: '|'.join(ast.literal_eval(x)) if pd.notna(x) else x)

            # 建立前缀树
            for cidr, name, descr, admin, org in zip(
                df['CIDR'] if not v6 else df['inet6num'], df['netname'], df['descr'], df['admin-c'], df['org']):
                try:
                    pyt_inetnum[cidr] = PINFO(name, descr, admin, org)
                except:
                    continue

        logger.info('开始加载 RDAP 前缀分配信息')
        pyt_rdap = pytricia.PyTricia() if not v6 else pytricia.PyTricia(128)
        for rir in self.rir_list:
            df = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_ip_rdap_info.csv',
                            usecols=['CIDR', 'descr', 'name', 'administrative', 'registrant'],
                            dtype=str, keep_default_na=False, na_values=[''])
            # 去除 IPv6/4 与 0.0.0.0, ::/0 前缀
            df = df[~df['CIDR'].str.contains(':', na=False)] if not v6 else \
                 df[df['CIDR'].str.contains(':', na=False)]
            df = df[df['CIDR'] != '0.0.0.0/0'] if not v6 else df[df['CIDR'] != '::/0']
            for cidr, name, descr, admin, org in zip(
                df['CIDR'], df['name'], df['descr'], df['administrative'], df['registrant']):
                try:
                    # 处理使用 '|' 分隔的存在多种 CIDR 表示的前缀
                    if not v6 and '|' in cidr:
                        cidr = cidr[0:cidr.find('|')]
                    pyt_rdap[cidr] = PINFO(name, descr, admin, org)
                except:
                    continue

        # 合并 inetnum 与 rdap 数据，优先选择 inetnum
        def get_pinfo(prefix):
            inet = pyt_inetnum.get(prefix)
            rdap = pyt_rdap.get(prefix)
            if inet is None:
                if rdap is None:
                    return PINFO()
                else:
                    return rdap
            else:
                if rdap is None:
                    return inet
                else:
                    return PINFO(inet.name if inet.name else rdap.name,
                                 inet.descr if inet.descr else rdap.descr,
                                 inet.admin if inet.admin else rdap.admin,
                                 inet.org if inet.org else rdap.org,)

        logger.info('开始处理前缀分配基本信息')
        df_bgp['name'], df_bgp['descr'], df_bgp['admin_prefix'], df_bgp['org_handle_prefix'] = \
            zip(*df_bgp['prefix'].apply(get_pinfo))
        df_bgp['inetnum'] = df_bgp['prefix'].apply(pyt_inetnum.get_key)
        df_bgp['rdap'] = df_bgp['prefix'].apply(pyt_rdap.get_key)

        DINFO = namedtuple('DINFO', ['source', 'country', 'date'])
        DINFO.__new__.__defaults__ = (None,) * len(DINFO._fields)

        logger.info('开始加载 IANA 委托 IPv4/IPv6 信息')
        delegate = 'ipv4.csv' if not v6 else 'ipv6.csv'
        ip = pd.read_csv(f'{self.format_dir}{self.date}/{delegate}',
                           usecols=['prefix', 'source', 'country', 'date'],
                           dtype=str, keep_default_na=False, na_values=[''])
        pyt = pytricia.PyTricia() if not v6 else pytricia.PyTricia(128)
        if not v6:
            pyt['0.0.0.0/0'] = DINFO()
        else:
            pyt['::/0'] = DINFO()
        for prefix, source, country, date in zip(
            ip['prefix'], ip['source'], ip['country'], ip['date']):
            pyt[prefix] = DINFO('ripe' if source == 'ripencc' else source, country, date)
        logger.info('开始处理国家、来源与日期信息')
        df_bgp['source'], df_bgp['country'], df_bgp['date'] = zip(*df_bgp['prefix'].apply(pyt.get))

        return df_bgp

    def __admin_org_info(self, df_bgp: pd.DataFrame) -> pd.DataFrame:
        '''
        获取管理人、组织机构信息，并使用组织机构补充前缀描述

        Parameters:

            df_bgp - 路由前缀与分配信息

        Returns:

            pd.DataFrame - 增加管理人、组织机构后的前缀信息

        '''
        logger.info('开始加载 AS 实体信息')
        ase = pd.read_csv(os.path.join(self.target_dir, 'format', f'as_entity_{self.date}.csv'),
                          usecols=['asn', 'administrative', 'org_handle', 'org_name', 'org_name_cn', 'uuid'],
                          dtype=str, keep_default_na=False, na_values=[''])
        # AS/管理人映射
        as_admin_map = {}
        # AS/组织机构映射，用于路由归属 AS 组织机构信息
        AOINFO = namedtuple('AOINFO', ['handle', 'name', 'name_cn', 'uuid'])
        AOINFO.__new__.__defaults__ = (None,) * len(AOINFO._fields)
        as_org_map = {}
        # handle/组织机构映射，用于路由前缀组织机构信息
        POINFO = namedtuple('POINFO', ['name', 'name_cn', 'uuid'])
        POINFO.__new__.__defaults__ = (None,) * len(POINFO._fields)
        handle_org_map = {}
        for asn, admin, handle, name, name_cn, uuid in zip(ase['asn'], ase['administrative'], ase['org_handle'],
                                                           ase['org_name'], ase['org_name_cn'], ase['uuid']):
            if pd.notna(admin):
                as_admin_map[asn] = admin
            as_org_map[asn] = AOINFO(handle, name, name_cn, uuid)
            if pd.notna(handle):
                handle_org_map[handle] = POINFO(name, name_cn, uuid)

        logger.info('开始加载 IANA 委托 AS 信息')
        asn = pd.read_csv(f'{self.format_dir}{self.date}/asn.csv', usecols=['asn', 'opq_id'], dtype=str)
        # 建立组织机构 ID/AS 映射
        id_as_map = {}
        for asn, opq_id in zip(asn['asn'], asn['opq_id']):
            if opq_id not in id_as_map:
                id_as_map[opq_id] = {asn}
            else:
                id_as_map[opq_id].add(asn)

        logger.info('开始处理归属 AS 管理人信息')
        def get_admin(route):
            if '|' in route:
                # 对多个注册归属 AS 对应的管理人使用列表 ['...'] 表示
                # 对单个注册归属 AS 对应的管理人使用字符串 '...' 表示
                # 一个 AS 对应的管理人信息存在使用 '|' 分隔的情况
                # 例如 34164|20940 -> "['NARA1-RIPE', 'APB15-RIPE|NARA1-RIPE|NB782-RIPE']"
                l = [as_admin_map.get(r, '') for r in route.split('|')]
                return l if any(x != l[0] for x in l) else None
            else:
                return as_admin_map.get(route, None)
        df_bgp['admin_route'] = df_bgp['route'].apply(lambda x: get_admin(x) if pd.notna(x) else x)
        df_bgp['admin_bgp'] = df_bgp['bgp'].apply(lambda x: as_admin_map.get(x, None) if pd.notna(x) else x)

        logger.info('开始处理组织机构信息')
        # 路由归属 AS 由映射得到组织机构
        df_bgp['org_handle_bgp'], df_bgp['org_name_bgp'], df_bgp['org_name_cn_bgp'], df_bgp['org_uuid_bgp'] = \
            zip(*df_bgp['bgp'].apply(lambda x: as_org_map.get(x, AOINFO())))
        # 路由前缀由 handle 得到组织机构
        df_bgp['org_name_prefix'], df_bgp['org_name_cn_prefix'], df_bgp['org_uuid_prefix'] = \
            zip(*df_bgp['org_handle_prefix'].apply(lambda x: handle_org_map.get(x, POINFO())))

        logger.info('开始完善前缀描述信息')
        def format_descr(descr, org, route):
            # 描述缺失或为无效 spam/abuse 类联系说明
            if (pd.isna(descr) or
                (descr.startswith('-----BEGIN CERTIFICATE-----')) or
                ('Dynamic IP Address'.lower() in descr.lower()) or
                ('NON-PORTABLE'.lower() in descr.lower()) or
                ('NOT PORTABLE'.lower() in descr.lower()) or
                ((('spam' in descr.lower()) or ('abuse' in descr.lower())) and descr.lower().startswith((
                    '_', '|', '*', '=', '#', ':', '-', 'please ', 'for ', 'http', 'see ', 'contact ', 'use ', 'used', 'report ',
                    'abuse', 'all ', 'the ', 'this ', 'technical ', 'law ', 'send ', 'routing ', 'in ', 'to ', 'if ', 'geofeed ')))
                ):
                # 使用前缀组织机构名或注册归属 AS 组织机构名补全
                return org if pd.notna(org) else as_org_map.get(route, AOINFO()).name
            return descr
        df_bgp['descr'] = [format_descr(descr, org, route) for descr, org, route
                           in zip(df_bgp['descr'], df_bgp['org_name_prefix'], df_bgp['route'])]

        return df_bgp

    def __rpki_info(self, df_bgp: pd.DataFrame, v6: bool = False) -> pd.DataFrame:
        '''
        获取 RPKI 验证信息

        Parameters:

            df_bgp - 路由前缀信息

        Returns:

            pd.DataFrame - 增加 RPKI 后的前缀信息

        '''
        ROA = namedtuple('ROA', ['asn', 'maxLength'])

        logger.info('开始加载路由源验证信息')
        try:
            with open(os.path.join(self.target_dir, 'format', f'roa.json')) as f:
                d = json.load(f)
                if not v6:
                    roas = [roa for roa in d['roas'] if ':' not in roa['prefix']]
                else:
                    roas = [roa for roa in d['roas'] if ':' in roa['prefix']]
        except:
            roas = []

        pyt = pytricia.PyTricia() if not v6 else pytricia.PyTricia(128)
        for roa in roas:
            r = ROA(roa['asn'][2:], roa['maxLength'])
            if pyt.has_key(roa['prefix']):
                pyt[roa['prefix']].append(r)
            else:
                pyt[roa['prefix']] = [r]

        def validity(prefix, asn):
            roas = pyt.get(prefix)
            if roas is not None:
                length = int(prefix[prefix.find('/')+1:])
                for roa in roas:
                    if length <= roa.maxLength and asn == roa.asn:
                        return 'valid'
                return 'invalid'
            return 'unknown'

        logger.info('开始处理 RPKI 信息')
        df_bgp['rpki'] = [validity(prefix, bgp) for prefix, bgp in zip(df_bgp['prefix'], df_bgp['bgp'])]
        return df_bgp

    def __domain_auth_info(self, df_bgp: pd.DataFrame) -> pd.DataFrame:
        '''
        获取网站服务信息

        Parameters:

            df_bgp - 路由前缀与分配信息

        Returns:

            pd.DataFrame - 增加管理人、组织机构后的前缀信息

        '''
        logger.info('开始建立路由前缀树')
        pyt = pytricia.PyTricia()
        df_bgp.reset_index(drop=True, inplace=True)
        for index, prefix in df_bgp['prefix'].items():
            pyt[prefix] = index

        logger.info('开始加载网站服务实体信息')
        website = pd.read_csv(os.path.join(self.target_dir, 'format', f'website_entity_base.csv'), 
                              usecols=['url', 'ip', 'auth_ip'], sep=';', dtype=str,
                              keep_default_na=False, na_values=[''])
        website = pd.concat([pd.read_csv(os.path.join(self.target_dir, 'format', f'domain_cn.csv'),
                                         usecols=['url', 'ip', 'auth_ip'], dtype=str), website])
        website.drop_duplicates(subset=['url'], inplace=True)
        def format_ip(addrs):
            if pd.notna(addrs):
                addrs = ast.literal_eval(addrs)
                l = []
                for addr in addrs:
                    try:
                        ipaddress.IPv4Address(addr)
                        l.append(addr)
                    except:
                        continue
                return l if l else None
        website['ip'] = website['ip'].apply(format_ip)
        website['auth_ip'] = website['auth_ip'].apply(format_ip)
        # 建立IP/域名列表映射、权威IP/域名列表映射
        ix_ip_map = [set() for i in range(len(df_bgp))]
        ix_auth_map = [set() for i in range(len(df_bgp))]
        for url, ip, auth_ip in zip(website['url'], website['ip'], website['auth_ip']):
            if ip:
                for addr in ip:
                    ix = pyt.get(addr)
                    if ix is not None:
                        ix_ip_map[ix].add(url)
            if auth_ip:
                for addr in auth_ip:
                    ix = pyt.get(addr)
                    if ix is not None:
                        ix_auth_map[ix].add(url)

        logger.info('开始处理网站服务信息')
        df_bgp['domain'] = ix_ip_map
        df_bgp['domain_num'] = df_bgp['domain'].apply(len)
        df_bgp['domain'] = df_bgp['domain'].apply(lambda x: list(x) if x else None)
        df_bgp['domain_auth'] = ix_auth_map
        df_bgp['domain_auth_num'] = df_bgp['domain_auth'].apply(len)
        df_bgp['domain_auth'] = df_bgp['domain_auth'].apply(lambda x: list(x) if x else None)

        return df_bgp

    def __to_postgres(self, df_bgp: pd.DataFrame, v6: bool = False) -> pd.DataFrame:
        '''
        IP 路由前缀 DataFrame 写入 PostgreSQL 数据库

        Parameters:

            df_bgp - 路由前缀信息

        Returns:

            pd.DataFrame - 路由前缀信息

        '''
        logger.info('开始导入数据库')
        # 注册归属 AS 字段 | 分隔字符串转为整数列表，其管理人字段转为列表
        df_bgp['route'] = df_bgp['route'].apply(
            lambda x: [int(i) for i in x.split('|')] if pd.notna(x) else [])
        df_bgp['admin_route'] = df_bgp['admin_route'].apply(
            lambda x: ([x] if pd.notna(x) else []) if not isinstance(x, list) else x)
        # 打包注册归属 AS 列表与对应的管理人列表， 转为字典 json
        df_bgp['admin_route'] = [json.dumps(dict(zip(k, v))) for k, v in zip(df_bgp['route'], df_bgp['admin_route'])]
        # 将空列表 [] 与空字典 json {} 替换为 None
        df_bgp['route'] = df_bgp['route'].apply(lambda x: x if x else None)
        df_bgp['admin_route'] = df_bgp['admin_route'].apply(lambda x: x if len(x) > 2 else None)
        # 自动推导并转换数据类型
        df_bgp = df_bgp.convert_dtypes()
        # 写入数据库并建立前缀索引
        if not v6:
            self.DB_Tool_instance.df_to_DB(df_bgp, 'ip_bgp_entity', ctype={'prefix':'cidr', 'prefix_len':'integer',
                'route':'bigint[]', 'bgp':'bigint', 'admin_route':'json', 'domain':'text[]', 'domain_num':'integer',
                'domain_auth':'text[]', 'domain_auth_num':'integer'}, primary=['prefix', 'bgp'])
            self.DB_Tool_instance.query_by_sql('CREATE INDEX IF NOT EXISTS ip_bgp_entity_idx ON ip_bgp_entity (prefix);')
        else:
            self.DB_Tool_instance.df_to_DB(df_bgp, 'ipv6_bgp_entity', ctype={'prefix':'cidr', 'prefix_len':'integer',
                'route':'bigint[]', 'bgp':'bigint', 'admin_route':'json'}, primary=['prefix', 'bgp'])
            self.DB_Tool_instance.query_by_sql('CREATE INDEX IF NOT EXISTS ipv6_bgp_entity_idx ON ipv6_bgp_entity (prefix);')

        return df_bgp
