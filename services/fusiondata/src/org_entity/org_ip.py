'''
通过 AS 的 Whois 与 RDAP 数据生成组织机构映射

'''

from fusiondata.src import BaseEntity
from fusiondata.src.utils.logging_manager import logger

import os
import uuid
from ast import literal_eval
from typing import Tuple

import pandas as pd
from tqdm import tqdm


class OrgIP(BaseEntity):
    def __init__(self, date: str, config_path='conf/config.yaml', enable_DB=True):
        super().__init__(config_path, date, enable_DB)
        self.target_dir = os.path.join(self.target_dir, 'format')
        self.org_entity_data_path = './fusiondata/data/org_entity/'
        self.rir_list = ['arin', 'apnic', 'ripe', 'lacnic', 'afrinic']

        ipv4_path = os.path.join(self.format_dir, self.date, 'ipv4.csv')
        df_ipv4 = pd.read_csv(ipv4_path, keep_default_na=False)
        df_ipv4 = df_ipv4[(df_ipv4['status'] == 'allocated') | (df_ipv4['status'] == 'assigned')].copy()
        df_ipv4.dropna(subset=['country'], inplace=True)
        self.df_ipv4 = df_ipv4[(df_ipv4['country'] != 'ZZ') & (df_ipv4['country'] != '')]

        ipv6_path = os.path.join(self.format_dir, self.date, 'ipv6.csv')
        df_ipv6 = pd.read_csv(ipv6_path, keep_default_na=False)
        df_ipv6 = df_ipv6[(df_ipv6['status'] == 'allocated') | (df_ipv6['status'] == 'assigned')].copy()
        df_ipv6.dropna(subset=['country'], inplace=True)
        self.df_ipv6 = df_ipv6[(df_ipv6['country'] != 'ZZ') & (df_ipv6['country'] != '')]

        self.df_ip = pd.concat([self.df_ipv4, self.df_ipv6])

    def __run(self, df_mail_key: pd.DataFrame, df_entity: pd.DataFrame, rir: str) -> Tuple[pd.DataFrame, set, set]:
        '''
        通过 IP 的 Whois 与 RDAP 数据生成组织机构映射 (org_handle)

        Parameters:

            df_ip: pd.DataFrame IP delegation 数据

            df_mail_key: pd.DataFrame 带邮箱关键字的前缀原始数据

            df_entity: pd.DataFrame RDAP/Whois 的 entity 数据

            rir: str RIR 名称

        Returns:

            df_org: pd.DataFrame IP-Org 映射数据

            diff_set_v4: set 未处理的 IPv4 前缀

            diff_set_v6: set 未处理的 IPv6 前缀

        '''

        df_mail_key_v4 = df_mail_key[df_mail_key['version'] == 'v4'].dropna(subset=['org']).copy()
        df_mail_key_v6 = df_mail_key[df_mail_key['version'] == 'v6'].dropna(subset=['org']).copy()

        df_entity_info = df_entity[df_entity['orginType'] == 'ip'].copy()
        df_entity_info = df_entity_info[['handle', 'name', 'descr', 'address', 'tel', 'fax', 'email', 'kind',
                                         'lacnic_legalRepresentative', 'self', 'alternate', 'up', 'registrationDate', 'lastChangeDate', 'country']].copy()
        df_entity_info.drop_duplicates(subset=['handle'], inplace=True)

        df_ipv4 = self.df_ipv4[self.df_ipv4['source'] == rir].copy()
        df_ipv6 = self.df_ipv6[self.df_ipv6['source'] == rir].copy()

        df_v4_group = df_mail_key_v4.groupby('org').agg(
            prefix_v4=('prefix', 'unique'),
            prefix_v4_num=('prefix', 'nunique'),
        )
        # df_v4_group['org'] = df_v4_group.index
        # print(df_v4_group)

        df_v6_group = df_mail_key_v6.groupby('org').agg(
            prefix_v6=('prefix', 'unique'),
            prefix_v6_num=('prefix', 'nunique'),
        )
        # df_v6_group['org'] = df_v6_group.index
        # print(df_v6_group)

        df_group = pd.merge(df_v4_group, df_v6_group, on='org', how='outer')
        df_group['handle'] = df_group.index
        df_group['prefix_v4_num'].fillna(0, inplace=True)
        df_group['prefix_v6_num'].fillna(0, inplace=True)
        sloved_ipv4 = set(df_group['prefix_v4'].explode().dropna().unique().tolist())
        sloved_ipv6 = set(df_group['prefix_v6'].explode().dropna().unique().tolist())

        print(df_group[df_group['handle'] == 'ORG-AL30-AP'])
        print(df_entity_info[df_entity_info['handle'] == 'ORG-AL30-AP'])
        df_org = pd.merge(df_group, df_entity_info, on='handle', how='left')
        print(df_org[df_org['handle'] == 'ORG-AL30-AP'])

        target_rir = rir if rir != 'ripe' else 'ripencc'
        # v4
        df_rir = df_ipv4[df_ipv4['source'] == target_rir].copy()
        target_set = set(df_rir['prefix'].to_list())
        diff_set_v4 = target_set - sloved_ipv4
        # v6
        df_rir = df_ipv6[df_ipv6['source'] == target_rir].copy()
        target_set = set(df_rir['prefix'].to_list())
        diff_set_v6 = target_set - sloved_ipv6

        df_org.drop_duplicates(subset=['handle'], inplace=True)
        df_org.sort_values(by=['prefix_v4_num', 'prefix_v6_num'], ascending=[False, False], inplace=True)

        df_org.to_csv(os.path.join(self.org_entity_data_path, rir, f'{rir}_ip_org.csv'), index=False)

        return df_org, diff_set_v4, diff_set_v6

    def __append_mail_key_col(self, df_org: pd.DataFrame, df_mail_key: pd.DataFrame, rir: str) -> pd.DataFrame:
        '''
        为 df_org 添加 mail_key 列，并据此进行初步聚类

        Parameters:

            df_org: pd.DataFrame AS-Org 映射数据

            df_mail_key: 带邮箱关键字的 AS 原始数据

            rir: str RIR 名称

        Returns:

            df_org_res: pd.DataFrame AS-Org 映射数据

        '''
        if rir not in self.rir_list:
            raise ValueError(f'Error rir: {rir}')

        df_org_res = df_org.copy()

        logger.info(f'为 {rir} 组织机构添加 org_mail_key 列')

        def get_org_mail_key(x):
            if isinstance(x, float):
                return None
            df_temp = df_mail_key[df_mail_key['prefix'].isin(x)].copy()

            res = df_temp['org_email_key'].explode().dropna().drop_duplicates().sort_values().tolist()

            if len(res) == 0:
                return None
            return set(res)

        # df_org_res['org_v4_mail_key'] = df_org_res['prefix_v4'].apply(lambda x: get_org_mail_key(x))
        # df_org_res['org_v6_mail_key'] = df_org_res['prefix_v6'].apply(lambda x: get_org_mail_key(x))

        def merge_key(row):
            set_v4 = get_org_mail_key(row['prefix_v4'])
            set_v6 = get_org_mail_key(row['prefix_v6'])

            if set_v4 is None and set_v6 is None:
                return None
            elif set_v4 is None:
                return set_v6
            elif set_v6 is None:
                return set_v4
            else:
                return set_v4 | set_v6

        df_org_res['org_mail_key'] = df_org_res.apply(lambda row: merge_key(row), axis=1)
        # print(df_org_res)
        logger.info(f'为 {rir} 组织机构添加 org_mail_key 列完成')

        df_org_res = df_org_res[['handle', 'prefix_v4', 'prefix_v6', 'org_mail_key']]
        df_org_res.rename(columns={'handle': 'org_handle'}, inplace=True)
        # print(df_org_res)

        df_without_org_mail = df_org_res[df_org_res['org_mail_key'].isna()].copy()

        df_with_org_mail = df_org_res[df_org_res['org_mail_key'].notna()].copy()
        df_with_org_mail['org_mail_key'] = df_with_org_mail['org_mail_key'].apply(lambda x: '|'.join(x))
        if rir == 'apnic':
            # 手动归并中国教育网的 CERNET 与 CERNIC
            df_with_org_mail['org_mail_key'] = df_with_org_mail['org_mail_key'].str.replace('cernet', 'cernic')
            df_with_org_mail['org_handle'] = df_with_org_mail['org_handle'].str.replace('ORG-CNTC2-AP', 'ORG-CEAR1-AP')
        df_with_org_mail['prefix_v4_num'] = df_with_org_mail['prefix_v4'].apply(
            lambda x: len(x) if isinstance(x, list) else 0)
        df_with_org_mail['prefix_v6_num'] = df_with_org_mail['prefix_v6'].apply(
            lambda x: len(x) if isinstance(x, list) else 0)
        df_with_org_mail.sort_values(by=['prefix_v4_num', 'prefix_v6_num'], ascending=[False, False], inplace=True)
        # print(df_with_org_mail)

        def set_sum(x: pd.Series):
            res = set()
            x.dropna(inplace=True)
            for i in x.values.tolist():
                if not isinstance(i, float):
                    res.update(i)
            return list(res)

        df_res_with_org_mail = df_with_org_mail.groupby('org_mail_key').agg(
            {
                # 先前通过 AS 数量排序，这里直接取第一个即为 AS 数量最多的 org_handle
                'org_handle': 'first',
                'prefix_v4': set_sum,
                'prefix_v6': set_sum,
            }
        )

        df_res_with_org_mail['org_mail_key'] = df_res_with_org_mail.index
        # print(df_res_with_org_mail)

        df_res = pd.concat([df_res_with_org_mail, df_without_org_mail])
        df_res['org_mail_key'] = df_res['org_mail_key'].apply(
            lambda x: set(x.split('|')) if isinstance(x, str) else None)
        df_res['prefix_v4_num'] = df_res['prefix_v4'].apply(lambda x: len(x) if not isinstance(x, float) else 0)
        df_res['prefix_v6_num'] = df_res['prefix_v6'].apply(lambda x: len(x) if not isinstance(x, float) else 0)
        df_res.sort_values(by=['prefix_v4_num', 'prefix_v6_num'], ascending=[False, False], inplace=True)

        logger.info(f'已利用 org mail key 初步聚类 {rir} 组织机构')

        return df_res

    def __merge_unsloved_ip_by_mail_key(self, df_mail_key: pd.DataFrame, target_v4: set, target_v6: set, rir: str, target_country: str = None) -> Tuple[pd.DataFrame, set, set]:
        '''
        为没有 org_handle 的 IP 利用联系人的 mail_key 进行聚类

        '''
        if rir not in self.rir_list:
            raise ValueError(f'Error rir: {rir}')

        mail_key_dict = dict()
        unsloved_v4 = set()
        unsloved_v6 = set()
        target_ip = target_v4 | target_v6

        df_mail = df_mail_key[df_mail_key['prefix'].isin(target_ip)].copy()
        if target_country:
            df_mail = df_mail[df_mail['country'] == target_country]

        for row in tqdm(df_mail.itertuples(), total=len(df_mail), desc=f'Merging {rir} unsloved IP prefix by mail key...'):
            tech_email = [i.lower() for i in row.tech_email_key] if isinstance(row.tech_email_key, list) else []
            admin_email = [i.lower() for i in row.admin_email_key] if isinstance(row.admin_email_key, list) else []
            tech_email_set = set(tech_email)
            admin_email_set = set(admin_email)
            # tech 更能代表 AS 的归属方
            # 但存在拥有非常多 tech 的 AS 的情况（mail key阈值 5），此时 admin 则更有代表性
            if len(tech_email_set) > 0 and len(tech_email_set) < 5:
                mixed_mail_set = tech_email_set
            else:
                mixed_mail_set = admin_email_set

            if len(mixed_mail_set) == 0:
                if row.version == 'v4':
                    unsloved_v4.add(row.prefix)
                else:
                    unsloved_v6.add(row.prefix)
            else:
                target_v4_set = set()
                target_v6_set = set()
                if row.version == 'v4':
                    target_v4_set.add(row.prefix)
                else:
                    target_v6_set.add(row.prefix)
                target_key = mixed_mail_set
                key_to_pop = []
                for key in mail_key_dict.keys():
                    key_set = set(key)
                    same_set = key_set & mixed_mail_set
                    if len(same_set) > 0:
                        target_v4_set.update(mail_key_dict.get(key).get('prefix_v4'))
                        target_v6_set.update(mail_key_dict.get(key).get('prefix_v6'))
                        target_key = key_set | target_key
                        key_to_pop.append(key)
                for key in key_to_pop:
                    mail_key_dict.pop(key)

                mail_key_dict[tuple(target_key)] = {'prefix_v4': target_v4_set,
                                                    'prefix_v6': target_v6_set, 'key_set': target_key}

        mail_key_dict = {'|'.join(k): v for k, v in mail_key_dict.items()}

        df_res = pd.DataFrame.from_dict(mail_key_dict, orient='index')

        return df_res, unsloved_v4, unsloved_v6

    def __merge_unsloved_ip_to_org_handle(self, df_org_handle: pd.DataFrame, df_unslove_ip: pd.DataFrame, rir: str) -> Tuple[pd.DataFrame, list, list]:

        unsloved_v4_list = []
        unsloved_v6_list = []
        df_res = df_org_handle.copy()
        df_res['prefix_v4'] = df_res['prefix_v4'].apply(lambda x: set(x) if isinstance(x, list) else x)
        df_res['prefix_v6'] = df_res['prefix_v6'].apply(lambda x: set(x) if isinstance(x, list) else x)

        logger.info('合并未处理的前缀到已处理的 org_handle 中')

        for row in tqdm(df_unslove_ip.itertuples(), total=len(df_unslove_ip), desc=f'Merging {rir} unsloved IP prefix to org handle...'):
            mixed_mail_set = row.key_set if isinstance(row.key_set, set) else set()

            if len(mixed_mail_set) == 0:
                unsloved_v4_list.append(row.prefix_v4)
                unsloved_v6_list.append(row.prefix_v6)
            else:
                find_org_flag = False
                find_org_idx = None
                for org_row in df_res.itertuples():
                    if not isinstance(org_row.org_mail_key, set):
                        continue

                    if org_row.org_mail_key == mixed_mail_set:
                        df_res.at[org_row.Index, 'prefix_v4'].update(row.prefix_v4)
                        df_res.at[org_row.Index, 'prefix_v6'].update(row.prefix_v6)
                        break
                    elif not find_org_flag:
                        same_set = org_row.org_mail_key & mixed_mail_set
                        if len(same_set) > 0:
                            find_org_idx = org_row.Index
                            find_org_flag = True
                else:
                    if find_org_flag:
                        df_res.at[find_org_idx, 'prefix_v4'].update(row.prefix_v4)
                        df_res.at[find_org_idx, 'prefix_v6'].update(row.prefix_v6)
                    else:
                        unsloved_v4_list.append(row.prefix_v4)
                        unsloved_v6_list.append(row.prefix_v6)

        df_res['prefix_v4'] = df_res['prefix_v4'].apply(lambda x: set(x) if isinstance(x, list) else x)
        df_res['prefix_v6'] = df_res['prefix_v6'].apply(lambda x: set(x) if isinstance(x, list) else x)

        df_res['prefix_v4_num'] = df_res['prefix_v4'].apply(lambda x: len(x) if isinstance(x, set) else 0)
        df_res['prefix_v6_num'] = df_res['prefix_v6'].apply(lambda x: len(x) if isinstance(x, set) else 0)
        df_res.sort_values(by=['prefix_v4_num', 'prefix_v6_num'], ascending=[False, False], inplace=True)

        logger.info('合并未处理的 IP 到已处理的 org_handle 完成')
        return df_res, unsloved_v4_list, unsloved_v6_list

    def __final_merge(self, df_org_handle_info: pd.DataFrame, df_org_handle_data: pd.DataFrame, rest_v4: list, rest_v6: list, rest_v4_list: list, rest_v6_list: list, df_ip_info: pd.DataFrame, rir: str) -> pd.DataFrame:
        '''
        最后整合 RIR 的所有组织机构数据

        Parameters:

            df_org_handle_info: pd.DataFrame 组织机构信息，由 self.__run 生成

            df_org_handle_data: pd.DataFrame 组织机构数据，由 self.__merge_unsloved_ip_to_org_handle 生成

            rest_v4: list 未处理的 IPv4 前缀，由 self.__merge_unsloved_ip_by_mail_key 生成

            rest_v6: list 未处理的 IPv6 前缀，由 self.__merge_unsloved_ip_by_mail_key 生成

            rest_v4_list: list 未处理的 IP，由 self.__merge_unsloved_ip_to_org_handle 生成

            rest_v6_list: list 未处理的 IP，由 self.__merge_unsloved_ip_to_org_handle 生成

            df_ip_info: pd.DataFrame IP 信息，读取自 {rir}_ip_info_with_mail_key.csv

            rir: str RIR 名称

        Returns:

            df_res: pd.DataFrame 整合后的组织机构数据

        '''
        df_org_info = df_org_handle_info[['handle', 'name', 'descr', 'address', 'tel',
                                          'fax', 'email', 'country']].copy()
        df_org_data = df_org_handle_data[['org_handle', 'prefix_v4', 'prefix_v4_num', 'prefix_v6', 'prefix_v6_num']].rename(
            {'org_handle': 'handle'}, axis=1)

        df_ip_info = df_ip_info[['prefix', 'country', 'ip_name', 'descr',
                                 'admin_phone', 'admin_email', 'tech_phone', 'tech_email', 'version']].copy()
        df_ip_info['index'] = df_ip_info['prefix']
        df_ip_info.set_index('index', inplace=True)

        logger.info(f'最后整合 {rir} 的所有组织机构数据')

        df_res = pd.merge(df_org_info, df_org_data, on='handle', how='left')

        def slove_list(x):
            if isinstance(x, list):
                return x
            elif isinstance(x, set):
                return list(x)
            else:
                return []

        df_res['prefix_v4'] = df_res['prefix_v4'].apply(slove_list)
        df_res['prefix_v6'] = df_res['prefix_v6'].apply(slove_list)

        data_list = []

        def slove_ip_list(x, v4: bool):

            ver_str = 'v4' if v4 else 'v6'

            for ip_set in x:
                ip_list = list(ip_set)
                if len(ip_list) == 0:
                    continue

                try:
                    ip_info_dict = df_ip_info.loc[ip_list[0]].to_dict()
                except KeyError:
                    continue

                ip_descr = ip_info_dict.get('descr')
                if isinstance(ip_descr, str):
                    ip_name = ip_descr.split('|')[0]
                else:
                    ip_name = ip_info_dict.get('ip_name')
                ip_tel = ip_info_dict.get('admin_phone')
                if ip_tel is None:
                    ip_tel = ip_info_dict.get('tech_phone')
                ip_email = ip_info_dict.get('admin_email')
                if ip_email is None:
                    ip_email = ip_info_dict.get('tech_email')
                ip_country = ip_info_dict.get('country')

                data_list.append({'handle': None, 'name': ip_name,
                                  'descr': ip_descr, 'address': None, 'tel': ip_tel,
                                  'fax': None, 'email': ip_email,
                                  'country': ip_country, f'prefix_{ver_str}': ip_list, f'prefix_{ver_str}_num': len(ip_list)})

        slove_ip_list(rest_v4_list, True)
        slove_ip_list(rest_v6_list, False)

        def slove_ip_single(x, v4: bool):

            ver_str = 'v4' if v4 else 'v6'

            for p in x:

                try:
                    ip_info_dict = df_ip_info.loc[p].to_dict()
                except KeyError:
                    continue

                ip_descr = ip_info_dict.get('descr')
                if isinstance(ip_descr, str):
                    ip_name = ip_descr.split('|')[0]
                else:
                    ip_name = ip_info_dict.get('ip_name')
                ip_tel = ip_info_dict.get('admin_phone')
                if ip_tel is None:
                    ip_tel = ip_info_dict.get('tech_phone')
                ip_email = ip_info_dict.get('admin_email')
                if ip_email is None:
                    ip_email = ip_info_dict.get('tech_email')
                ip_country = ip_info_dict.get('country')

                data_list.append({'handle': None, 'name': ip_name,
                                  'descr': ip_descr, 'address': None, 'tel': ip_tel,
                                  'fax': None, 'email': ip_email,
                                  'country': ip_country, f'prefix_{ver_str}': [p], f'prefix_{ver_str}_num': 1})

        slove_ip_single(rest_v4, True)
        slove_ip_single(rest_v6, False)

        df_extra = pd.DataFrame(data_list)
        df_res = pd.concat([df_res, df_extra])

        return df_res

    def run(self):

        # rir_list = self.rir_list
        rir_list = ['apnic']
        df_ip = self.df_ip
        list_df_org = []

        for rir in rir_list:
            logger.info(f'处理 {rir} 组织机构数据')

            target_path = os.path.join(self.org_entity_data_path, rir)

            if not os.path.exists(target_path):
                os.mkdir(target_path)

            rdap_path = os.path.join(self.format_dir, self.date, rir, f'{rir}_ip_entity_rdap_info.csv')
            df = pd.read_csv(rdap_path)
            df.dropna(subset=['name'], inplace=True)

            df_ip_mail_key = pd.read_csv(os.path.join(
                target_path, f'{rir}_ip_info_with_mail_key.csv'))

            df_ip_mail_key['org_email_key'] = df_ip_mail_key['org_email_key'].apply(
                lambda x: literal_eval(x) if pd.notna(x) else [])
            df_ip_mail_key['admin_email_key'] = df_ip_mail_key['admin_email_key'].apply(
                lambda x: literal_eval(x) if pd.notna(x) else [])
            df_ip_mail_key['tech_email_key'] = df_ip_mail_key['tech_email_key'].apply(
                lambda x: literal_eval(x) if pd.notna(x) else [])

            # df_prefix = df_ip_mail_key[['prefix', 'handle', 'version']].copy()
            # df_prefix.rename(columns={'handle': 'orginHandle'}, inplace=True)
            # df = pd.merge(df, df_prefix, on='orginHandle', how='left')
            # df.dropna(subset=['prefix'], inplace=True)
            # print(len(df_prefix))

            df_org, unsloved_ipv4, unsloved_ipv6 = self.__run(df_ip_mail_key, df, rir)
            # list_df_org.append(df_org)
            logger.info(
                f'利用 org handle 初步聚类 {rir} 组织机构，未处理的 IPv4 前缀数量: {len(unsloved_ipv4)}， 未处理的 IPv6 前缀数量: {len(unsloved_ipv6)}')

            df_org_handle_group = self.__append_mail_key_col(df_org, df_ip_mail_key, rir)
            df_org_handle_group.to_csv(os.path.join(target_path, f'{rir}_ip_org_handle_group.csv'), index=False)

            df_unslove_mail_group, rest_v4, rest_v6 = self.__merge_unsloved_ip_by_mail_key(
                df_ip_mail_key, unsloved_ipv4, unsloved_ipv6, rir)
            df_unslove_mail_group.to_csv(os.path.join(target_path, f'{rir}_ip_unslove_mail_group.csv'), index=False)
            logger.info(f'利用 mail key 进一步聚类 {rir} 组织机构，未处理的 v4 前缀数量: {len(rest_v4)}，未处理的 v6 前缀数量: {len(rest_v6)}')
            # with open(os.path.join(self.org_entity_data_path, f'{rir}_unslove_asn.txt'), 'w') as f:
            #     f.write('\n'.join(map(str, rest_asn)))

            df_merged, rest_v4_list, rest_v6_list = self.__merge_unsloved_ip_to_org_handle(
                df_org_handle_group, df_unslove_mail_group, rir)
            df_merged.to_csv(os.path.join(target_path, f'{rir}_ip_merged_org_handle_group.csv'), index=False)
            logger.info(f'利用 mail key 将未处理的 AS 聚类到 {rir} 组织机构')

            df_rir_res = self.__final_merge(df_org, df_merged, rest_v4, rest_v6,
                                            rest_v4_list, rest_v6_list, df_ip_mail_key, rir)
            list_df_org.append(df_rir_res)
            df_rir_res.to_csv(os.path.join(target_path, f'{rir}_ip_final_merged.csv'), index=False)

            logger.info(f'{rir} 组织机构数据处理完成 \n')
        # return
        logger.info('整合五大 RIR Org 映射')

        df_all_org = pd.concat(list_df_org)
        # df_all_org.to_csv(os.path.join(self.org_entity_data_path, f'as_org_mapping.csv'), index=False)
        df_all_org.rename(columns={'name': 'org_name'}, inplace=True)

        df_org_cn = pd.read_csv(os.path.join(self.org_entity_data_path, 'org_translate.csv'),
                                usecols=['org_name', 'org_name_cn'])
        df_org_cn.drop_duplicates(subset=['org_name'], inplace=True)
        df_org_cn.dropna(inplace=True)
        # print(df_all_org)
        # print(df_org_cn)
        df_all_org = pd.merge(df_all_org, df_org_cn, on='org_name', how='left')

        df_all_org['uuid'] = None
        df_all_org['uuid'] = df_all_org['org_name'].apply(lambda x: uuid.uuid5(
            uuid.NAMESPACE_DNS, str(x).replace(' ', '')).hex if isinstance(x, str) else None)

        def solve_handle(x: pd.Series):
            return set(x.dropna().values.tolist())

        def solve_prefix(x: pd.Series):
            res = set()
            for s in x.values.tolist():
                if isinstance(s, list) or isinstance(s, set):
                    res.update(s)
            return list(res)

        df_all_org = df_all_org.groupby('uuid').agg(
            {
                'handle': solve_handle,
                'org_name': 'first',
                'descr': 'first',
                'address':  'first',
                'tel': 'first',
                'fax':  'first',
                'email': 'first',
                'country': 'first',
                'prefix_v4': solve_prefix,
                'prefix_v6': solve_prefix,
                'org_name_cn': 'first'
            }
        ).reset_index()

        df_org_only = df_all_org[['uuid', 'org_name', 'descr']].copy()
        df_org_only.drop_duplicates(subset=['uuid'], inplace=True)
        df_org_only.to_csv(os.path.join(self.org_entity_data_path, 'ip_org_only.csv'), index=False)

        df_all_org['prefix_v4_num'] = df_all_org['prefix_v4'].apply(lambda x: len(x))
        df_all_org['prefix_v6_num'] = df_all_org['prefix_v6'].apply(lambda x: len(x))
        df_all_org['CIDR'] = df_all_org['prefix_v4'] + df_all_org['prefix_v6']
        # print(df_all_org)
        df_all_org = df_all_org.explode('CIDR')
        df_all_org = df_all_org[df_all_org['CIDR'].notna()]
        # print(df_all_org)

        # df_all_org['prefix'] = df_all_org['prefix'].apply(lambda x: list(x))
        df_all_org['handle'] = df_all_org['handle'].apply(lambda x: list(x))

        all_ip_set = set(df_ip['prefix'].tolist())
        grouped_ip_set = set(df_all_org['CIDR'].values.tolist())
        diff_set = all_ip_set - grouped_ip_set

        fail_path = os.path.join(self.org_entity_data_path, 'unsolved_ip.txt')
        logger.info(f'无法处理的 IP 前缀数量: {len(diff_set)}，正在写入 {fail_path} ...')
        with open(fail_path, 'w') as f:
            f.write('\n'.join(map(str, diff_set)))
        # print(diff_set)

        length = len(df_all_org['CIDR'].unique())
        logger.info('整合五大 RIR IP-Org 映射完成')
        res_path = os.path.join(self.org_entity_data_path, 'ip_org_mapping.csv')
        logger.info(f'映射 IP 前缀数量: {length}，正在写入文件: {res_path}')
        df_all_org.to_csv(res_path, index=False)
