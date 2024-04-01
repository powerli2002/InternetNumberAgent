import pandas as pd
from ast import literal_eval


def merge_list(x):
    res = set()
    for sublist in x:
        res.update(sublist)
    return list(res)


# 创建示例 DataFrame
df = pd.read_csv('data/opq_org_classify.csv')

df['opq_id'] = df['opq_id'].apply(lambda x: x if pd.isna(x) else literal_eval(x))
df['org_id'] = df['org_id'].apply(lambda x: x if pd.isna(x) else literal_eval(x))
df['sibling_as'] = df['sibling_as'].apply(lambda x: x if pd.isna(x) else literal_eval(x))
df['org_name'] = df['org_name'].str.replace(',', '')
print(df)

grouped = df.groupby('org_name').agg({'opq_id': merge_list,
                                      'org_id': merge_list,
                                      'sibling_as': merge_list}).reset_index()

print(grouped)
grouped.to_csv('data/opq_org_classify_grouped.csv', index=False)
