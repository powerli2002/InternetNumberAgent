import pandas as pd
from ast import literal_eval

import uuid

df = pd.read_csv('data/opq_org_classify.csv')
df['uuid'] = None
df['uuid'] = df['uuid'].apply(lambda x: uuid.uuid4().hex)
df['asn'] = df['sibling_as'].apply(lambda x: x if pd.isna(x) else literal_eval(x))
df = df.explode('asn')
df = df[df['asn'].notna()]
df = df.drop(columns=['opq_id', 'org_id'])
df.info()
print(len(df['asn'].unique()))
df.to_csv('data/opq_org_classify_explode.csv', index=False)
