import pandas as pd

df_rank = pd.read_csv('./data/as_rank.csv')
df_org = pd.read_csv('./data/as_pure_org.csv')
df_org_name = df_org[['orgId', 'orgName']]

df_rank.rename(columns={'organization.orgId': 'orgId'}, inplace=True)
df_rank = pd.merge(df_rank, df_org_name, on='orgId', how='left')

df_rank.sort_values(by='rank', inplace=True)
print(f'Writing {len(df_rank)} rows to ./data/as_rank_org.csv')
df_rank.to_csv('./data/as_rank_org.csv', index=False)
df_cn_rank = df_rank[df_rank['country'] == 'CN']
print(f'Writing {len(df_cn_rank)} rows to ./data/as_cn_rank_org.csv')
df_cn_rank.to_csv('./data/as_cn_rank_org.csv', index=False)

df_cn_org = df_org[df_org['country'] == 'CN']
print(f'Writing {len(df_cn_org)} rows to ./data/as_cn_pure_org.csv')
df_cn_org.to_csv('./data/as_cn_pure_org.csv', index=False)
