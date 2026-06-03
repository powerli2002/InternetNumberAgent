from fusiondata.src.utils.logging_manager import logger
from fusiondata.src import BaseEntity

import os
import re
import json
from ast import literal_eval

import pandas as pd


class ASEntityFormatter(BaseEntity):
    def __init__(self,  date: str, config_path='conf/config.yaml', enable_DB=True):
        '''
        AS 实体格式化工具

        Parameters:

            date - 日期，格式为 YYYY-MM-DD。请注意，本类将根据该日期读取相应的数据文件（包括但不限于 RIR 文件等），因此可能需要根据数据需求自行更改而不是直接使用当前日期。

            config_path - 配置文件路径

            enable_DB - 是否启用数据库

        '''
        super().__init__(config_path, date, enable_DB)

        self.df_ddos_as = pd.read_csv(os.path.join(self.static_data_path, 'ddos_as.csv'),
                                      dtype={'aut-num': int}, keep_default_na=False)
        self.df_delegate_asn = pd.read_csv(f'{self.format_dir}{self.date}/asn.csv',
                                           dtype={'asn': int, 'source': str, 'country': str,
                                                  'status': str, 'opq_id': str, 'date': str},
                                           usecols=['asn', 'source', 'country', 'status', 'opq_id', 'date'], keep_default_na=False)
        self.df_delegate_asn['source'] = self.df_delegate_asn['source'].apply(lambda x: 'ripe' if x == 'ripencc' else x)

    def run(self, base_info_only=False):
        '''
        运行 AS 字典处理器

        Parameters:

            base_info_only: bool, 是否只输出基本信息，若为 False，则将加载 RIB 路由表数据并导入 AS 基本信息

        Returns:

            None

        '''
        logger.info('开始运行 AS 字典处理器')
        target_df = self.__base_as_info()
        target_df = self.__as_contacts_info(target_df)
        logger.info('正在获取 AS 路由导入/导出规则')
        df_import_export = self.get_as_import_export_info()
        logger.info('获取 AS 路由导入/导出规则完成，合并至 AS 基本信息')
        target_df = pd.merge(target_df, df_import_export, on='asn', how='left')

        logger.info('开始导出 AS 基本信息')
        target_df.to_csv(os.path.join(self.target_dir, 'format', 'as_entity_base.csv'), index=False)

        logger.info('AS 基本信息导出完成')

        if not base_info_only:
            logger.info('开始加载 RIB 数据')
            rib_parsed_dir = os.path.join(self.target_dir, 'format')
            file_list = [f for f in os.listdir(rib_parsed_dir) if f.startswith('rib_data') and f.endswith('.csv')]
            file_list.sort(reverse=True)
            taget_file = file_list[1]
            logger.info(f'找到 RIB 数据文件 {taget_file}，开始加载')
            df_rib = pd.read_csv(os.path.join(rib_parsed_dir, taget_file), dtype={'asn': int})

            logger.info('RIB 数据加载完成')

            target_df = pd.merge(target_df, df_rib, on='asn', how='left')
            target_df['is_route'] = target_df.apply(lambda row: False if pd.isna(
                row['v4Prefixes']) and pd.isna(row['v6Prefixes']) else True, axis=1)

            target_df.to_csv(os.path.join(self.target_dir, 'format', f'as_entity_{self.date}.csv'), index=False)
            logger.info('AS 基本信息与 RIB 数据合并完成')

        logger.info('ALL DONE!')

    def __base_as_info(self) -> pd.DataFrame:
        '''
        获取 AS 基本信息

        Parameters:

            None

        Returns:

            pd.DataFrame: AS 基本信息

        '''

        logger.info('加载 DDOS AS 基本信息')
        df_ddos = self.df_ddos_as
        df_ddos['is_ddos_provider'] = True
        df_ddos.rename(columns={'aut-num': 'asn'}, inplace=True)
        df_ddos = df_ddos[['asn', 'is_ddos_provider']].copy()
        logger.info('DDOS AS 基本信息加载完成')

        # def solve_members(x):
        #     if x and not pd.isnull(x):
        #         df = pd.json_normalize(literal_eval(x))
        #         return
        #     else:
        #         return []

        logger.info('加载 CAIDA 数据')
        df_as_org = pd.read_csv(os.path.join(self.static_data_path, 'org_data.csv'),
                                usecols=['orgId', 'rank', 'country.iso'], keep_default_na=False)
        df_as_org.rename(columns={'orgId': 'org_id', 'country.iso': 'country', 'rank': 'org_rank'}, inplace=True)
        # df_as_org['sibling_as'] = df_as_org['sibling_as'].apply(solve_members).copy()
        df_as_org = self.append_country_cn_in_df(df_as_org)
        df_as_org.rename(columns={'country_cn': 'org_country_cn', 'country': 'org_country'}, inplace=True)

        df_as_rank = pd.read_csv(os.path.join(self.static_data_path, 'as_rank.csv'),
                                 usecols=['asn', 'rank', 'asnName', 'longitude', 'latitude', 'country', 'organization.orgId'], keep_default_na=False)
        df_as_rank.rename(columns={'rank': 'as_rank', 'asnName': 'as_name', 'longitude': 'as_longitude',
                          'latitude': 'as_latitude', 'organization.orgId': 'org_id', 'country': 'as_country'}, inplace=True)

        df_as_ciada = pd.merge(df_as_rank, df_as_org, on='org_id', how='left')
        df_as_ciada['index'] = df_as_ciada['asn']
        df_as_ciada.set_index('index', inplace=True)

        as_type_path = os.path.join(self.static_data_path, 'asdb.csv')
        df_as_type = pd.read_csv(as_type_path)
        logger.info('CAIDA 数据加载完成')

        logger.info('加载组织机构数据')
        # as_org_mapping 由 OrgAS 类生成
        df_opq_group = pd.read_csv(os.path.join(self.target_dir, 'org_entity', 'as_org_mapping.csv'), dtype={
                                   'asn': int}, usecols=['org_name', 'sibling', 'uuid', 'org_name_cn', 'asn'], keep_default_na=False)
        df_opq_group.rename(columns={'sibling': 'sibling_as'}, inplace=True)
        with open(os.path.join(self.static_data_path, 'org_cn_convert.json'), 'r') as f:
            org_cn_convert = json.load(f)
        for k, v in org_cn_convert.items():
            name = v.get('org_name')
            name_cn = v.get('org_name_cn')
            df_opq_group.loc[df_opq_group['uuid'] == k, 'org_name'] = name
            df_opq_group.loc[df_opq_group['uuid'] == k, 'org_name_cn'] = name_cn

        with open(os.path.join(self.static_data_path, 'org_cn_ct.txt'), 'r') as f:
            org_cn_ct = f.read().split('\n')
        for o in org_cn_ct:
            df_opq_group.loc[df_opq_group['uuid'] == o, 'org_name'] = 'China Telecom'
            df_opq_group.loc[df_opq_group['uuid'] == o, 'org_name_cn'] = '中国电信'
            df_opq_group.loc[df_opq_group['uuid'] == o, 'uuid'] = '0150451b8a7c5245942274e63b066fc9'

        logger.info('组织机构数据加载完成')

        logger.info('加载 AS 网站和描述翻译信息')
        df_web = pd.read_csv(os.path.join(self.static_data_path, 'as_translate.csv'), dtype={
                             'asn': int}, usecols=['asn', 'descr_cn',  'website'], keep_default_na=False)
        logger.info('AS 网站和描述翻译信息加载完成')

        logger.info('开始加载 RIR 数据')
        rdap_info_list = []
        for rir in self.rir_list:
            df = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_as_rdap_info.csv', usecols=[
                'handle', 'name', 'country', 'descr', 'registrant', 'administrative', 'technical', 'abuse', 'registrationDate', 'lastChangeDate'], dtype=str, keep_default_na=False)
            df['asn'] = df['handle'].apply(lambda x: int(x.split('AS')[-1].strip()))
            rdap_info_list.append(df)
        df_as_rdap = pd.concat(rdap_info_list, ignore_index=True)
        logger.info('RIR 数据加载完成')

        logger.info('开始加载 AS 地理位置数据')
        # df_as_geo = pd.read_json(f'{self.target_dir}format/as_geo_dict.json', orient='index')
        # df_as_geo['as'] = df_as_geo.index
        # df_as_geo['as'] = df_as_geo['as'].str.split(',')
        # df_as_geo = df_as_geo.explode('as').drop_duplicates('as')
        # df_as_geo['as'] = df_as_geo['as'].astype(int)
        # df_as_geo.reset_index(drop=True, inplace=True)
        # df_as_geo.rename(columns={'country': 'geo_country_list', 'country_num': 'geo_country_list_num',
        #                  'city': 'geo_city_list', 'city_num': 'geo_city_list_num', 'lat-lon': 'geo_latitude_longitude', 'lat-lon_num': 'geo_latitude_longitude_num', 'as': 'asn'}, inplace=True)
        df_as_geo = pd.read_csv(os.path.join(self.static_data_path, 'as_geo.csv'),
                                dtype={'asn': int}, keep_default_na=False)
        logger.info('AS 地理位置数据加载完成')

        # 所有文件以asn为键
        df = pd.merge(self.df_delegate_asn, df_as_rdap, on='asn', how='left')
        df = pd.merge(df, df_ddos, on='asn', how='left')
        df = pd.merge(df, df_as_ciada, on='asn', how='left')
        df = pd.merge(df, df_opq_group, on='asn', how='left')
        df = pd.merge(df, df_as_type, on='asn', how='left')
        df = pd.merge(df, df_as_geo, on='asn', how='left')
        df = pd.merge(df, df_web, on='asn', how='left')

        # 处理国家信息
        df['country'] = df['country_x'].fillna(df['country_y']).fillna(
            df['as_country']).fillna(df['org_country']).fillna('ZZ')
        df['country'].replace('', 'ZZ', inplace=True)
        df = self.append_country_cn_in_df(df)

        # 处理 DDOS 信息
        df['is_ddos_provider'] = df['is_ddos_provider'].fillna(False)

        # 处理 AS 名称
        df['descr'] = df['descr'].apply(lambda x: ' '.join(x.split('|')) if not pd.isna(x) else x)
        df['aut_name'] = df['as_name'].fillna(df['name']).fillna(df['descr'])

        df.drop(['as_country', 'country_x', 'country_y', 'as_name', 'name', 'handle'], axis=1, inplace=True)
        df.rename(columns={'country_cn': 'as_country_cn', 'country': 'as_country',
                  'registrant': 'org_handle', 'registrationDate': 'registration_date', 'lastChangeDate': 'last_change_date'}, inplace=True)

        def solve_org_handle(x):
            if not x or pd.isna(x):
                return None
            else:
                str_list = x.upper().split('|')
                if len(str_list) == 1:
                    return str_list[0]
                else:
                    for s in str_list:
                        if 'ORG' in s:
                            return s
                    return str_list[0]

        # 确保 org_handle 正确且唯一
        df['org_handle'] = df['org_handle'].apply(solve_org_handle)

        # 处理 AS 描述并补全 AS 名称
        idx = df['aut_name'].str.contains(r'^AS\d+$', case=False, na=False)
        logger.info(f'替换匹配表达式 ^AS\d+$ 的 AS 名称为其 descr ，共 {len(df.loc[idx, "aut_name"])} 条')
        df.loc[idx].to_csv(os.path.join(self.target_dir, 'diff.csv'), index=False)
        df.loc[idx, 'aut_name'] = df.loc[idx, 'descr']
        df['aut_name'] = df['aut_name'].fillna(df['org_name']).fillna(df['asn'].apply(lambda x: f'AS{x}'))

        # 更新 AS type 信息 IDC|CDN|CLOUD
        df.loc[(df['aut_name'].str.contains('IDC', case=False, na=False)) | (
            df['descr'].str.contains('IDC', case=False, na=False)), 'type'] = 'IDC'
        df.loc[(df['aut_name'].str.contains('IDC', case=False, na=False)) | (
            df['descr'].str.contains('IDC', case=False, na=False)), 'type_cn'] = '互联网数据中心'

        df.loc[(df['aut_name'].str.contains('CDN', case=False, na=False)) | (
            df['descr'].str.contains('CDN', case=False, na=False)), 'type'] = 'CDN'
        df.loc[(df['aut_name'].str.contains('CDN', case=False, na=False)) | (
            df['descr'].str.contains('CDN', case=False, na=False)), 'type_cn'] = '内容分发网络'

        df.loc[(df['aut_name'].str.contains('CLOUD', case=False, na=False)) | (
            df['descr'].str.contains('CLOUD', case=False, na=False)), 'type'] = 'Hosting and Cloud Provider'
        df.loc[(df['aut_name'].str.contains('CLOUD', case=False, na=False)) | (
            df['descr'].str.contains('CLOUD', case=False, na=False)), 'type_cn'] = '托管和云提供商'
        df['type'].fillna('Other', inplace=True)
        df['type_cn'].fillna('其他', inplace=True)

        df.sort_values(by=['as_rank'], inplace=True)
        df['index'] = df['asn']
        df.set_index('index', inplace=True)
        logger.info('AS 基本信息加载完成')

        return df

    def __as_contacts_info(self, df_as_entity: pd.DataFrame) -> pd.DataFrame:
        '''
        获取 AS 联系人信息

        Parameters:

            df_as_entity - AS 基本信息

        Returns:

            pd.DataFrame - 增加联系人信息后的 AS 信息

        '''
        logger.info('开始加载 AS 联系人信息')

        rdap_info_list = []
        for rir in self.rir_list:
            df = pd.read_csv(f'{self.format_dir}{self.date}/{rir}/{rir}_as_entity_rdap_info.csv', usecols=[
                'handle', 'name', 'tel', 'email', 'fax', 'descr', 'address'], dtype=str, keep_default_na=False)
            rdap_info_list.append(df)

        df_as_contacts = pd.concat(rdap_info_list, ignore_index=True)
        df_as_contacts.drop_duplicates(subset=['handle'], inplace=True)
        df_as_contacts['index'] = df_as_contacts['handle']
        df_as_contacts.set_index('index', inplace=True)

        def solve_contacts_info(x):
            if x and not pd.isna(x):
                contacts_list = str(x).strip().split('|')
                res_list = []
                for c in contacts_list:
                    try:
                        d = df_as_contacts.loc[c].fillna('')
                    except KeyError:
                        continue
                    res_list.append(d)
                if res_list:
                    df = pd.DataFrame(res_list)
                    return df.to_json(orient='records')

            return None

        # def solve_asn_contacts_info(x):
        #     if x and not pd.isna(x):
        #         df = df_as_contacts[df_as_contacts['asn'] == int(x)].drop_duplicates(
        #             subset=['handle']).drop(['asn', 'handle'], axis=1).fillna('')
        #         df = df.loc[df.index.notna()]
        #         info = df.to_dict('index')
        #         return info
        #     else:
        #         return None

        logger.info('开始处理 AS 联系人信息')
        df_as_entity['admin_info'] = df_as_entity['administrative'].apply(solve_contacts_info)
        logger.info('AS 管理员信息处理完成')
        df_as_entity['tech_info'] = df_as_entity['technical'].apply(solve_contacts_info)
        logger.info('AS 技术员信息处理完成')
        df_as_entity['abuse_info'] = df_as_entity['abuse'].apply(solve_contacts_info)
        logger.info('AS 投诉信息处理完成')

        # df_as_entity['contacts_info'] = df_as_entity['asn'].apply(solve_asn_contacts_info)

        logger.info('AS 联系人信息处理完成')

        return df_as_entity

    def get_as_import_export_info(self) -> pd.DataFrame:
        '''
        获取 AS import export 信息

        Returns:

            pd.DataFrame - AS import export 信息

        '''

        # lacnic 无 import export 信息
        rir_list = ['apnic', 'ripe', 'afrinic', 'arin']
        col_list = ['aut-num',  'import', 'export', 'mp-import', 'mp-export']
        ext_col_list = ['import-via', 'export-via']

        aut_num_list = []
        for rir in rir_list:
            target_col_list = col_list if rir != 'apnic' and rir != 'ripe' else col_list + ext_col_list
            data_path = os.path.join(self.format_dir, self.date, rir,  f'{rir}_aut-num_whois_info.csv')
            df = pd.read_csv(data_path, usecols=target_col_list, dtype=str, keep_default_na=False)
            aut_num_list.append(df)

        data_col = ['import', 'export', 'mp-import', 'mp-export', 'import-via', 'export-via']
        df_as_route = pd.concat(aut_num_list, ignore_index=True)
        df_as_route.dropna(subset=data_col, how='all', inplace=True)
        df_as_route.drop_duplicates(subset=['aut-num'], inplace=True)

        df_as_route['asn'] = df_as_route['aut-num'].apply(lambda x: int(x.upper().split('AS')[-1]))

        pattern_asn = re.compile(r'(AS\d+)')
        pattern_prefix = re.compile(r'(\{.+\})')

        def solve_col(x):
            if pd.isna(x):
                return x
            return ' '.join(x.split('|')).upper()

        def solve_import_export(import_flag: bool, x):
            if pd.isna(x):
                return []
            res = []
            if import_flag:
                line_split = 'FROM'
                data_split = 'ACCEPT'
            else:
                line_split = 'TO'
                data_split = 'ANNOUNCE'

            data_list = x.split(line_split)
            for data in data_list:
                if not data or data_split not in data:
                    continue
                pre, after = data.strip().split(data_split, 1)

                # 处理 import 来源
                search_source_as = pattern_asn.search(pre)
                if not search_source_as:
                    if 'ANY' in pre:
                        source_as = 'AS-ANY'
                    else:
                        continue
                else:
                    source_as = search_source_as.group()

                # 处理 import 目标
                target_as_list = []
                # 不使用正则表达式，因为有些 AS 不是通过 AS 号码来表示的，比如 AS-MYMANGA
                list_target_as = after.strip().split(' ')
                for i in range(len(list_target_as)):
                    item = list_target_as[i]
                    search_target_prefix = pattern_prefix.search(item)
                    if item.startswith('AS'):
                        # 有些 AS 有 AS 号码，但会带着其他字符，比如 AS12491:AS-IPPLANET
                        # 此时需要将其他字符去掉
                        search_target_as = pattern_asn.search(item)
                        if search_target_as:
                            item = search_target_as.group()

                        if i > 0 and list_target_as[i - 1] == 'NOT':  # 如果前一个是 NOT，那么这个 AS 是排除的
                            item = f'NOT {item}'
                        target_as_list.append(item)
                        continue

                    # 路由策略也有可能针对前缀而非 AS 号码
                    search_target_prefix = pattern_prefix.search(item)
                    if search_target_prefix:
                        item = search_target_prefix.group()
                        if i > 0 and list_target_as[i - 1] == 'NOT':  # 如果前一个是 NOT，那么这个 AS 是排除的
                            item = f'NOT {item}'
                        target_as_list.append(item)

                if not target_as_list and 'ANY' in after:
                    target_as_list.append('AS-ANY')

                single_res = {line_split: source_as, data_split: target_as_list}
                res.append(single_res)
            return res

        for col in data_col:
            df_as_route[col] = df_as_route[col].apply(solve_col)

        df_import = df_as_route[['import', 'import-via', 'mp-import']]
        df_import = df_import.fillna('').copy()
        df_as_route['import'] = df_import.apply(lambda x: ' '.join(x), axis=1)

        df_export = df_as_route[['export', 'export-via', 'mp-export']]
        df_export = df_export.fillna('').copy()
        df_as_route['export'] = df_export.apply(lambda x: ' '.join(x), axis=1)

        df_as_route['import'] = df_as_route['import'].apply(lambda x: solve_import_export(True, x)).copy()
        df_as_route['import_as'] = df_as_route['import'].apply(lambda x: [item['FROM'] for item in x]).copy()
        df_as_route['export'] = df_as_route['export'].apply(lambda x: solve_import_export(False, x)).copy()
        df_as_route['export_as'] = df_as_route['export'].apply(lambda x: [item['TO'] for item in x]).copy()

        df_as_route.drop(columns=['import-via', 'mp-import', 'export-via', 'mp-export', 'aut-num'], inplace=True)
        # 删除 import 和 export 都为空列表的行
        df_as_route.drop(df_as_route[(df_as_route['import'].str.len() == 0) &
                                     (df_as_route['export'].str.len() == 0)].index, inplace=True)
        df_as_route.reset_index(drop=True, inplace=True)

        return df_as_route
