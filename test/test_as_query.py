import pandas as pd
import os

df_source = pd.read_csv('/home/back_data/rirdata/data/format/2023-07-18/asn.csv',
                        usecols=['asn', 'opq_id'], dtype={'asn': int})
# len_group = len(df_source.groupby('opq_id'))
# print(len_group)
# df_source = df_source[df_source['opq_id'] == 'A914EAE4']

df = pd.read_csv('/home/back_data/fusionprocessing/data/format/as_entity_2023-07-06.csv', usecols=[
                 'asn', 'aut_name', 'descr', 'as_country', 'as_country_cn', 'as_rank', 'org_id', 'org_name', 'org_rank'], dtype={'asn': int, 'org_id': str})

df = pd.merge(df, df_source, on='asn', how='left')

xiaoniu_df_list = []
for f in os.listdir('/home/back_data/fusionprocessing/test/data/result/国家AS信息/'):
    df_temp = pd.read_csv(
        f'/home/back_data/fusionprocessing/test/data/result/国家AS信息/{f}', usecols=['asn', 'descr_xiaoniu'], dtype={'asn': int})
    xiaoniu_df_list.append(df_temp)
df_xiaoniu_as = pd.concat(xiaoniu_df_list, ignore_index=True)

df = pd.merge(df, df_xiaoniu_as, on='asn', how='left')

xiaoniu_df_list = []
for f in os.listdir('/home/back_data/fusionprocessing/test/data/result/国家组织机构信息/'):
    df_temp = pd.read_csv(
        f'/home/back_data/fusionprocessing/test/data/result/国家组织机构信息/{f}', usecols=['orgId', 'org_name_xiaoniu'], dtype={'asn': int, 'orgId': str})
    xiaoniu_df_list.append(df_temp)
df_xiaoniu_org = pd.concat(xiaoniu_df_list, ignore_index=True)
df_xiaoniu_org.rename(columns={'orgId': 'org_id'}, inplace=True)
df = pd.merge(df, df_xiaoniu_org, on='org_id', how='left')

df_web = pd.read_csv('/home/back_data/fusionprocessing/test/data/asn_website.csv', dtype={'asn': int})
df_web.rename(columns={'website': 'as_url'}, inplace=True)

df = pd.merge(df, df_web, on='asn', how='left')

df['as_name_cn'] = None
df['as_descr_en'] = None
df['as_descr_cn'] = None
df['org_name_cn'] = None
df['org_descr_en'] = None
df['org_descr_cn'] = None
df['org_url'] = None
df['parent_org_cn'] = None
df['parent_org_en'] = None
df['tag'] = None

df.sort_values(by=['as_country', 'as_rank'], inplace=True, axis=0)
df = df[['asn',	'descr', 'as_rank', 'as_country', 'as_country_cn', 'descr_xiaoniu', 'as_name_cn', 'as_descr_en',	'as_descr_cn', 'aut_name', 'as_url', 'org_id', 'opq_id', 'org_name', 'org_name_xiaoniu',  'org_name_cn', 'org_descr_en', 'org_descr_cn', 'org_url', 'parent_org_cn', 'parent_org_en',
         'org_rank',  'tag']]

df.to_csv('data/asn_to_cn.csv', index=False)

for k, d in df.groupby('as_country_cn'):
    d.to_csv(f'data/国家AS信息/{k}.csv', index=False)

# df = df.loc[df['org_id'] == '962de41b32']
# l = ast.literal_eval(df['sibling_as'].values[0])
# print(l)
# df.info()
# df_res = df.loc[df_source['asn'].values]
# print(df_res['as_country'].drop_duplicates())
# df_res.to_csv('data/4134_res.csv', index=False)
# df_res['org_name'].drop_duplicates().to_csv('data/4134_org_name.csv', index=False)
# n = 23650
# print(df.loc[int(n), 'v6Prefixes'])
# df = df[['asn', 'aut_name']]

# print(df)
# print(df[df['aut_name'].isna()])
