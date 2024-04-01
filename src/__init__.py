from src.utils.db_tool import DB_Tool
from src.utils.logging_manager import logger

import os
import yaml
import json
from jsoncomment import JsonComment

import pandas as pd


class BaseEntity():
    '''
    基础类，包含配置文件设置以及一些常用的方法。

    '''

    def __init__(self, config_path, date: str, enable_DB=True):
        self.__load_config(config_path)
        # if date == '' or date is None or date.lower() == 'latest':
        #     rir_dir = self.format_dir
        #     date_list = sorted(os.listdir(rir_dir), reverse=True)
        #     if len(date_list) > 1:
        #         self.date = date_list[1]
        #     else:
        #         raise ValueError(f'Latest date need at least 2 dates, but only 1 or less date found: {date_list}')
        # else:
        #     self.date = date
        self.date = date
        self.static_data_path = './data/static/'

        df_country_code = pd.read_csv('./data/utils/iso3166.csv', na_filter=False)
        # EN -> ZH
        self.country_code_map = dict(zip(df_country_code['ISO_2'].values, df_country_code['ZH'].values))

        if enable_DB:
            self.DB_Tool_instance = DB_Tool(config_path, date)
        self.enable_DB = enable_DB

        self.rir_list = ['apnic', 'arin', 'lacnic', 'ripe', 'afrinic']
        self.json_parser = JsonComment(json)

    # Load Config File
    def __load_config(self, config_path):
        try:
            with open(config_path, 'r') as cf:
                config = yaml.load(cf.read(), Loader=yaml.loader.SafeLoader)

                self.format_dir = config.get("rir_format_dir", "./rir_data/data/format/")
                self.logging_dir = config.get("logging_dir", "./logs/")
                self.target_dir = config.get("output_dir", "./data/")
                self.rib_dir = config.get("rib_dir", "./bgp_data/data/")
                self.caida_dir = config.get("caida_dir", "./src/caida/data/")

                self.postgresql_database = config["postgresql_database"]
                self.postgresql_user = config["postgresql_user"]
                self.postgresql_password = config["postgresql_password"]
                self.postgresql_host = config["postgresql_host"]
                self.postgresql_port = config["postgresql_port"]
            if os.environ.get('IN_DOCKER_CONTAINER', False):
                # Docker 环境下，将数据目录映射到宿主机
                # 环境变量 IN_DOCKER_CONTAINER 必须在 dockerfile 中设置
                self.format_dir = './rir_data/data/format/'
                self.logging_dir = './logs/'
                self.target_dir = './data/'
                self.rib_dir = './bgp_data/data/'
                self.caida_dir = './src/caida/data/'
        except Exception as e:
            logger.error("Load Config File Error: %s", e)
            exit(1)

    def append_country_cn_in_df(self, data: pd.DataFrame, target_col='country') -> pd.DataFrame:
        '''
        为 DataFrame 添加 country_cn 字段。

        Parameters:

            data - DataFrame 数据

            target_col - 目标列名，默认为 `country`

        Returns:

            pd.DataFrame - 添加 `{target_col}_cn` 字段后的 DataFrame

        '''
        if target_col not in data.columns:
            raise KeyError(f'data has no column `{target_col}`')
        c_map = self.country_code_map
        c_map['null'] = '未分配'
        c_map[''] = '未分配'
        c_map['-'] = '暂无数据'
        data[f'{target_col}_cn'] = data[target_col].map(self.country_code_map).copy()
        return data
