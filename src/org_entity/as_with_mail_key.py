import pandas as pd
import os
from ast import literal_eval

import tld
from tqdm import tqdm

from src import BaseEntity
from src.utils.logging_manager import logger


def unique_list(x: pd.Series):
    if x.empty:
        return None
    return list(x.dropna().unique())


def unique_set(x: pd.Series):
    if x.empty:
        return None
    res = set()
    for i in x.values:
        if isinstance(i, list):
            target_list = [j.lower() for j in i if pd.notna(j)]
            res.update(target_list)
    return list(res)


def mail_set(x, tld_set: set):
    if not isinstance(x, list):
        return None
    res = set()
    for i in x:
        if pd.notna(i):
            temp = i.lower()
            if temp.startswith('@'):
                temp = temp[1:]
            tld_obj = tld.get_tld(temp, fix_protocol=True, as_object=True, fail_silently=True)
            if tld_obj is None:
                # print(temp)
                res.update(temp.split('.'))
            else:
                res.update(tld_obj.domain.split('.'))
                res.update(tld_obj.subdomain.split('.'))
    res = res.difference(tld_set)
    return res


def slove_org(x):
    if not x or pd.isna(x):
        return None
    elif '|' in x:
        sp_list = x.split('|')
        for sp in sp_list:
            if sp.startswith('ORG-'):
                return sp
    else:
        return x


def slove_contact(x):
    if not x or pd.isna(x):
        return None

    return list(set(x.split('|')))


def parse_contact_info(x: list):
    res = set()
    for i in x:
        if i and pd.notna(i):
            if '|' in i:
                res.update(i.split('|'))
            else:
                res.add(i)
    return list(res)


def unique_list(x: pd.Series):
    if x.empty:
        return None
    else:
        s = set()
        for v in x.values:
            if v and pd.notna(v):
                if '|' in v:
                    s.update(v.split('|'))
                else:
                    s.add(v)
        return list(s)


def with_email_domain(x):
    if not isinstance(x, str) and not isinstance(x, list):
        return None
    target_list = literal_eval(x) if isinstance(x, str) else x

    s = set()
    for email in target_list:
        if email and pd.notna(email) and '@' in email:
            s.add('@' + email.split('@')[-1].strip())
    return list(s)


def with_parsed_phone(x):
    if not isinstance(x, str) and not isinstance(x, list):
        return None
    target_list = literal_eval(x) if isinstance(x, str) else x

    s = set()
    for phone in target_list:
        if phone and pd.notna(phone):
            if ':' in phone:
                s.add(phone.split(':')[-1].strip())
            else:
                s.add(phone.strip())
    return list(s)


