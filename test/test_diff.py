import pandas as pd

df_diff = pd.read_csv('/home/lgh/fusionprocessing/data/diff.csv')
df_1 = df_diff[['asn', 'aut_name']]
df_diff['aut_name'] = df_diff['descr']
df_diff['aut_name'] = df_diff['aut_name'].fillna(df_diff['org_name']).fillna(df_diff['asn'].apply(lambda x: f'AS{x}'))
print(df_1)
print(df_diff[['asn', 'aut_name']])
