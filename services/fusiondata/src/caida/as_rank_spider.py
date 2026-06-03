import requests
import pandas as pd

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36'
BASE_URL = 'https://api.asrank.caida.org/v2/restful/asns/'
DATA_BLOCK_NUM = 5000

if __name__ == '__main__':
    test_rul = BASE_URL + '?first=1'
    r = requests.get(test_rul, headers={'User-Agent': USER_AGENT})
    total_count = r.json()['data']['asns']['totalCount']
    print(total_count)

    list_df = []
    for i in range(0, total_count, DATA_BLOCK_NUM):
        print(f'Processing {i} to {i + DATA_BLOCK_NUM}')
        r = requests.get(f'{BASE_URL}?first={DATA_BLOCK_NUM}&offset={i}', headers={'User-Agent': USER_AGENT})
        edge_list = r.json()['data']['asns']['edges']
        df = pd.json_normalize(edge_list, max_level=2)
        list_df.append(df)
        # time.sleep(1)
    df_res = pd.concat(list_df)
    df_res.columns = df_res.columns.str.replace('node.', '', regex=False)
    df_res.dropna(how='all', axis=1, inplace=True)
    df_res.rename(columns={'country.iso': 'country'}, inplace=True)
    df_res.to_csv('data/as_rank.csv', index=False)
