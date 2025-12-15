import pandas as pd

df = pd.read_csv('/home/back_data/fusionprocessing/data/format/country_entity_2023-07-06.csv')

# USD_CNY_RATE = 7

# df['GDP(CNY)'] = df['GDP p.c. (USD)'].apply(lambda x: int(''.join(x[1:].split(',')))*USD_CNY_RATE)

# df.drop(['Sub-Region', 'CC Num', 'Region Number', 'GDP p.c. (USD)'], axis=1, inplace=True)

df['index'] = df['country']
df.set_index('index', inplace=True)

print(df)
print(df.info())

print(df.loc['CN'])
