import requests
import pandas as pd

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36'
BASE_URL = 'https://api.asrank.caida.org/v2/restful/organizations/'
DATA_BLOCK_NUM = 5000  # less than 5000

if __name__ == '__main__':
    has_next_page = True
    list_df = []
    offset = 0
    while has_next_page:

        target_url = f'{BASE_URL}&first={DATA_BLOCK_NUM}&offset={offset}'
        print(target_url)
        r = requests.get(target_url, headers={'User-Agent': USER_AGENT})
        json_data = r.json()

        total_count = json_data['totalCount']
        offset = json_data['pageInfo']['offset']
        has_next_page = json_data['pageInfo']['hasNextPage']
        print(f'Processing {offset} to {DATA_BLOCK_NUM + offset}, total: {total_count}')

        offset += DATA_BLOCK_NUM
        data_list = json_data['data']
        df = pd.json_normalize(data_list, max_level=2)
        list_df.append(df)

    df_res = pd.concat(list_df)
    df_res.dropna(how='all', axis=1, inplace=True)
    df_res.to_csv('data/as_org.csv', index=False)
