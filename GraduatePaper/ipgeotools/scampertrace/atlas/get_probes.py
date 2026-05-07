import requests
import pandas as pd


# 获取所有中国probes
all_probes = []
url = "https://atlas.ripe.net/api/v2/probes/?country_code=CN"

while url:
    response = requests.get(url)
    data = response.json()
    all_probes.extend(data['results'])
    url = data.get('next')

# 转成pandas dataframe并筛选有IPv6的
df = pd.DataFrame(all_probes)
df = df[df['address_v6'].notna()]

df.to_csv('atlas_china_v6.csv', index=False)






# 整理json文件，输出 v6，asn，prefix_v6

