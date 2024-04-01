from src.utils.logging_manager import logger
from src import BaseEntity

import os
import re
from multiprocessing.pool import Pool

import pandas as pd
from IPy import IP


class RIBFormatter(BaseEntity):
    def __init__(self, date: str, config_path='config.yaml', enable_DB=False):
        '''
        RIB 路由表数据提取，生成包含 IPv4 路由前缀与路由归属 AS 的数据文件

        Parameters:

            date - 日期，格式为 YYYY-MM-DD。请注意，本类将根据该日期读取相应的数据文件（包括但不限于 RIR 文件等），因此可能需要根据数据需求自行更改而不是直接使用当前日期。

            config_path - 配置文件路径

            enable_DB - 是否启用数据库

        '''
        super().__init__(config_path, date, enable_DB)

    def run(self):
        logger.info('开始获取 RIB 中数据并处理路由前缀信息')
        ipv4_prefix, ipv6_prefix = self.__rib_prefix_as_info()
        logger.info('RIB 数据获取完成')

        logger.info('开始导出 BGP 路由前缀与归属 AS 信息')
        dfv4 = pd.DataFrame(ipv4_prefix, columns=['prefix', 'as'])
        dfv6 = pd.DataFrame(ipv6_prefix, columns=['prefix', 'as'])
        dfv4.to_csv(os.path.join(self.target_dir, 'format', 'rib_prefix_base.csv'), index=False)
        dfv6.to_csv(os.path.join(self.target_dir, 'format', 'rib_v6_prefix_base.csv'), index=False)
        logger.info('BGP 路由前缀与归属 AS 信息导出完成')

    def __rib_prefix_as_info(self) -> tuple:
        '''
        获取路由前缀与路由归属 AS 信息

        Parameters:

            None

        Returns:

            tuple : 处理后的 IPv4 与 IPv6 路由前缀与路由归属 AS

        '''
        logger.info('开始获取 RIB 基本信息')
        file_path_list = []
        for rib_file in os.listdir(self.rib_dir):
            if not rib_file.endswith('.data'):
                continue
            file_path_list.append(os.path.join(self.rib_dir, rib_file))

        process_num = int(os.cpu_count()*0.75)
        logger.info(f'使用 {process_num} 个子进程处理 RIB 数据')
        logger.info(f'共有 {len(file_path_list)} 个 RIB 文件需要处理')

        ipv4_prefix = set()
        ipv6_prefix = set()
        with Pool(process_num) as p:
            res = p.imap_unordered(self.process_task, file_path_list)
            for v4, v6 in res:
                ipv4_prefix.update(v4)
                ipv6_prefix.update(v6)
        return ipv4_prefix, ipv6_prefix

    @staticmethod
    def process_task(rib_file_path: str) -> tuple:
        logger.info(f'开始处理 {rib_file_path}')
        ipv4_prefix = set()
        ipv6_prefix = set()
        try:
            with open(rib_file_path, 'r') as f:
                for line in f:
                    route = line.split('|')
                    if len(route) < 7:
                        # 路由撤回报文，忽略
                        continue
                    path = route[6].split(' ') # ASPath
                    if len(path) > 1:
                        prefix = route[5] # 路由 IP 前缀
                        bgp = path[-1] # 路由归属 AS
                        if not bgp[-1].isdigit():
                            bgp = re.search(r'\d+', bgp).group()
                        if IP(prefix).version() == 4:
                            ipv4_prefix.add((prefix, bgp))
                        else:
                            ipv6_prefix.add((prefix, bgp))
        except Exception as e:
            logger.error(f'处理 {rib_file_path} 路由信息出错，错误信息：{e}')
        finally:
            logger.info(f'{rib_file_path} 处理完成')

        return ipv4_prefix, ipv6_prefix
