import pandas as pd

df = pd.read_csv('/home/back_data/fusionprocessing/src/caida/国家组织机构信息/中国.csv')
df.info()
print(df['members.asns.totalCount'].sum())
