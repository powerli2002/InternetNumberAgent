from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent / "data"

df_rank = pd.read_csv(DATA_DIR / "as_rank.csv")
df_org = pd.read_csv(DATA_DIR / "as_pure_org.csv")
df_org_name = df_org[['orgId', 'orgName']]

df_rank.rename(columns={'organization.orgId': 'orgId'}, inplace=True)
df_rank = pd.merge(df_rank, df_org_name, on='orgId', how='left')

df_rank.sort_values(by='rank', inplace=True)
as_rank_org_path = DATA_DIR / "as_rank_org.csv"
print(f'Writing {len(df_rank)} rows to {as_rank_org_path}')
df_rank.to_csv(as_rank_org_path, index=False)
df_cn_rank = df_rank[df_rank['country'] == 'CN']
as_cn_rank_org_path = DATA_DIR / "as_cn_rank_org.csv"
print(f'Writing {len(df_cn_rank)} rows to {as_cn_rank_org_path}')
df_cn_rank.to_csv(as_cn_rank_org_path, index=False)

df_cn_org = df_org[df_org['country'] == 'CN']
as_cn_pure_org_path = DATA_DIR / "as_cn_pure_org.csv"
print(f'Writing {len(df_cn_org)} rows to {as_cn_pure_org_path}')
df_cn_org.to_csv(as_cn_pure_org_path, index=False)
