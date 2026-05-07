import math
from multiprocessing import Pool
from pprint import pprint
from random import shuffle
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from default import *
from scripts.utils.file_utils import load_json, dump_json
from scripts.utils.helpers import distance, haversine
from scripts.utils.logging_manager import logger

class DatasetCreator:
    """
    数据集生成工具
    处理用户probe和anchor数据，生成项目数据集
    """
    
    def __init__(self, limit=1000):
        self.LIMIT = limit
        self.probes = None
        self.anchors = None
        self.probes_and_anchors = None
        self.targets_per_prefix = {}
        self.vp_distance_matrix = {}
        self.selected_probes = []
        
    def load_probe_anchor_data(self):
        """
        加载探针和锚点数据
        """
        logger.info("\n===== 1. 加载探针和锚点数据 =====")

        # 加载探针和锚点
        self.probes = load_json(USER_PROBES_FILE)
        self.anchors = load_json(USER_ANCHORS_FILE)

        # 输出统计信息
        logger.info(f"已选择探针数量: {len(self.probes)}")
        logger.info(f"已选择锚点数量: {len(self.anchors)}")

        # 显示部分探针示例
        logger.info("\n探针示例:")
        for i, probe in enumerate(self.probes):
            if i > 10:
                break
            logger.debug(f"探针 {i}: {probe}")

        # 合并探针和锚点并随机打乱
        self.probes_and_anchors = self.probes + self.anchors
        logger.info(f"\n探针和锚点总数: {len(self.probes_and_anchors)}")
        shuffle(self.probes_and_anchors)

        # 保存合并后的数据
        dump_json(self.probes_and_anchors, USER_PROBES_AND_ANCHORS_FILE)
        logger.info(f"已保存合并数据到: {USER_PROBES_AND_ANCHORS_FILE}")
        
        return self.probes_and_anchors

    def generate_distance_matrix(self):
        """
        生成成对距离矩阵
        """
        logger.info("\n===== 3. 生成成对距离矩阵 =====")
        logger.info("计算所有探针和锚点之间的地理距离...")

        # 重新加载探针和锚点数据
        if self.probes is None:
            self.probes = load_json(USER_PROBES_FILE)
        if self.anchors is None:
            self.anchors = load_json(USER_ANCHORS_FILE)
            
        anchors_ip_list = [anchor["address_v4"] for anchor in self.anchors]
        all_probes = self.probes.copy()
        all_probes.extend(self.anchors)

        # 创建IP到坐标的映射
        vp_coordinates_per_ip = {}  # 键为探针或锚点的IPv4地址，值为对应的经纬度坐标

        for probe in all_probes:
            ip_v4_address = probe["address_v4"]
            long, lat = probe["geometry"]["coordinates"]
            vp_coordinates_per_ip[ip_v4_address] = lat, long

        # 创建距离矩阵
        self.vp_distance_matrix = {}
        vp_coordinates_per_ip_l = sorted(vp_coordinates_per_ip.items(), key=lambda x: x[0])

        # 计算锚点之间的距离
        for i in range(len(vp_coordinates_per_ip_l)):
            vp_i, vp_i_coordinates = vp_coordinates_per_ip_l[i]
            if vp_i not in anchors_ip_list:  # 只考虑锚点
                continue
            for j in range(len(vp_coordinates_per_ip_l)):
                vp_j, vp_j_coordinates = vp_coordinates_per_ip_l[j]
                dist = haversine(vp_i_coordinates, vp_j_coordinates)
                self.vp_distance_matrix.setdefault(vp_i, {})[vp_j] = dist
                self.vp_distance_matrix.setdefault(vp_j, {})[vp_i] = dist

        # 保存距离矩阵
        dump_json(self.vp_distance_matrix, USER_PAIRWISE_DISTANCE_FILE)
        logger.info(f"已保存距离矩阵到: {USER_PAIRWISE_DISTANCE_FILE}")
        
        return self.vp_distance_matrix
    


    def run(self):
        """
        运行完整的数据集创建流程
        """
        logger.info("开始运行数据集创建流程...")
        self.load_probe_anchor_data()
        self.generate_distance_matrix()
        logger.info("数据集创建流程完成")
        
        return {
            "probes_and_anchors": self.probes_and_anchors,
            "vp_distance_matrix": self.vp_distance_matrix,
        }


if __name__ == "__main__":
    creator = DatasetCreator()
    creator.run()
