import pandas as pd
import json
import os

df = pd.read_csv('/home/lgh/fusionprocessing/data/format/as_entity_2023-10-17.csv', dtype={'asn': int}, usecols=['asn', 'source', 'status', 'descr', 'as_rank', 'org_id', 'org_country', 'org_country_cn',
                 'org_name', 'org_name_cn', 'type', 'as_country', 'as_country_cn', 'aut_name', ], keep_default_na=False)

# org_name = 'China Education and Research Network (CERNET)'

# print(df)
# df.to_csv('data/contact_info_test.csv', index=False)

# 4137 4837

# with open('data/asn.txt', 'r') as f:
#     asn = f.read().splitlines()
#     asn = [int(x) for x in asn if x.isdigit()]

# df = df[['asn', 'source', 'status', 'org_name', 'org_name_cn', 'aut_name']]

# d = df[df['asn'].isin(asn)]


# # df[(df['aut_name'].str.contains('IDC', case=False, na=False)) | (
# #     df['descr'].str.contains('IDC', case=False, na=False))]['type'] = 'IDC'
# df.loc[(df['aut_name'].str.contains('IDC', case=False, na=False)) | (
#     df['descr'].str.contains('IDC', case=False, na=False)), 'type'] = 'IDC'

# # df[(df['aut_name'].str.contains('CDN', case=False, na=False)) | (
# #     df['descr'].str.contains('CDN', case=False, na=False))]['type'] = 'CDN'
# df.loc[(df['aut_name'].str.contains('CDN', case=False, na=False)) | (
#     df['descr'].str.contains('CDN', case=False, na=False)), 'type'] = 'CDN'

# # df[(df['aut_name'].str.contains('CLOUD', case=False, na=False)) | (
# #     df['descr'].str.contains('CLOUD', case=False, na=False))]['type'] = 'CLOUD'
# df.loc[(df['aut_name'].str.contains('CLOUD', case=False, na=False)) | (
#     df['descr'].str.contains('CLOUD', case=False, na=False)), 'type'] = 'CLOUD'

# d = df[df['asn'] == 132437]
d = df
# d['admin_info'] = d['admin_info'].apply(lambda x: json.loads(str(x)) if not pd.isna(x) else x).copy()
# d['tech_info'] = d['tech_info'].apply(lambda x: json.loads(str(x)) if not pd.isna(x) else x).copy()
# d['abuse_info'] = d['abuse_info'].apply(lambda x: json.loads(str(x)) if not pd.isna(x) else x).copy()

# df['sibling_as_num'] = df['sibling_as'].apply(lambda x: len(ast.literal_eval(x)) if not pd.isna(x) else 0)
# df.drop(['sibling_as'], axis=1, inplace=True)
print(d)
# d.to_csv(f'data/query.csv', index=False)
# l1, l2 = ast.literal_eval(d['v4Prefixes'].values[0]), ast.literal_eval(d['v6Prefixes'].values[0])
# print(f'v4Prefixes: {len(l1)}')
# print(f'v6Prefixes: {len(l2)}')
# l1, l2 = ast.literal_eval(d['v4Peer'].values[0]), ast.literal_eval(d['v6Peer'].values[0])
# print(f'v4Peer: {len(l1)}')
# print(f'v6Peer: {len(l2)}')
# l3 = ast.literal_eval(d['sibling_as'].values[0])
# print(f'sibling_as: {len(l3)}')
