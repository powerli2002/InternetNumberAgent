import os
import uuid

import pandas as pd
from ast import literal_eval


def solve_members(x):
    if x and not pd.isnull(x):
        df = pd.json_normalize(literal_eval(x))
        return df['node.asn'].tolist()
    else:
        return []


df_classify = pd.read_csv('/home/lgh/fusionprocessing/data/format/opq_org_group_with_name_and_sibling.csv')
df_classify['uuid'] = None
df_classify['uuid'] = df_classify['org_name'].apply(lambda x: uuid.uuid5(uuid.NAMESPACE_DNS, str(x)).hex)
# print(df_classify)
df_classify.to_csv(os.path.join('/home/lgh/fusionprocessing/data/format/',
                   'opq_org_group_with_name_and_sibling.csv'), index=False)