class ASWithMailKey(BaseEntity):
    def __init__(self, date: str, config_path='conf/config.yaml', enable_DB=True):
        super().__init__(config_path, date, enable_DB)
        self.target_dir = os.path.join(self.target_dir, 'format')
        self.org_entity_data_path = './data/org_entity/'
        # self.rir_list = ['afrinic', 'apnic', 'arin', 'lacnic', 'ripe'] # Super class

        df_tld = pd.read_csv(os.path.join(self.static_data_path, 'TLD.csv'))
        df_tld['Domain'] = df_tld['Domain'].str.replace('.', '')
        df_tld = df_tld[df_tld['Type'] == 'country-code']
        # df_tld = df_tld[~(df_tld['TLD Manager'].str.contains(r'llc|inc|ltd|limited|company|co\.|corporation', case=False))]
        tld_set = set(df_tld['Domain'].values)

        # 自定义邮箱后缀
        diy_domain = {'', 'com', 'ocm', 'con', 'net', 'supplied', 'unknown', 'nic', 'ap', 'team', 'access', 'gmail', 'qq', '163', '126', 'outlook', 'hotmail', 'yahoo', 'sina', 'sohu', 'aliyun',
                      'foxmail', 'yeah', '139', '189', 'tom', '21cn', 'vip', 'icloud', 'live', 'msn', 'sogou', 'mail', 'corp', 'public', 'apnic', 'arin', 'ripe', 'ripencc', 'lacnic', 'afrinic'}
        tld_set.update(diy_domain)
        self.tld_set = tld_set

    def grouped_csv(self, handle_as=True) -> dict:
        '''
        生成按照 rir 分组的 as 信息 csv 文件

        '''
        if handle_as:
            asn_path = os.path.join(self.format_dir, self.date, 'asn.csv')
            df_as = pd.read_csv(asn_path, dtype={'asn': int})
            df_as = df_as[(df_as['status'] == 'allocated') | (df_as['status'] == 'assigned')]
        else:
            ipv4_path = os.path.join(self.format_dir, self.date, 'ipv4.csv')
            df_ipv4 = pd.read_csv(ipv4_path)
            df_ipv4 = df_ipv4[(df_ipv4['status'] == 'allocated') | (df_ipv4['status'] == 'assigned')]
            df_ipv4['version'] = 'v4'

            ipv6_path = os.path.join(self.format_dir, self.date, 'ipv6.csv')
            df_ipv6 = pd.read_csv(ipv6_path)
            df_ipv6 = df_ipv6[(df_ipv6['status'] == 'allocated') | (df_ipv6['status'] == 'assigned')]
            df_ipv6['version'] = 'v6'

            df_as = pd.concat([df_ipv4, df_ipv6], ignore_index=True)

        rdap_dir = os.path.join(self.format_dir, self.date)
        rdap_list = []
        entity_list = []
        result = {}
        for rir in self.rir_list:
            if handle_as:
                rdap_path = os.path.join(rdap_dir, rir, f'{rir}_as_rdap_info.csv')
                df_rdap = pd.read_csv(rdap_path, usecols=['handle', 'name', 'descr',
                                                          'registrant', 'administrative', 'technical', 'abuse'])
            else:
                rdap_path = os.path.join(rdap_dir, rir, f'{rir}_ip_rdap_info.csv')
                df_rdap = pd.read_csv(rdap_path, usecols=['CIDR', 'handle', 'name', 'descr',
                                                          'registrant', 'administrative', 'technical', 'abuse'])

            if handle_as:
                df_rdap['asn'] = df_rdap['handle'].apply(lambda x: int(x.split('AS')[-1]))
                df_rdap.drop(columns=['handle'], inplace=True)
                df_rdap.rename(columns={'name': 'as_name',
                                        'registrant': 'org', 'administrative': 'admin_c',
                                        'technical': 'tech_c', 'abuse': 'abuse_c'}, inplace=True)
            else:
                df_rdap.rename(columns={'CIDR': 'prefix', 'name': 'ip_name',
                                        'registrant': 'org', 'administrative': 'admin_c',
                                        'technical': 'tech_c', 'abuse': 'abuse_c'}, inplace=True)

            logger.info(f'sloving {rir} org...')
            df_rdap['org'] = df_rdap['org'].apply(slove_org)
            df_rdap['admin_c'] = df_rdap['admin_c'].apply(slove_contact)
            df_rdap['tech_c'] = df_rdap['tech_c'].apply(slove_contact)
            df_rdap['abuse_c'] = df_rdap['abuse_c'].apply(slove_contact)
            rdap_list.append(df_rdap)

            if handle_as:
                entity_path = os.path.join(rdap_dir, rir, f'{rir}_as_entity_rdap_info.csv')
            else:
                entity_path = os.path.join(rdap_dir, rir, f'{rir}_ip_entity_rdap_info.csv')
            df_entity = pd.read_csv(entity_path)
            entity_list.append(df_entity)

            if handle_as:
                df_temp = df_as[df_as['asn'].isin(df_rdap['asn'].unique())].copy()
                df_rir_as = pd.merge(df_temp, df_rdap, on='asn', how='left')
            else:
                df_temp = df_as[df_as['prefix'].isin(df_rdap['prefix'].unique())].copy()
                df_rir_as = pd.merge(df_temp, df_rdap, on='prefix', how='left')
            df_rir_as['org_phone'] = None
            df_rir_as['org_email'] = None
            df_rir_as['org_descr'] = None
            df_rir_as['org_name'] = None
            df_rir_as['admin_phone'] = None
            df_rir_as['admin_email'] = None
            df_rir_as['tech_phone'] = None
            df_rir_as['tech_email'] = None
            df_rir_as['abuse_phone'] = None
            df_rir_as['abuse_email'] = None
            # print(df_rir_as)

            if rir != 'arin':
                df_entity.drop_duplicates(subset=['handle'], inplace=True)
                df_entity['index'] = df_entity['handle'].copy()
                df_entity.set_index('index', inplace=True)
                for row in tqdm(df_rir_as.itertuples(), total=len(df_rir_as), desc=f'Parsing {rir} contact info...'):
                    if row.org and pd.notna(row.org):
                        try:
                            org_phone = df_entity.loc[row.org]['tel']
                            org_email = df_entity.loc[row.org]['email']
                            org_descr = df_entity.loc[row.org]['descr']
                            org_name = df_entity.loc[row.org]['name']
                        except KeyError:
                            continue
                        if org_phone and pd.notna(org_phone):
                            df_rir_as.at[row.Index, 'org_phone'] = org_phone.split('|')
                        if org_email and pd.notna(org_email):
                            df_rir_as.at[row.Index, 'org_email'] = org_email.split('|')
                        if org_descr and pd.notna(org_descr):
                            df_rir_as.at[row.Index, 'org_descr'] = org_descr
                        if org_name and pd.notna(org_name):
                            df_rir_as.at[row.Index, 'org_name'] = org_name

                    if row.admin_c:
                        phone_set = set()
                        email_set = set()
                        for admin in row.admin_c:
                            try:
                                admin_phone = df_entity.loc[admin]['tel']
                                admin_email = df_entity.loc[admin]['email']
                            except KeyError:
                                continue
                            if admin_phone and pd.notna(admin_phone):
                                phone_set.update(admin_phone.split('|'))
                            if admin_email and pd.notna(admin_email):
                                email_set.update(admin_email.split('|'))

                        df_rir_as.at[row.Index, 'admin_phone'] = list(phone_set)
                        df_rir_as.at[row.Index, 'admin_email'] = list(email_set)

                    if row.tech_c:
                        phone_set = set()
                        email_set = set()
                        for tech in row.tech_c:
                            try:
                                tech_phone = df_entity.loc[tech]['tel']
                                tech_email = df_entity.loc[tech]['email']
                            except KeyError:
                                continue
                            if tech_phone and pd.notna(tech_phone):
                                phone_set.update(tech_phone.split('|'))
                            if tech_email and pd.notna(tech_email):
                                email_set.update(tech_email.split('|'))
                        df_rir_as.at[row.Index, 'tech_phone'] = list(phone_set)
                        df_rir_as.at[row.Index, 'tech_email'] = list(email_set)

                    if row.abuse_c:
                        phone_set = set()
                        email_set = set()
                        for abuse in row.abuse_c:
                            try:
                                abuse_phone = df_entity.loc[abuse]['tel']
                                abuse_email = df_entity.loc[abuse]['email']
                            except KeyError:
                                continue
                            if abuse_phone and pd.notna(abuse_phone):
                                phone_set.update(abuse_phone.split('|'))
                            if abuse_email and pd.notna(abuse_email):
                                email_set.update(abuse_email.split('|'))
                        df_rir_as.at[row.Index, 'abuse_phone'] = list(phone_set)
                        df_rir_as.at[row.Index, 'abuse_email'] = list(email_set)
            else:
                logger.info(f'grouping {rir} entity...')
                df_arin_group = df_entity.groupby('orginHandle').agg({
                    'tel': unique_list,
                    'email': unique_list,
                })
                df_entity.drop_duplicates(subset=['handle'], inplace=True)
                df_entity['index'] = df_entity['handle'].copy()
                df_entity.set_index('index', inplace=True)
                for row in tqdm(df_rir_as.itertuples(), total=len(df_rir_as), desc=f'Parsing {rir} contact info...'):
                    if row.org and pd.notna(row.org):
                        try:
                            df_rir_as.at[row.Index, 'org_phone'] = df_arin_group.loc[row.org]['tel']
                            df_rir_as.at[row.Index, 'org_email'] = df_arin_group.loc[row.org]['email']
                            df_rir_as.at[row.Index, 'org_descr'] = df_entity.loc[row.org]['descr']
                            df_rir_as.at[row.Index, 'org_name'] = df_entity.loc[row.org]['name']
                        except KeyError:
                            continue

            result[rir] = df_rir_as

        logger.info('All AS info parsed successfully!')
        return result

    def run(self, handle_as=True):
        #　过滤出状态为 'allocated' 或 'assigned' 的记录，并根据不同的RIR（如'arin'、'apnic'等），读取相应的RDAP信息文件
        result_dict = self.grouped_csv(handle_as)

        for rir in self.rir_list:
            df = result_dict.get(rir)

            df['org_email'] = df['org_email'].apply(with_email_domain)
            df['admin_email'] = df['admin_email'].apply(with_email_domain)
            df['tech_email'] = df['tech_email'].apply(with_email_domain)
            df['abuse_email'] = df['abuse_email'].apply(with_email_domain)

            df['org_phone'] = df['org_phone'].apply(with_parsed_phone)
            df['admin_phone'] = df['admin_phone'].apply(with_parsed_phone)
            df['tech_phone'] = df['tech_phone'].apply(with_parsed_phone)
            df['abuse_phone'] = df['abuse_phone'].apply(with_parsed_phone)

            for c in ['org_email', 'admin_email', 'tech_email', 'abuse_email']:
                df[c] = df[c].apply(lambda x: literal_eval(x) if isinstance(x, str) else x)
                df[f'{c}_key'] = df[c].apply(lambda x: list(mail_set(x, self.tld_set)) if isinstance(x, list) else None) # mail是列表，则返回检查过的邮件列表

            if handle_as:
                target_str = 'as'
            else:
                target_str = 'ip'

            target_path = os.path.join(self.org_entity_data_path, rir)

            if not os.path.exists(target_path):
                os.mkdir(target_path)

            target_path = os.path.join(target_path,
                                       f'{rir}_{target_str}_info_with_mail_key.csv')
            df.to_csv(target_path, index=False)
            logger.info(f'{rir} {target_str} info with mail key saved in {target_path} successfully!')
