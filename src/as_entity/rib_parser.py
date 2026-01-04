from src.utils.logging_manager import logger
from src import BaseEntity

import os
from multiprocessing.pool import Pool

import pandas as pd
from IPy import IP


class RIBParser(BaseEntity):

    def __init__(self,  date: str, config_path='conf/config.yaml', enable_DB=True):
        '''
        RIB路由表数据提取类

        Parameters:

            date - 日期，格式为 YYYY-MM-DD。请注意，本类将根据该日期读取相应的数据文件（包括但不限于 RIR 文件等），因此可能需要根据数据需求自行更改而不是直接使用当前日期。

            config_path - 配置文件路径

            enable_DB - 是否启用数据库

        '''
        super().__init__(config_path, date, enable_DB)

        self.json_file_path = f'{self.target_dir}format/rib_data_{self.date}.json'
        self.csv_file_path = f'{self.target_dir}format/rib_data_{self.date}.csv'

    def run(self, output_type='csv'):
        logger.info('开始获取 RIB 中数据并导入 AS 基本信息')
        d = self.__rib_as_info()
        res = self.__convert_set_to_list(d)
        logger.info('RIB 数据获取完成')

        if output_type.lower() == 'csv':
            self.__as_dict_to_csv(res)
        elif output_type.lower() == 'json':
            self.__as_dict_to_json(res)
        else:
            self.__as_dict_to_json(res)
            self.__as_dict_to_csv(res)
        logger.info('RIB 数据导出完成')

    def __rib_as_info(self) -> dict:
        '''
        获取 AS 路由信息

        Parameters:

            None

        Returns:

            dict : 处理后的 AS 字典

        '''
        logger.info('开始获取 RIB 基本信息')
        as_dict = {}
        file_path_list = []
        for rib_file in os.listdir(self.rib_dir):
            if not rib_file.endswith('.data'):
                continue
            file_path_list.append(os.path.join(self.rib_dir, rib_file))

        process_num = int(os.cpu_count()*0.75)
        logger.info(f'使用 {process_num} 个子进程处理 RIB 数据')
        logger.info(f'共有 {len(file_path_list)} 个 RIB 文件需要处理')

        with Pool(process_num) as p:
            res = p.imap_unordered(self.process_task, file_path_list)
            for r in res:
                for k, v in r.items():
                    if as_dict.get(k) is None:
                        as_dict[k] = {}
                    for k1, v1 in v.items():
                        as_dict[k].setdefault(k1, set()).update(v1)
        return as_dict

    @staticmethod
    def process_task(rib_file_path: str) -> dict:
        as_dict = {}
        logger.info(f'开始处理 {rib_file_path}')
        count = 0
        try:
            with open(rib_file_path, 'r') as f:
                for line in f:
                    route = line.split('|')
                    if len(route) < 7:
                        # 路由撤回报文，忽略
                        continue
                    count += 1
                    if count % 1000000 == 0:
                        logger.info(f'{rib_file_path}: 已处理 {count} 条路由')

                    path = route[6].split(' ')  # ASPath
                    prefix = route[5]   # 路由IP前缀
                    prefix_version = IP(prefix).version()  # 路由IP版本

                    if len(path) > 1:
                        path_pairs = zip(path, path[1:])  # 前一个asn与后一个asn组成pair
                        # 确认上下游关系和 peer 关系
                        for pair in path_pairs:
                            if pair[0] == pair[1]:
                                continue

                            try:
                                pre, after = int(pair[0].strip()), int(pair[1].strip())
                            except:
                                continue

                            if as_dict.get(after) is None:
                                as_dict[after] = {}

                            if as_dict.get(pre) is None:
                                as_dict[pre] = {}

                            str_prefix = 'v4' if prefix_version == 4 else 'v6'
                            # 在 AS 字典中找到 AS pair 中的两个 AS，确认其上下游关系和 peer 关系
                            as_dict[after].setdefault(f"{str_prefix}Upstream", set()).add(pre)
                            as_dict[after].setdefault(f"{str_prefix}Peer", set()).add(pre)

                            as_dict[pre].setdefault(f"{str_prefix}Downstream", set()).add(after)
                            as_dict[pre].setdefault(f"{str_prefix}Peer", set()).add(after)

                    # 在字典中，为该路由源 AS 添加这整条 ASPath 和 前缀，表明源 AS 有这么条路由并拥有这么个前缀
                    try:
                        source = int(path[-1].strip())
                    except:
                        continue

                    if as_dict.get(source) is None:
                        as_dict[source] = {}

                    if prefix_version == 4:
                        as_dict[source].setdefault("v4Propagation", set()).add(route[6])
                        as_dict[source].setdefault("v4Prefixes", set()).add(prefix)
                    if prefix_version == 6:
                        as_dict[source].setdefault("v6Propagation", set()).add(route[6])
                        as_dict[source].setdefault("v6Prefixes", set()).add(prefix)

        except Exception as e:
            logger.error(f'处理 {rib_file_path} 路由信息出错，错误信息：{e}')
        finally:
            logger.info(f'{rib_file_path} 处理完成，共处理 {count} 条路由')

        return as_dict

    def __convert_set_to_list(self, target_dict: dict) -> dict:
        '''
        把 as_dict 中的 set 转换为 list

        Parameters:

            None

        Returns:

            dict: 转换后的 as_dict
        '''
        logger.info('开始将 AS 字典中的 set 转换为 list')
        for key, value in target_dict.items():
            for k, v in value.items():
                if isinstance(v, set):
                    target_dict[key][k] = list(v)
        logger.info('AS 字典中的 set 转换为 list 完成')
        return target_dict

    def __as_dict_to_json(self, target_dict: dict):
        '''
        把 as_dict 转换为 json 文件

        Parameters:

            None

        Returns:

            None

        '''
        logger.info('开始将 AS 字典转换为 json 文件')
        self.json_parser.dumpf(target_dict, self.json_file_path, ensure_ascii=False)
        logger.info('AS 字典转换为 json 文件完成')

    def __as_dict_to_csv(self, target_dict: dict):
        '''
        把 as_dict 转换为 csv 文件

        Parameters:

            None

        Returns:

            None

        '''
        logger.info('开始将 AS 字典转换为 csv 文件')
        data_csv = []
        for k, v in target_dict.items():
            v['asn'] = k
            data_csv.append(v)
        df = pd.json_normalize(data_csv, max_level=0)
        df.to_csv(self.csv_file_path, index=False)
        logger.info('AS 字典转换为 csv 文件完成')
