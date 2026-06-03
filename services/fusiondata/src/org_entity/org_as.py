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


class OrgAS(BaseEntity):
    def __init__(self, date: str, config_path='conf/config.yaml', enable_DB=True):
        super().__init__(config_path, date, enable_DB)
        self.target_dir = os.path.join(self.target_dir, 'format')
        self.org_entity_data_path = './fusiondata/data/org_entity/'
        self.rir_list = ['arin', 'apnic', 'ripe', 'lacnic', 'afrinic']

        asn_path = os.path.join(self.format_dir, self.date, 'asn.csv')
        df_asn = pd.read_csv(asn_path, dtype={'asn': int}, keep_default_na=False)
        df_asn = df_asn[(df_asn['status'] == 'allocated') | (df_asn['status'] == 'assigned')].copy()
        df_asn.dropna(subset=['country'], inplace=True)
        self.df_asn = df_asn[(df_asn['country'] != 'ZZ') & (df_asn['country'] != '')]

    def __goup_df_by_handle(self, df: pd.DataFrame, type: str, taget_asn: list = None) -> Tuple[pd.DataFrame, set]:
        '''
        通过 handle 分组

        Parameters:

            df: pd.DataFrame RDAP/Whois 数据

            type: str 数据类型

            taget_asn: list 目标 AS

        Returns:

            df: pd.DataFrame 分组后的数据

            sloved_asn: set 已处理的 AS

        '''

        type = type.lower()
        if type == 'org':
            df = df[(df['orginType'] == 'asn') & ((df['curType'] == 'registrant')
                                                  | (df['curType'] == 'org')) & (df['kind'] == 'org')].copy()
        elif type == 'irt':
            df = df[(df['orginType'] == 'asn') & (df['curType'] == 'abuse')].copy()
        elif type == 'admin':
            df = df[(df['orginType'] == 'asn') & (df['curType'] == 'administrative')].copy()
        else:
            raise TypeError(f'Error data type: {type}')

        if taget_asn:
            df = df[df['orginHandle'].isin(taget_asn)]

        sloved_asn = set()

        def agg_slove(x: pd.Series):
            res = set()

            for s in x.values.tolist():
                assert isinstance(s, str)
                s = s.strip().upper()
                if s.startswith('AS'):
                    if '-' in s:
                        temp = s.split('-')
                        start = int(temp[0].split('AS')[-1])
                        end = int(temp[-1].split('AS')[-1])
                        res.update(range(start, end + 1))
                    else:
                        res.add(int(s.split('AS')[-1]))
                else:
                    res.add(int(s))

            sloved_asn.update(res)

            return res

            # if x.str.contains('AS').all():
            #     return x.sum()
            # else:
            #     return 'AS'.join(x.values.tolist())

        df = df.groupby('handle').agg(
            {
                'name': 'first',
                'descr': 'first',
                'address': 'first',
                'tel': 'first',
                'fax': 'first',
                'email': 'first',
                'kind': 'first',
                'lacnic_legalRepresentative': 'first',
                'self': 'first',
                'alternate': 'first',
                'up': 'first',
                'registrationDate': 'first',
                'lastChangeDate': 'first',
                'country': 'first',
                'orginHandle': agg_slove
            }
        ).reset_index()

        # ['AS141170', 'AS142650 - AS143673']

        df.rename(columns={'orginHandle': 'sibling'}, inplace=True)
        df['sibling_num'] = df['sibling'].apply(lambda x: len(x))
        df.sort_values('sibling_num', inplace=True, ascending=False)
        df.drop_duplicates(subset=['handle'], inplace=True)

        return df, sloved_asn

    def __run(self, df_asn: pd.DataFrame, df_rir_rdap: pd.DataFrame, rir: str) -> Tuple[pd.DataFrame, set]:
        '''
        通过 AS 的 Whois 与 RDAP 数据生成组织机构映射 (org_handle)

        Parameters:

            df_asn: pd.DataFrame AS delegation 数据

            df_rir_rdap: pd.DataFrame RIR RDAP 数据

            rir: str RIR 名称

        Returns:

            df_org: pd.DataFrame AS-Org 映射数据

            diff_set: set 未处理的 AS

        '''
        # 把带有 - 的 AS 集合处理成单个 AS
        df_rir_rdap = df_rir_rdap[df_rir_rdap['orginType'] == 'asn'].copy()
        df_rdap_set = df_rir_rdap[df_rir_rdap['orginHandle'].str.contains('-')]
        df_rir_rdap = df_rir_rdap.drop(df_rdap_set.index).copy()
        # 在 AS 范围块中可能存在已经分配的 AS，需要去除
        exist_as = df_rir_rdap['orginHandle'].unique().tolist()
        exist_as = {int(i.split('AS')[-1])for i in exist_as if i.startswith('AS')}

        def solve_as_set(x):
            as_list = x.split('-')
            start = int(as_list[0].split('AS')[-1])
            end = int(as_list[-1].split('AS')[-1])
            res_set = set(range(start, end + 1))
            res_set -= exist_as
            res = [f'AS{i}' for i in res_set]
            return res

        df_rdap_set['orginHandle'] = df_rdap_set['orginHandle'].apply(solve_as_set).copy()
        df_rdap_set = df_rdap_set.explode('orginHandle')
        df_rir_rdap = pd.concat([df_rir_rdap, df_rdap_set])

        # 通过组织机构 handle 分组
        df_org, sloved_asn = self.__goup_df_by_handle(df_rir_rdap, type='org')
        # print(rir)
        # print(len(sloved_asn))
        df_org['index'] = df_org['handle']
        df_org.set_index('index', inplace=True)
        logger.info(f'利用 org handle 处理的 AS 数量: {len(sloved_asn)}')

        target_rir = rir if rir != 'ripe' else 'ripencc'
        df_rir = df_asn[df_asn['source'] == target_rir].copy()
        target_set = set(df_rir['asn'].to_list())
        diff_set = target_set - sloved_asn

        df_org.drop_duplicates(subset=['handle'], inplace=True)
        df_org.sort_values('sibling_num', ascending=False, inplace=True)

        return df_org, diff_set

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

        def get_org_mail_key(x):
            if not isinstance(x, set):
                return None
            df_temp = df_mail_key[df_mail_key['asn'].isin(x)].copy()

            res = df_temp['org_email_key'].explode().dropna().drop_duplicates().sort_values().tolist()

            if len(res) == 0:
                return None

            return res

        logger.info(f'为 {rir} 组织机构添加 org_mail_key 列')
        df_org_res['org_mail_key'] = df_org_res['sibling'].apply(get_org_mail_key)

        df_org_res = df_org_res[['handle', 'sibling', 'org_mail_key']]
        df_org_res.rename(
            columns={'sibling': 'asn', 'handle': 'org_handle'}, inplace=True)

        df_without_org_mail = df_org_res[df_org_res['org_mail_key'].isna()].copy()

        df_with_org_mail = df_org_res[df_org_res['org_mail_key'].notna()].copy()
        df_with_org_mail['org_mail_key'] = df_with_org_mail['org_mail_key'].apply(lambda x: '|'.join(x))
        if rir == 'apnic':
            # 手动归并中国教育网的 CERNET 与 CERNIC
            df_with_org_mail['org_mail_key'] = df_with_org_mail['org_mail_key'].str.replace('cernet', 'cernic')
            df_with_org_mail['org_handle'] = df_with_org_mail['org_handle'].str.replace('ORG-CNTC2-AP', 'ORG-CEAR1-AP')
        df_with_org_mail['asn_num'] = df_with_org_mail['asn'].apply(lambda x: len(x))
        df_with_org_mail.sort_values(by='asn_num', ascending=False, inplace=True)

        def set_sum(x: pd.Series):
            res = set()
            for i in x.values.tolist():
                if isinstance(i, set):
                    res.update(i)
            return res

        df_res_with_org_mail = df_with_org_mail.groupby('org_mail_key', as_index=False).agg(
            {
                # 先前通过 AS 数量排序，这里直接取第一个即为 AS 数量最多的 org_handle
                'org_handle': 'first',
                'asn': set_sum
            }
        )

        df_res = pd.concat([df_res_with_org_mail, df_without_org_mail])
        df_res['org_mail_key'] = df_res['org_mail_key'].apply(
            lambda x: set(x.split('|')) if isinstance(x, str) else None)
        df_res['asn_num'] = df_res['asn'].apply(lambda x: len(x))
        df_res.sort_values(by='asn_num', ascending=False, inplace=True)

        logger.info(f'已利用 org mail key 初步聚类 {rir} 组织机构')

        return df_res

    def __merge_unsloved_asn_by_mail_key(self, df_mail_key: pd.DataFrame, target_asn: set, rir: str, target_country: str = None) -> Tuple[pd.DataFrame, set]:
        '''
        为没有 org_handle 的 AS 利用联系人的 mail_key 进行聚类

        '''
        if rir not in self.rir_list:
            raise ValueError(f'Error rir: {rir}')

        mail_key_dict = dict()
        unsloved_asn = set()

        df_mail = df_mail_key[df_mail_key['asn'].isin(target_asn)].copy()
        if target_country:
            df_mail = df_mail[df_mail['country'] == target_country]

        for row in tqdm(df_mail.itertuples(), total=len(df_mail), desc=f'Merging {rir} unsloved asns by mail key...'):
            tech_email = [i.lower() for i in row.tech_email_key] if isinstance(row.tech_email_key, list) else []
            admin_email = [i.lower() for i in row.admin_email_key] if isinstance(row.admin_email_key, list) else []
            tech_email_set = set(tech_email)
            admin_email_set = set(admin_email) 
            # tech 更能代表 AS 的归属方 技术联系人
            # 但存在拥有非常多 tech 的 AS 的情况（mail key阈值 5），此时 admin 则更有代表性  管理员联系人
            if len(tech_email_set) > 0 and len(tech_email_set) < 5:
                mixed_mail_set = tech_email_set
            else:
                mixed_mail_set = admin_email_set

            if len(mixed_mail_set) == 0:
                unsloved_asn.add(row.asn)
            else:
                target_asn_set = set([row.asn])
                target_key = mixed_mail_set
                key_to_pop = []
                for key in mail_key_dict.keys():
                    key_set = set(key)
                    same_set = key_set & mixed_mail_set
                    if len(same_set) > 0:
                        target_asn_set.update(mail_key_dict.get(key).get('asn'))
                        target_key = key_set | target_key
                        key_to_pop.append(key)
                for key in key_to_pop:
                    mail_key_dict.pop(key)

                mail_key_dict[tuple(target_key)] = {'asn': target_asn_set, 'key_set': target_key}

        mail_key_dict = {'|'.join(k): v for k, v in mail_key_dict.items()}

        df_res = pd.DataFrame.from_dict(mail_key_dict, orient='index')

        return df_res, unsloved_asn

    def __merge_unsloved_asn_to_org_handle(self, df_org_handle: pd.DataFrame, df_unslove_asn: pd.DataFrame, rir: str) -> Tuple[pd.DataFrame, list]:

        unsloved_asn_list = []
        df_res = df_org_handle.copy()

        logger.info(f'通过 mail_key 合并未处理的 AS 到已处理的 org_handle 中, 待处理的 AS 数量: {len(df_unslove_asn)}')

        for row in tqdm(df_unslove_asn.itertuples(), total=len(df_unslove_asn), desc=f'Merging {rir} unsloved asns to org handle...'):
            mixed_mail_set = row.key_set if isinstance(row.key_set, set) else set()

            if len(mixed_mail_set) == 0:
                unsloved_asn_list.append(row.asn)
            else:
                find_org_flag = False
                find_org_idx = None
                for org_row in df_res.itertuples():
                    if not isinstance(org_row.org_mail_key, set):
                        continue

                    if org_row.org_mail_key == mixed_mail_set:
                        df_res.at[org_row.Index, 'asn'].update(row.asn)
                        break
                    elif not find_org_flag:
                        same_set = org_row.org_mail_key & mixed_mail_set
                        if len(same_set) > 0:
                            find_org_idx = org_row.Index
                            find_org_flag = True
                else:
                    if find_org_flag:
                        df_res.at[find_org_idx, 'asn'].update(row.asn)
                    else:
                        unsloved_asn_list.append(row.asn)
        df_res['asn_num'] = df_res['asn'].apply(lambda x: len(x))
        df_res.sort_values(by='asn_num', ascending=False, inplace=True)

        logger.info('合并未处理的 AS 到已处理的 org_handle 完成')
        return df_res, unsloved_asn_list

    def __final_merge(self, df_org_handle_info: pd.DataFrame, df_org_handle_data: pd.DataFrame, rest_asns: list, rest_asn_lsit: list, df_as_info: pd.DataFrame, rir: str) -> pd.DataFrame:
        '''
        最后整合 RIR 的所有组织机构数据

        Parameters:

            df_org_handle_info: pd.DataFrame 组织机构信息，由 self.__run 生成

            df_org_handle_data: pd.DataFrame 组织机构数据，由 self.__merge_unsloved_asn_to_org_handle 生成

            rest_asns: list 未处理的 AS，由 self.__merge_unsloved_asn_by_mail_key 生成

            rest_asn_lsit: list 未处理的 AS，由 self.__merge_unsloved_asn_to_org_handle 生成

            df_as_info: pd.DataFrame AS 信息，读取自 {rir}_as_info_with_mail_key.csv

            rir: str RIR 名称

        Returns:

            df_res: pd.DataFrame 整合后的组织机构数据

        '''
        df_org_info = df_org_handle_info[['handle', 'name', 'descr', 'address', 'tel',
                                          'fax', 'email', 'country']].copy()
        df_org_data = df_org_handle_data[['org_handle', 'asn', 'asn_num']].rename(
            {'org_handle': 'handle', 'asn': 'sibling', 'asn_num': 'sibling_num'}, axis=1)

        df_as_info = df_as_info[['asn', 'country', 'as_name', 'descr',
                                 'admin_phone', 'admin_email', 'tech_phone', 'tech_email']].copy()
        df_as_info['index'] = df_as_info['asn']
        df_as_info.set_index('index', inplace=True)

        logger.info(f'最后整合 {rir} 的所有组织机构数据')

        df_res = pd.merge(df_org_info, df_org_data, on='handle', how='left')
        df_res['sibling'] = df_res['sibling'].apply(lambda x: list(x) if isinstance(x, set) else [])

        data_list = []

        for asn_set in rest_asn_lsit:
            asn_list = list(asn_set)

            as_info_dict = df_as_info.loc[asn_list[0]].to_dict()

            as_descr = as_info_dict.get('descr')
            if isinstance(as_descr, str):
                as_name = as_descr.split('|')[0]
            else:
                as_name = as_info_dict.get('as_name')
            as_tel = as_info_dict.get('admin_phone')
            if as_tel is None:
                as_tel = as_info_dict.get('tech_phone')
            as_email = as_info_dict.get('admin_email')
            if as_email is None:
                as_email = as_info_dict.get('tech_email')
            as_country = as_info_dict.get('country')

            data_list.append({'handle': None, 'name': as_name,
                              'descr': as_descr, 'address': None, 'tel': as_tel,
                              'fax': None, 'email': as_email,
                              'country': as_country, 'sibling': asn_list, 'sibling_num': len(asn_list)})

        for asn in rest_asns:
            as_info_dict = df_as_info.loc[asn].to_dict()

            as_descr = as_info_dict.get('descr')
            if isinstance(as_descr, str):
                as_name = as_descr.split('|')[0]
            else:
                as_name = as_info_dict.get('as_name')
            as_tel = as_info_dict.get('admin_phone')
            if as_tel is None:
                as_tel = as_info_dict.get('tech_phone')
            as_email = as_info_dict.get('admin_email')
            if as_email is None:
                as_email = as_info_dict.get('tech_email')
            as_country = as_info_dict.get('country')

            data_list.append({'handle': None, 'name': as_name,
                              'descr': as_descr, 'address': None, 'tel': as_tel,
                              'fax': None, 'email': as_email,
                              'country': as_country, 'sibling': [asn], 'sibling_num': 1})

        df_extra = pd.DataFrame(data_list)
        df_res = pd.concat([df_res, df_extra])

        def get_nona_handle(x: pd.Series):
            x = x.dropna()
            if x.empty:
                return None
            else:
                return x.values[0]

        df_extra_grouped = df_res.groupby('name').agg(
            {
                'handle': get_nona_handle,
                'descr': get_nona_handle,
                'address': get_nona_handle,
                'tel': get_nona_handle,
                'fax': get_nona_handle,
                'email': get_nona_handle,
                'country': get_nona_handle,
                'sibling': 'sum',
            }
        )
        df_extra_grouped['name'] = df_extra_grouped.index
        df_extra_grouped['sibling'] = df_extra_grouped['sibling'].apply(lambda x: list(set(x)))
        df_extra_grouped['sibling_num'] = df_extra_grouped['sibling'].apply(lambda x: len(x))
        df_extra_grouped.sort_values(by='sibling_num', ascending=False, inplace=True)

        return df_extra_grouped

    def run(self):

        rir_list = self.rir_list
        # rir_list = ['apnic']
        df_asn = self.df_asn
        list_df_org = []

        for rir in rir_list:
            logger.info(f'处理 {rir} 组织机构数据')

            target_path = os.path.join(self.org_entity_data_path, rir)

            if not os.path.exists(target_path):
                os.mkdir(target_path)

            rdap_path = os.path.join(self.format_dir, self.date, rir, f'{rir}_as_entity_rdap_info.csv')
            df = pd.read_csv(rdap_path)
            df.dropna(subset=['name'], inplace=True)

            df_org, unsloved_asn = self.__run(df_asn, df, rir)
            # list_df_org.append(df_org)
            logger.info(f'利用 org handle 初步聚类 {rir} 组织机构，未处理的 AS 数量: {len(unsloved_asn)}')

            df_as_mail_key = pd.read_csv(os.path.join(
                target_path, f'{rir}_as_info_with_mail_key.csv'), dtype={'asn': int})
            df_as_mail_key.drop_duplicates(subset=['asn'], inplace=True)

            df_as_mail_key['org_email_key'] = df_as_mail_key['org_email_key'].apply(
                lambda x: literal_eval(x) if pd.notna(x) else [])
            df_as_mail_key['admin_email_key'] = df_as_mail_key['admin_email_key'].apply(
                lambda x: literal_eval(x) if pd.notna(x) else [])
            df_as_mail_key['tech_email_key'] = df_as_mail_key['tech_email_key'].apply(
                lambda x: literal_eval(x) if pd.notna(x) else [])

            df_org_handle_group = self.__append_mail_key_col(df_org, df_as_mail_key, rir)
            df_org_handle_group.to_csv(os.path.join(target_path, f'{rir}_org_handle_group.csv'), index=False)
            df_unslove_mail_group, rest_asn = self.__merge_unsloved_asn_by_mail_key(df_as_mail_key, unsloved_asn, rir)
            df_unslove_mail_group.to_csv(os.path.join(target_path, f'{rir}_unslove_mail_group.csv'), index=False)
            logger.info(f'利用 mail key 进一步聚类 {rir} 组织机构，无法使用 mail key 处理的 AS 数量: {len(rest_asn)}')

            df_merged, rest_asn_list = self.__merge_unsloved_asn_to_org_handle(
                df_org_handle_group, df_unslove_mail_group, rir)
            df_merged.to_csv(os.path.join(target_path, f'{rir}_merged_org_handle_group.csv'), index=False)
            logger.info(f'利用 mail key 将未处理的 AS 聚类到 {rir} 组织机构')

            df_rir_res = self.__final_merge(df_org, df_merged, rest_asn, rest_asn_list, df_as_mail_key, rir)
            list_df_org.append(df_rir_res)
            df_rir_res.to_csv(os.path.join(target_path, f'{rir}_final_merged.csv'), index=False)

            logger.info(f'{rir} 组织机构数据处理完成 \n')
        # return
        logger.info('整合五大 RIR Org 映射')

        df_all_org = pd.concat(list_df_org)
        df_all_org.rename(columns={'name': 'org_name'}, inplace=True)

        df_org_cn = pd.read_csv(os.path.join(self.static_data_path, 'org_translate.csv'),
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

        def solve_sibling(x: pd.Series):
            res = set()
            for s in x.values.tolist():
                res.update(s)
            return res

        # 这一步能把重复的 org_name 合并
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
                'sibling': solve_sibling,
                'org_name_cn': 'first'
            }
        ).reset_index()

        df_org_only = df_all_org[['uuid', 'org_name', 'descr']].copy()
        df_org_only.drop_duplicates(subset=['uuid'], inplace=True)
        df_org_only.to_csv(os.path.join(self.org_entity_data_path, 'org_only.csv'), index=False)

        df_all_org['sibling_num'] = df_all_org['sibling'].apply(lambda x: len(x))
        df_all_org['asn'] = df_all_org['sibling'].copy()
        df_all_org = df_all_org.explode('asn')
        df_all_org = df_all_org[df_all_org['asn'].notna()]

        df_all_org['sibling'] = df_all_org['sibling'].apply(lambda x: list(x))
        df_all_org['handle'] = df_all_org['handle'].apply(lambda x: list(x))

        all_as_set = set(df_asn['asn'].tolist())
        grouped_as_set = set(df_all_org['asn'].tolist())
        diff_set = all_as_set - grouped_as_set

        fail_path = os.path.join(self.org_entity_data_path, 'unsolved_as.txt')
        logger.info(f'无法处理的 AS 数量: {len(diff_set)}，已写入 {fail_path}')
        with open(fail_path, 'w') as f:
            f.write('\n'.join(map(str, diff_set)))
        # print(diff_set)

        length = len(df_all_org['asn'].unique())
        logger.info('整合五大 RIR AS-Org 映射完成')
        res_path = os.path.join(self.org_entity_data_path, 'as_org_mapping.csv')
        logger.info(f'映射 AS 数量: {length}，正在写入文件: {res_path}')
        df_all_org.to_csv(res_path, index=False)
