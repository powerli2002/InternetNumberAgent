from fusiondata.src.utils.logging_manager import logger
from fusiondata.src import BaseEntity

import os
import re
import ast
import pytricia
import ipaddress
import numpy as np
import pandas as pd


class IndustryEntityFormatter(BaseEntity):
    def __init__(self, date: str, config_path='conf/config.yaml', enable_DB=True):
        super().__init__(config_path, date, enable_DB)
    
    def run(self):
        def name(domain):
            top_level = {'com', 'org', 'net', 'int', 'edu', 'gov', 'mil', 'arpa'}
            country_code = {'cn', 'tw', 'hk', 'mo'}
            labels = domain.split('.')
            if len(labels) < 3:
                name = domain
            elif labels[-1] in country_code and labels[-2] in top_level:
                name = '.'.join(labels[-3:])
            else:
                name = '.'.join(labels[-2:])
            return name

        logger.info('读取域名信息')
        d = pd.read_csv(os.path.join(self.target_dir, 'format', 'domain_cn.csv'), usecols=['url', 'title', 'industry', 'description', 'key', 'ip', 'auth_ip'], dtype=str)
        d = d[d['url'].notna()]
        d = d[d['title'].notna()]
        im = dict()
        for u, i in zip(d['url'], d['industry']):
            if i is not None:
                im[name(u)] = i

        logger.info('读取子域名信息')
        f = [re.sub('[^-0-9]', '', filename) for filename in os.listdir(os.path.join(self.target_dir, 'format')) if filename.startswith('resolve_result')]
        latest = sorted(f, key=lambda x: tuple(x.split('-')), reverse=True)[1]
        r = pd.read_csv(os.path.join(self.target_dir, 'format', f'resolve_result_{latest}.csv'), dtype=str)
        r = r[r['url'].notna()]
        r = r[r['title'].notna()]
        km = dict()
        for u, k in zip(r['url'], r['key']):
            km[u] = k

        d['k'] = d.apply(lambda x: x['key'] if pd.notna(x['key']) else km.get(x['url'], None), axis=1)
        d.drop(columns=['key'], axis=1, inplace=True)
        d.rename(columns={'k': 'key'}, inplace=True)

        def gi(u):
            i = im.get(u, None)
            if i is not None:
                return i

            m = name(u)
            i = im.get(m, None)
            if i is not None:
                return i

            w = 'www.' + m
            i = im.get(w, None)
            if i is not None:
                return i
            
            return None

        r['industry'] = r['url'].apply(gi)

        o = pd.concat([d, r])
        o.drop_duplicates(subset=['url'], inplace=True)
        o = o[~o['url'].str.contains(r'[\u4e00-\u9FFF]', regex=True)]
        o.replace(to_replace=[r'\\t|\\n|\\r', '\t|\n|\r'], value=['',''], regex=True, inplace=True)

        s = set(o['url'])

        def p(u):
            m = name(u)
            if m == u or len(m) >= len(u):
                return None
            if m in s:
                return m
            w = 'www.' + m
            if w == u:
                return None
            if w in s:
                return w
            return None

        o['parent'] = o['url'].apply(p)

        logger.info('读取 IP 路由实体与 AS 实体信息')
        pyt = pytricia.PyTricia()
        bgp = pd.read_csv(os.path.join(self.target_dir, 'format', f'ip_bgp_entity_{self.date}.csv'), usecols=['prefix', 'bgp'], dtype={'prefix':str, 'bgp':int})
        for prefix, asn in zip(bgp['prefix'], bgp['bgp']):
            pyt[prefix] = (prefix, asn)

        ase = pd.read_csv(os.path.join(self.target_dir, 'format', f'as_entity_{self.date}.csv'), usecols=['asn', 'org_name'], dtype={'asn':int, 'org_name':str})
        aom = dict(zip(ase['asn'], ase['org_name']))

        def format(addrs):
            if not addrs:
                return None
            addrs = ast.literal_eval(addrs)
            s = set()
            for addr in addrs:
                try:
                    ipaddress.IPv4Address(addr)
                    s.add(addr)
                except:
                    continue
            return list(s) if s else None
        def prefixes(addrs):
            if not addrs:
                return None
            s = set()
            for addr in addrs:
                try:
                    i = pyt.get(addr)
                    if pd.notna(i):
                        s.add(i[0])
                except:
                    continue
            return list(s) if s else None
        def bgps(addrs):
            if not addrs:
                return None
            s = set()
            for addr in addrs:
                try:
                    i = pyt.get(addr)
                    if pd.notna(i):
                        s.add(i[1])
                except:
                    continue
            return list(s) if s else None

        logger.info('开始处理域名对应前缀与 AS 信息')
        o.replace({np.nan: None}, inplace=True)
        o['ip'] = o['ip'].apply(format)
        o['auth_ip'] = o['auth_ip'].apply(format)
        o['ip_prefix'] = o['ip'].apply(prefixes)
        o['ip_asn'] = o['ip'].apply(bgps)
        o['auth_ip_prefix'] = o['auth_ip'].apply(prefixes)
        o['auth_ip_asn'] = o['auth_ip'].apply(bgps)

        def atoo(asns):
            if not asns:
                return None
            s = set()
            for asn in asns:
                a = aom.get(asn, None)
                if pd.notna(a):
                    s.add(a)
            return list(s) if s else None

        o['ip_org'] = o['ip_asn'].apply(atoo)
        o['auth_ip_org'] = o['auth_ip_asn'].apply(atoo)

        logger.info('导出行业实体数据')
        o = o[['url', 'parent', 'title', 'industry', 'description', 'key', 'ip', 'ip_prefix', 'ip_asn', 'ip_org', 'auth_ip', 'auth_ip_prefix', 'auth_ip_asn', 'auth_ip_org']]
        o.to_csv(os.path.join(self.target_dir, 'format', f'industry_entity_{self.date}.csv'), index=False)
