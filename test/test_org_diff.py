import pandas as pd
import ast
import subprocess
import time

df_caida_org = pd.read_csv('/home/back_data/fusionprocessing/src/caida/data/org_data.csv', dtype={'orgId': str})
df_caida_org = df_caida_org[df_caida_org['orgId'] == '1191b749c0']
data_asns = df_caida_org['members.asns.edges'].values[0]
# print(type(data_asns))
data_asns = ast.literal_eval(data_asns)
# print(data_asns)
list_asns = [int(x['node']['asn']) for x in data_asns]
print(list_asns)

df_source = pd.read_csv('/home/back_data/rirdata/data/format/2023-07-06/asn.csv', dtype={'asn': int})
df_source = df_source[df_source['asn'].isin(list_asns)]
df_source.sort_values(by=['opq_id'], inplace=True, axis=0)
print(df_source)
df_source.to_csv('data/CM_data/delegate.csv', index=False)

for asn in list_asns:
    print(f'Solving AS{asn}...')
    rir_str = df_source[df_source['asn'] == asn]['source'].values[0]
    if rir_str == 'ripencc':
        rir_str = 'ripe'
    p = subprocess.Popen(['whois', '-h', f'whois.{rir_str}.net', f'AS{asn}'],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    whois_data = p.stdout.read().decode(errors='ignore')
    error_data = p.stderr.read().decode(errors='ignore').lower()
    with open(f'data/CM_data/whois/{asn}.txt', 'w') as f:
        f.write(whois_data)
    time.sleep(1)
