# 导出as_entity

import pandas as pd


as_entity_path = "/home/back_data/fusionprocessing/data/format/as_entity_2024-07-22.csv"

as_entity_output_path = "/home/back_data/fusionprocessing/data/export/as_entity_CN_2024-07-22.csv"

as_entity = pd.read_csv(as_entity_path)
# 筛选as_country为CN的行
as_entity = as_entity[as_entity['as_country'] == 'CN']


as_entity.to_csv(as_entity_output_path)

