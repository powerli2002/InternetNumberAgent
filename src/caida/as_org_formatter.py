import pandas as pd


if __name__ == '__main__':
    df = pd.read_csv('data/as_org.csv')
    org_col_list = ['orgId.score', 'orgId.orgId', 'orgId.orgName',
                    'orgId.country', 'orgId.source', 'orgId.members', 'orgId.changed', 'orgId.date', 'orgId.ts']
    df = df[org_col_list]
    df.columns = df.columns.str.replace('orgId.', '', regex=False)
    df.drop_duplicates(subset=['orgId', 'orgName'], inplace=True)
    df['memberNumber'] = df['members'].apply(lambda x: len(eval(x)))
    # df_grouped = df.groupby(['country']).agg({'score': 'sum', 'members': 'sum'})
    # df_grouped = df.groupby(['country'])
    # for name, group in df_grouped:
    #     print(name)
    #     print(group)
    df.sort_values(by=['country', 'score'], ascending=True, inplace=True)
    df.reset_index(drop=True, inplace=True)
    df.to_csv('data/as_simple_org.csv', index=False, columns=['score', 'orgId', 'orgName', 'country', 'memberNumber'])
    # df = df.loc[df['memberNumber'] == 1, :]
    # print(df)
