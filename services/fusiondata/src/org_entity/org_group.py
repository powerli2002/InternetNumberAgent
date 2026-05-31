'''
通过 opq_id 与 CAIDA 数据结合生成组织机构映射
depacated: 该代码已经废弃，使用 org_as.py 代替

'''

from fusiondata.src import BaseEntity
from fusiondata.src.utils.logging_manager import logger

import os
import uuid

import pandas as pd
from ast import literal_eval


def solve_members(x):
    if x and not pd.isnull(x):
        df = pd.json_normalize(literal_eval(x))
        return list(map(int, df['node.asn'].tolist()))
    else:
        return []


class OrgGroup(BaseEntity):
    def __init__(self,  date: str, config_path='conf/config.yaml', enable_DB=True):
        super().__init__(config_path, date, enable_DB)
        self.target_dir = os.path.join(self.target_dir, 'format')

    def run(self):
        logger.info('Start to group org.')
        df_caida = self.get_caida_org_explode()
        logger.info('Finish getting caida org data.')
        # df_caida = pd.read_csv(os.path.join(self.target_dir, 'caida_org_explode.csv'))
        df_group = self.group_opq_org(df_caida)
        logger.info('Finish grouping opq org.')
        df_classify = self.generate_sibling_and_org_name(df_group, df_caida)
        logger.info('Finish generating sibling_as and org_name.')
        # df_classify = pd.read_csv(os.path.join(self.target_dir, 'opq_org_group_with_name_and_sibling.csv'))
        df_final = self.final_result(df_classify)
        logger.info('Finish final grouping. Writing to file...')
        res_path = os.path.join(self.target_dir, 'new_org_result.csv')
        df_final.to_csv(res_path, index=False)
        logger.info(f'Finish writing to file: {res_path}')

    def get_caida_org_explode(self) -> pd.DataFrame:
        '''
        从 caida 数据中获取 org 信息，爆炸成 asn-org 一对一的形式

        '''
        df_caida = pd.read_csv(os.path.join(self.caida_dir, 'org_data.csv'),
                               usecols=['orgId', 'orgName', 'rank', 'country.iso', 'members.asns.edges'], keep_default_na=False)
        df_caida.rename(columns={'orgId': 'org_id', 'orgName': 'org_name', 'country.iso': 'country',
                        'rank': 'org_rank',  'members.asns.edges': 'sibling_as'}, inplace=True)
        df_caida['sibling_as'] = df_caida['sibling_as'].apply(solve_members).copy()
        df_caida = df_caida.explode('sibling_as')
        df_caida.rename(columns={'sibling_as': 'asn'}, inplace=True)

        df_source = pd.read_csv(os.path.join(self.format_dir, self.date, 'asn.csv'),
                                dtype={'asn': int}, keep_default_na=False)

        df = pd.merge(df_source, df_caida, on='asn', how='left')
        df['country'] = df['country_x'].fillna(df['country_y']).fillna('ZZ')
        df.drop(columns=['country_x', 'country_y'], inplace=True)

        df.to_csv(os.path.join(self.target_dir, 'caida_org_explode.csv'), index=False)

        return df

    def group_opq_org(self, df: pd.DataFrame) -> pd.DataFrame:
        '''
        对 as-org 一对一数据进行分析，利用递归搜索树的方法，通过 org_id 和 opq_id 两个字段进行分组

        Parameters:

            df - pd.DataFrame : as-org 一对一数据

        Returns:

            df_res - pd.DataFrame : 分组结果

        '''
        dc = df.groupby('opq_id')['org_id'].apply(lambda x: x.dropna().unique().tolist())
        dict_opq_to_org = dc.to_dict()

        dc = df.groupby('org_id')['opq_id'].apply(lambda x: x.dropna().unique().tolist())
        dict_org_to_opq = dc.to_dict()

        logger.info('Dicts are ready.')

        set_solved_opq, set_solved_org = set(), set()
        list_group_opq = []

        def search_child(key: str, opq_to_org_flag: bool) -> tuple:
            '''
            搜索树
            '''
            d = dict_opq_to_org if opq_to_org_flag else dict_org_to_opq
            solved = set_solved_org if opq_to_org_flag else set_solved_opq
            res_opq, res_org = set(), set()
            for i in d.get(key, []):
                if i not in solved:
                    if opq_to_org_flag:
                        res_org.add(i)
                    else:
                        res_opq.add(i)
                    solved.add(i)
                    search_opq, search_org = search_child(i, not opq_to_org_flag)
                    res_opq.update(search_opq)
                    res_org.update(search_org)
            return res_opq, res_org

        count = 0
        for k in dict_opq_to_org.keys():
            count += 1
            if count % 1000 == 0:
                logger.info(f'count: {count}')
            if k not in set_solved_opq:
                set_solved_opq.add(k)
                search_opq, search_org = search_child(k, True)
                search_opq.add(k)
                list_group_opq.append((list(search_opq), list(search_org)))

                # for org in dict_opq_to_org.get(k, []):
                #     opq_list = dict_org_to_opq.get(org, [])
                #     new_group.update(opq_list)
                #     set_solved_opq.update(opq_list)

        df_res = pd.DataFrame(list_group_opq, columns=['opq_id', 'org_id'])
        df_res.to_csv(os.path.join(self.target_dir, 'opq_org_group.csv'), index=False)

        return df_res

    def generate_sibling_and_org_name(self, df_group: pd.DataFrame, df_explode: pd.DataFrame) -> pd.DataFrame:
        '''
        为分组结果添加 sibling_as 和 org_name 字段

        Parameters:

            df_group - pd.DataFrame : 分组结果

            df_explode - pd.DataFrame : as-org 一对一数据

        Returns:

            df_classify - pd.DataFrame : 添加 sibling_as 和 org_name 字段后的分组结果

        '''
        df_classify = df_group.copy()

        df_classify.reset_index(inplace=True)
        df_classify.set_index('index', inplace=True)
        df_classify['sibling_as'] = None
        df_classify['org_name'] = None

        # groupby 后再查找比 isin() 快
        df_opq_group = df_explode.groupby('opq_id')
        df_org_group = df_explode.groupby('org_id')

        count = 0
        for row in df_classify.itertuples():
            count += 1
            if count % 1000 == 0:
                logger.info(f'count: {count}')
            opq_id_list = row.opq_id
            org_id_list = row.org_id

            sibling_set = set()
            for opq_id in opq_id_list:
                sibling_set.update(df_opq_group.get_group(opq_id)['asn'].tolist())
            df_classify.at[row.Index, 'sibling_as'] = list(sibling_set)
            df_classify.at[row.Index, 'sibling_as_num'] = len(sibling_set)

            list_org_df = []
            for org_id in org_id_list:
                list_org_df.append(df_org_group.get_group(org_id))

            if list_org_df:
                df_org_temp = pd.concat(list_org_df)
                # print(df_org_temp)
                # print(df_org_temp['org_name'].mode().tolist())
                df_org_temp.dropna(subset=['org_name'], inplace=True)
                df_org_temp = df_org_temp[df_org_temp['org_rank'] <= df_org_temp['org_rank'].min()]
                # print(df_org_temp)
                # print(df_org_temp['org_name'].mode().tolist())
                try:
                    df_classify.at[row.Index, 'org_name'] = df_org_temp['org_name'].mode().tolist()[0]
                except IndexError:
                    logger.error('IndexError!')
                    logger.error(pd.concat(list_org_df))
                    df_classify.at[row.Index, 'org_name'] = None

        def merge_list(x):
            res = set()
            for sublist in x:
                res.update(sublist)
            return list(res)

        # 去除重复的 org_name，保证相同的 org_name 对应的 sibling_as 一致
        # df_classify['opq_id'] = df_classify['opq_id'].apply(lambda x: x if pd.isna(x) else literal_eval(x))
        # df_classify['org_id'] = df_classify['org_id'].apply(lambda x: x if pd.isna(x) else literal_eval(x))
        # df_classify['sibling_as'] = df_classify['sibling_as'].apply(lambda x: x if pd.isna(x) else literal_eval(x))
        df_classify['org_name'] = df_classify['org_name'].str.replace(',', '')

        df_classify = df_classify.groupby('org_name').agg({'opq_id': merge_list,
                                                           'org_id': merge_list,
                                                           'sibling_as': merge_list}).reset_index()

        df_classify['uuid'] = None
        df_classify['uuid'] = df_classify['org_name'].apply(lambda x: uuid.uuid5(uuid.NAMESPACE_DNS, str(x)).hex)

        df_classify.to_csv(os.path.join(self.target_dir, 'opq_org_group_with_name_and_sibling.csv'), index=False)
        return df_classify

    def final_result(self, df_classify: pd.DataFrame) -> pd.DataFrame:
        '''
        生成最终结果

        Parameters:

            df_classify - pd.DataFrame : 添加 sibling_as 和 org_name 字段后的分组结果

        Returns:

            df - pd.DataFrame : 最终结果

        '''

        df = df_classify.copy()
        df.groupby('sibling_as')['uuid'].apply(lambda x: str(x.dropna().unique()))

        df_org_cn = pd.read_csv(os.path.join('data', 'input', 'as_translate.csv'),
                                usecols=['org_name', 'org_name_cn'])
        df_org_cn.drop_duplicates(subset=['org_name'], inplace=True)
        df_org_cn.dropna(inplace=True)
        df = pd.merge(df, df_org_cn, on='org_name', how='left')

        df['asn'] = df['sibling_as'].apply(lambda x: x if pd.isna(x) else literal_eval(x))
        df = df.explode('asn')
        df = df[df['asn'].notna()]
        df = df.drop(columns=['opq_id', 'org_id'])
        # df.info()
        length = len(df['asn'].unique())
        logger.info(f'as 数量: {length}')

        return df
