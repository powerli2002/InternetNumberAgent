import json
import csv
from collections import OrderedDict

def flatten_dict(d, parent_key='', sep='.'):
    """递归展平嵌套字典"""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return OrderedDict(items)

def process_peeringdb_data(input_file, output_file):
    # 读取JSON数据
    with open(input_file, 'r', encoding='utf-8') as f:
        data = [json.loads(line) for line in f]
    
    # 获取所有可能的字段（包括嵌套字段）
    all_fields = set()
    for item in data:
        flattened = flatten_dict(item)
        all_fields.update(flattened.keys())
    
    # 排序字段（可选）
    sorted_fields = sorted(all_fields)
    
    # 写入CSV
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=sorted_fields)
        writer.writeheader()
        
        for item in data:
            flattened = flatten_dict(item)
            # 确保所有字段都存在，不存在则为空
            row = {field: flattened.get(field, '') for field in sorted_fields}
            writer.writerow(row)

if __name__ == "__main__":
    input_json = "/home/back_data/fusionprocessing/fusiondata/data/static/asns.jsonl"  # 您的输入文件
    output_csv = "/home/back_data/fusionprocessing/fusiondata/data/static/as_rank_20250330.csv"  # 输出文件
    
    process_peeringdb_data(input_json, output_csv)
    print(f"数据处理完成，已保存到 {output_csv}")
