"""
处理 IP地理位置数据库 后台导出的数据


"""

import pandas as pd

def make_csv(input_file, output_format):
    """
    处理 IP地理位置数据库 后台导出的数据


    """
    if output_format == 'device':
        output_file = input_file.replace('.csv', '_device_input.csv')
    elif output_format == 'source':
        output_file = input_file.replace('.csv', '_source_input.csv')
    else:
        raise ValueError(f'Invalid output format: {output_format}')

    df = pd.read_csv(input_file)
    df = df[['ID', '设备IPv6']]
    
    df.rename(columns={'设备IPv6': 'ipv6'}, inplace=True)
    df.dropna(subset=['ipv6'], inplace=True)
    df.to_csv(output_file, index=False)





if __name__ == '__main__':
    input_file = 'data/input/ip_geo_data_20251111_133545.csv'
    make_csv(input_file, 'device')
    make_csv(input_file, 'source')