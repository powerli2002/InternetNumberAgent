import pandas as pd
from ast import literal_eval


def solve_members(x):
    if x and not pd.isnull(x):
        df = pd.json_normalize(literal_eval(x))
        return list(map(int, df['node.asn'].tolist()))
    else:
        return []


# df_caida = pd.read_csv('/home/lgh/fusionprocessing/src/caida/data/org_data.csv',
#                        usecols=['orgId', 'orgName', 'rank', 'country.iso', 'members.asns.edges'])
# df_caida.rename(columns={'orgId': 'org_id', 'orgName': 'org_name', 'country.iso': 'country',
#                 'rank': 'org_rank',  'members.asns.edges': 'sibling_as'}, inplace=True)
# df_caida['sibling_as'] = df_caida['sibling_as'].apply(solve_members).copy()
# df_caida = df_caida.explode('sibling_as')
# df_caida.rename(columns={'sibling_as': 'asn'}, inplace=True)
# df_caida.to_csv('data/caida_org_explode.csv', index=False)

df_caida = pd.read_csv('data/caida_org_explode.csv',
                       dtype={'asn': int}, usecols=['asn', 'org_id', 'org_name', 'org_rank'])

df_source = pd.read_csv('/home/lgh/rirdata/data/format/2023-07-06/asn.csv', dtype={'asn': int})

df = pd.merge(df_source, df_caida, on='asn', how='left')
df['country'] = df['country'].fillna('ZZ')
print(df)

# ----------------- 通过字典搜索树分类opq_id和org_id -----------------

# dc = df.groupby('opq_id')['org_id'].apply(lambda x: x.dropna().unique().tolist())
# dict_opq_to_org = dc.to_dict()

# dc = df.groupby('org_id')['opq_id'].apply(lambda x: x.dropna().unique().tolist())
# dict_org_to_opq = dc.to_dict()

# print('Dicts are ready.')

# set_solved_opq, set_solved_org = set(), set()
# list_group_opq = []


# def search_child(key: str, opq_to_org_flag: bool) -> tuple:
#     '''
#     搜索树
#     '''
#     d = dict_opq_to_org if opq_to_org_flag else dict_org_to_opq
#     solved = set_solved_org if opq_to_org_flag else set_solved_opq
#     res_opq, res_org = set(), set()
#     for i in d.get(key, []):
#         if i not in solved:
#             if opq_to_org_flag:
#                 res_org.add(i)
#             else:
#                 res_opq.add(i)
#             solved.add(i)
#             search_opq, search_org = search_child(i, not opq_to_org_flag)
#             res_opq.update(search_opq)
#             res_org.update(search_org)
#     return res_opq, res_org


# count = 0
# for k in dict_opq_to_org.keys():
#     count += 1
#     if count % 1000 == 0:
#         print(f'count: {count}')
#     if k not in set_solved_opq:
#         set_solved_opq.add(k)
#         search_opq, search_org = search_child(k, True)
#         search_opq.add(k)
#         list_group_opq.append((list(search_opq), list(search_org)))

#         # for org in dict_opq_to_org.get(k, []):
#         #     opq_list = dict_org_to_opq.get(org, [])
#         #     new_group.update(opq_list)
#         #     set_solved_opq.update(opq_list)

# df_res = pd.DataFrame(list_group_opq, columns=['opq_id', 'org_id'])
# df_res.to_csv('data/opq_org_group.csv', index=False)

# ----------------- 通过字典搜索树分类opq_id和org_id -----------------

df_classify = pd.read_csv('data/opq_org_group.csv')
df_classify['opq_id'] = df_classify['opq_id'].apply(lambda x: literal_eval(x))
df_classify['org_id'] = df_classify['org_id'].apply(lambda x: literal_eval(x))
df_classify.reset_index(inplace=True)
df_classify.set_index('index', inplace=True)
df_classify['sibling_as'] = None
df_classify['org_name'] = None

df_opq_group = df.groupby('opq_id')
df_org_group = df.groupby('org_id')

# df_classify = df_classify[df_classify['opq_id'] ==
#                           "['A914EAE4', 'A918EED4', 'A91B1A23', 'F36DB492', 'A917576D', '0008a813-d36d-4b09-b1f6-1fb15f923722', '80ca3f56fa8caf39ad30cf68850d2c1d', 'A91DEB01', 'A9143CB3']"]

count = 0
for row in df_classify.itertuples():
    count += 1
    if count % 1000 == 0:
        print(f'count: {count}')
    opq_id_list = row.opq_id
    org_id_list = row.org_id

    sibling_set = set()
    for opq_id in opq_id_list:
        sibling_set.update(df_opq_group.get_group(opq_id)['asn'].tolist())
    df_classify.at[row.Index, 'sibling_as'] = list(sibling_set)

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
            print('IndexError!')
            print(pd.concat(list_org_df))
            df_classify.at[row.Index, 'org_name'] = None

# print(df_classify)
df_classify.to_csv('data/opq_org_classify.csv', index=False)

# df_group = df.groupby(['opq_id'])

# print(len(df_group))
# dict_df = {}
# for name, group in df_group:
#     org_id_list = group['org_id'].dropna().unique().tolist()
#     org_name_series = group['org_name'].dropna()
