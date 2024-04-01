import pandas as pd

df = pd.read_csv('/home/lgh/fusionprocessing/data/format/rib_data_2023-07-06.csv')

df['index'] = df['asn'].astype(int)
df.set_index('index', inplace=True)

print(df.loc[4134])
