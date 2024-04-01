import pandas as pd
import os
from ast import literal_eval


rir_data_dir = '/home/lgh/rirdata/data/format/2023-04-26'

df_as_dict = pd.read_csv('../data/format/as_dict_old.csv',
                         usecols=['asn', 'region', 'as_name', 'descr', 'is_ddos_provider', 'org_name', 'admin', 'tech', 'abuse', 'sibling_as', 'v6Upstream', 'v6Peer', 'v6Propagation', 'v6Prefixes', 'v4Upstream', 'v4Peer', 'v4Propagation', 'v4Prefixes'])
df_as_dict.rename(columns={'as_name': 'aut_name', 'region': 'country', 'sibling_as': 'sibling'}, inplace=True)
# print(df_as_dict)

df_as_org = pd.read_csv('../src/caida/data/as_org.csv',
                        usecols=['asn', 'asnName', 'country', 'orgId.orgName', 'orgId.country'])
df_as_org.rename(columns={'asnName': 'as_name', 'orgId.orgName': 'org_name',
                 'orgId.country': 'org_country'}, inplace=True)

df_as_rank = pd.read_csv('../src/caida/data/as_rank.csv',
                         usecols=['asn', 'rank', 'asnName', 'longitude', 'latitude', 'country'])
df_as_rank.rename(columns={'asnName': 'as_name', 'longitude': 'as_longitude', 'latitude': 'as_latitude'}, inplace=True)

df_as_type = pd.read_csv('../data/format/astype.txt', sep='|', skiprows=6, names=['asn', 'source', 'type'])
df_as_type.drop(['source'], axis=1, inplace=True)

df_caida = pd.merge(df_as_rank, df_as_org, on='asn', how='outer')
df_caida['as_name'] = df_caida['as_name_x'].fillna(df_caida['as_name_y'])
df_caida['country'] = df_caida['country_x'].fillna(df_caida['country_y'])
df_caida.drop(['as_name_x', 'as_name_y', 'country_x', 'country_y'], axis=1, inplace=True)
# print(df_caida)

df = pd.merge(df_as_dict, df_caida, on='asn', how='outer')
df['country'] = df['country_x'].fillna(df['country_y']).fillna('ZZ')
df['aut_name'] = df['as_name'].fillna(df['aut_name'])
df['org_name'] = df['org_name_y'].fillna(df['org_name_x'])
df.drop(['country_x', 'country_y', 'as_name', 'org_name_x', 'org_name_y'], axis=1, inplace=True)

df = pd.merge(df, df_as_type, on='asn', how='left')

for col in ['sibling', 'v6Upstream', 'v6Peer', 'v6Propagation', 'v6Prefixes', 'v4Upstream', 'v4Peer', 'v4Propagation', 'v4Prefixes']:
    df[col] = df[col].apply(lambda x: x if pd.isna(x) else literal_eval(x))

df.sort_values(by=['asn'], inplace=True)
df.reset_index(drop=True, inplace=True)
print(df)
print(df.columns)
df.to_json('../data/format/as_dict.json', orient='records', lines=True)
df.to_csv('../data/format/as_dict.csv', index=False)

# entity_list = []
# for rir in ['apnic', 'arin', 'lacnic', 'afrinic', 'ripe']:
#     data_path = os.path.join(rir_data_dir, rir, f'{rir}_entity_org_rdap_info.csv')
#     df_rir = pd.read_csv(data_path, dtype=str, usecols=['handle', 'name', 'descr', 'address', 'tel', 'fax', 'email'])
#     entity_list.append(df_rir)
# df_entity = pd.concat(entity_list)
# df_entity.drop_duplicates(subset=['handle'], inplace=True)
# df_entity['name_lower'] = df_entity['name'].str.lower()
# print(df_entity)
