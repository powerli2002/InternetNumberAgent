import pandas as pd


def append_country_cn_in_df(data: pd.DataFrame, country_map: dict) -> pd.DataFrame:
    '''
    为 DataFrame 添加 country_cn 字段。
    该 DataFrame 必须包含 country 字段，否则抛出 KeyError 异常。

    Parameters:

        data - DataFrame 数据

    Returns:

        pd.DataFrame - 添加 country_cn 字段后的 DataFrame

    '''
    if 'country' not in data.columns:
        raise KeyError('data has no column `country`')
    c_map = country_map
    c_map['null'] = '未分配'
    c_map[''] = '未分配'
    c_map['-'] = '暂无数据'
    data['country_cn'] = data['country'].map(country_map).copy()
    return data


df = pd.read_csv('/home/back_data/fusionprocessing/fusiondata/data/format/as_entity_base.csv', usecols=['asn', 'source', 'descr', 'registration_date', 'last_change_date',
                 'as_rank', 'as_longitude', 'as_latitude', 'as_country', 'as_country_cn', 'aut_name'])
df.dropna(subset=['descr', 'aut_name'], inplace=True, how='all')
# df = pd.read_csv('/home/back_data/fusionprocessing/src/caida/data/org_data.csv')
# df.rename(columns={'orgName': 'org_name', 'country.name': 'country_en'}, inplace=True)
# print(df.shape)

df_country_code = pd.read_csv('/home/back_data/fusionprocessing/fusiondata/data/utils/iso3166.csv', na_filter=False)
country_code_map = dict(zip(df_country_code['ISO_2'].values, df_country_code['ZH'].values))

if 'country.iso' in df.columns and 'country' not in df.columns:
    df.rename(columns={'country.iso': 'country'}, inplace=True)

if 'country' in df.columns:
    df = append_country_cn_in_df(df, country_code_map)
data_type = 'as'  # 'org'
df['tag'] = None
df[f'{data_type}_name_cn'] = None
df[f'{data_type}_descr_en'] = None
df[f'{data_type}_descr_cn'] = None
df[f'{data_type}_url'] = None

for name, group in df.groupby('as_country_cn'):
    group.sort_values(by='as_rank', inplace=True)
    group.to_csv(f'国家AS信息/{name}.csv', index=False)
