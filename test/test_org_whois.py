import pandas as pd

df_opq_group = pd.read_csv('/home/back_data/fusionprocessing/data/org_entity/as_org_mapping.csv', dtype={'asn': str},
                           usecols=['org_name', 'sibling', 'uuid', 'org_name_cn', 'asn'])


# def slove(x):
#     try:
#         return int(x)
#     except:
#         print(x)
#         return 0


df_opq_group['asn'] = df_opq_group['asn'].apply(int)
l = df_opq_group['asn'].tolist()
l.sort(reverse=True)
print(l[0:10])

df_opq_group.rename(columns={'sibling': 'sibling_as'}, inplace=True)

print(df_opq_group)
