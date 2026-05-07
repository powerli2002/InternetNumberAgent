#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
探针选择策略模块

实现四种探针选择策略：
1. all: 所有探针
2. l3: 延迟最短的三个探针  
3. d3: 地理距离最短的三个探针
4. t3: 能形成三角形的最近三个探针
"""

import sys
import os
import itertools
import numpy as np
from typing import Dict, List, Tuple, Any, Optional

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.utils.helpers import haversine
from scripts.utils.logging_manager import logger


def is_point_in_triangle(A: Tuple[float, float], B: Tuple[float, float], 
                        C: Tuple[float, float], P: Tuple[float, float]) -> bool:
    """
    判断点P是否在三角形ABC内部
    使用叉积法判断点是否在三角形内
    
    Args:
        A, B, C: 三角形的三个顶点 (lon, lat)
        P: 待判断的点 (lon, lat)
    
    Returns:
        bool: True如果点在三角形内，False否则
    """
    def cross(p1, p2, p3):
        """计算叉积 (p2-p1) × (p3-p1)"""
        x1, y1 = p2[0] - p1[0], p2[1] - p1[1]
        x2, y2 = p3[0] - p1[0], p3[1] - p1[1]
        return x1 * y2 - x2 * y1
    
    # 计算点P相对于三角形各边的位置
    b1 = cross(P, A, B) < 0.0
    b2 = cross(P, B, C) < 0.0  
    b3 = cross(P, C, A) < 0.0
    
    # 如果点在三角形内部，所有叉积应该有相同的符号
    return (b1 == b2) and (b2 == b3)


def triangle_area(A: Tuple[float, float], B: Tuple[float, float], 
                 C: Tuple[float, float]) -> float:
    """
    计算三角形的面积（使用经纬度坐标）
    
    Args:
        A, B, C: 三角形的三个顶点 (lon, lat)
    
    Returns:
        float: 三角形面积（平方千米）
    """
    # 使用海伦公式计算面积
    a = haversine(B, C)  # BC边长
    b = haversine(A, C)  # AC边长  
    c = haversine(A, B)  # AB边长
    
    s = (a + b + c) / 2  # 半周长
    
    # 防止数值误差导致负数开方
    area_squared = s * (s - a) * (s - b) * (s - c)
    if area_squared <= 0:
        return 0
        
    return np.sqrt(area_squared)


class ProbeSelector:
    """探针选择器类"""
    
    def __init__(self):
        pass
    
    def select_probes_all(self, target_ip: str, vp_coordinates_per_ip: Dict[str, Tuple[float, float]], 
                         rtt_per_src: Dict[str, float], 
                         target_real_location: Optional[Tuple[float, float]] = None,
                         delta: float = None) -> Dict[str, float]:
        """
        策略1: 选择所有可用探针
        
        Args:
            target_ip: 目标IP地址
            vp_coordinates_per_ip: VP坐标字典 {ip: (lon, lat)}
            rtt_per_src: RTT数据字典 {src_ip: min_rtt}
            target_real_location: 目标真实位置，all策略不需要
            
        Returns:
            Dict[str, float]: 选择的探针RTT数据
        """
        # 过滤掉目标IP自身，返回所有其他探针
        selected_probes = {
            src_ip: rtt_value for src_ip, rtt_value in rtt_per_src.items() 
            if src_ip != target_ip and src_ip in vp_coordinates_per_ip
        }
        
        logger.debug(f"策略ALL: 为目标 {target_ip} 选择了 {len(selected_probes)} 个探针")
        return selected_probes
    
    def select_probes_l3(self, target_ip: str, vp_coordinates_per_ip: Dict[str, Tuple[float, float]], 
                        rtt_per_src: Dict[str, float], 
                        target_real_location: Optional[Tuple[float, float]] = None,
                        delta: float=None ) -> Dict[str, float]:
        """
        策略2: 选择延迟最短的三个探针
        
        Args:
            target_ip: 目标IP地址
            vp_coordinates_per_ip: VP坐标字典 {ip: (lon, lat)}
            rtt_per_src: RTT数据字典 {src_ip: min_rtt}
            target_real_location: 目标真实位置，l3策略不需要
            
        Returns:
            Dict[str, float]: 选择的探针RTT数据
        """
        # 过滤掉目标IP自身
        available_probes = {
            src_ip: rtt_value for src_ip, rtt_value in rtt_per_src.items()
            if src_ip != target_ip and src_ip in vp_coordinates_per_ip
        }
        
        if len(available_probes) <= 3:
            logger.debug(f"策略L3: 可用探针数量 {len(available_probes)} ≤ 3，返回所有探针")
            return available_probes
        
        # 计算每个探针的最小RTT并排序
        probe_min_rtt = []
        for src_ip, rtt_value in available_probes.items():
            probe_min_rtt.append((src_ip, rtt_value))
        
        # 按最小RTT排序，选择前3个
        probe_min_rtt.sort(key=lambda x: x[1])
        selected_probes = {item[0]: item[1] for item in probe_min_rtt[:3]}
        
        logger.debug(f"策略L3: 为目标 {target_ip} 选择了延迟最短的 {len(selected_probes)} 个探针")
        return selected_probes
    
    def select_probes_d3(self, target_ip: str, vp_coordinates_per_ip: Dict[str, Tuple[float, float]], 
                        rtt_per_src: Dict[str, float], 
                        target_real_location: Tuple[float, float],
                        delta: float = None) -> Dict[str, float]:
        """
        策略3: 选择地理距离最短的三个探针
        
        Args:
            target_ip: 目标IP地址  
            vp_coordinates_per_ip: VP坐标字典 {ip: (lon, lat)}
            rtt_per_src: RTT数据字典 {src_ip: min_rtt}
            target_real_location: 目标真实位置 (lon, lat)
            
        Returns:
            Dict[str, float]: 选择的探针RTT数据
        """
        if target_real_location is None:
            logger.warning(f"策略D3: 目标 {target_ip} 缺少真实位置信息，回退到ALL策略")
            return self.select_probes_all(target_ip, vp_coordinates_per_ip, rtt_per_src)
        
        # 过滤掉目标IP自身
        available_probes = {
            src_ip: rtt_value for src_ip, rtt_value in rtt_per_src.items()
            if src_ip != target_ip and src_ip in vp_coordinates_per_ip
        }
        
        if len(available_probes) <= 3:
            logger.debug(f"策略D3: 可用探针数量 {len(available_probes)} ≤ 3，返回所有探针")
            return available_probes
        
        # 计算每个探针到目标的地理距离
        probe_distances = []
        for src_ip, rtt_value in available_probes.items():
            probe_location = vp_coordinates_per_ip[src_ip]
            distance = haversine(probe_location, target_real_location)
            probe_distances.append((src_ip, distance, rtt_value))
        
        # 按距离排序，选择最近的3个
        probe_distances.sort(key=lambda x: x[1])
        selected_probes = {item[0]: item[2] for item in probe_distances[:3]}
        
        logger.debug(f"策略D3: 为目标 {target_ip} 选择了地理距离最近的 {len(selected_probes)} 个探针")
        return selected_probes
    
    def select_probes_t3(self, target_ip: str, vp_coordinates_per_ip: Dict[str, Tuple[float, float]], 
                        rtt_per_src: Dict[str, float], 
                        target_real_location: Tuple[float, float],
                        delta: float = None) -> Tuple[Dict[str, float], str]:
        """
        策略4: 选择能形成包含目标的三角形的最近三个探针
        
        Args:
            target_ip: 目标IP地址
            vp_coordinates_per_ip: VP坐标字典 {ip: (lon, lat)}
            rtt_per_src: RTT数据字典 {src_ip: min_rtt}
            target_real_location: 目标真实位置 (lon, lat)
            delta: 距离延迟转换系数
            
        Returns:
            Tuple[Dict[str, float], str]: (选择的探针RTT数据, 选择状态)
            选择状态: "success" 表示成功找到三角形，"fail" 表示失败
        """

        if target_real_location is None:
            logger.warning(f"策略T3: 目标 {target_ip} 缺少真实位置信息，回退到ALL策略")
            return self.select_probes_all(target_ip, vp_coordinates_per_ip, rtt_per_src, target_real_location, delta), "fail"
        
        # 过滤掉目标IP自身
        available_probes = {
            src_ip: rtt_value for src_ip, rtt_value in rtt_per_src.items()
            if src_ip != target_ip and src_ip in vp_coordinates_per_ip
        }
        
        if len(available_probes) < 3:
            logger.debug(f"策略T3: 可用探针数量 {len(available_probes)} < 3，返回所有探针")
            return available_probes, "fail"
        
        probe_list = list(available_probes.keys())
        best_triangle = None
        min_score = float('inf')
        
        # 遍历所有可能的三探针组合
        for probe_combo in itertools.combinations(probe_list, 3):
            probe_a, probe_b, probe_c = probe_combo
            loc_a = vp_coordinates_per_ip[probe_a]
            loc_b = vp_coordinates_per_ip[probe_b]
            loc_c = vp_coordinates_per_ip[probe_c]
            
            # 检查目标是否在三角形内
            if is_point_in_triangle(loc_a, loc_b, loc_c, target_real_location):
                # 计算三角形三边长
                side_ab = haversine(loc_a, loc_b)
                side_bc = haversine(loc_b, loc_c)
                side_ca = haversine(loc_c, loc_a)
                
                # 计算三边长的标准差（越小越接近等边三角形）
                sides = np.array([side_ab, side_bc, side_ca])
                std_dev = np.std(sides)
                
                # 计算三个探针到目标的平均距离
                dist_to_target = (
                    haversine(loc_a, target_real_location) +
                    haversine(loc_b, target_real_location) +
                    haversine(loc_c, target_real_location)
                ) / 3
                
                # 综合评分：标准差越小越好，平均距离越小越好
                # 使用标准差和平均距离的加权和作为评分标准
                score = std_dev + 0.5 * dist_to_target  # 0.5是权重系数，可以根据需要调整
                
                if score < min_score:
                    min_score = score
                    best_triangle = probe_combo
        
        if best_triangle:
            # 找到了包含目标的三角形
            selected_probes = {
                probe_ip: available_probes[probe_ip] 
                for probe_ip in best_triangle
            }
            logger.debug(f"策略T3: 为目标 {target_ip} 找到包含目标的三角形，选择了 {len(selected_probes)} 个探针")
            return selected_probes, "success"
        else:
            # 没有找到包含目标的三角形，回退到选择所有探针策略
            logger.debug(f"策略T3: 未找到包含目标 {target_ip} 的三角形，回退到选择所有探针策略")
            fallback_probes = self.select_probes_all(target_ip, vp_coordinates_per_ip, rtt_per_src, target_real_location, delta)
            return fallback_probes, "fail"
    
    def select_probes(self, strategy: str, target_ip: str, 
                     vp_coordinates_per_ip: Dict[str, Tuple[float, float]], 
                     rtt_per_src: Dict[str, float], 
                     target_real_location: Optional[Tuple[float, float]] = None,
                     delta: float = None) -> Tuple[Dict[str, float], str]:
        """
        根据策略选择探针
        
        Args:
            strategy: 探针选择策略 ('all', 'l3', 'd3', 't3')
            target_ip: 目标IP地址
            vp_coordinates_per_ip: VP坐标字典 {ip: (lon, lat)}
            rtt_per_src: RTT数据字典 {src_ip: min_rtt}
            target_real_location: 目标真实位置 (lon, lat)，某些策略需要
            delta: 距离延迟转换系数
            
        Returns:
            Tuple[Dict[str, float], str]: (选择的探针RTT数据, 选择状态)
            选择状态: 对于T3策略，"success"表示成功找到三角形，"fail"表示失败
                     对于其他策略，始终返回"success"
        """
        strategy = strategy.lower()
        
        if strategy == 'all':
            probes = self.select_probes_all(target_ip, vp_coordinates_per_ip, rtt_per_src, target_real_location, delta)
            return probes, "success"
        elif strategy == 'l3':
            probes = self.select_probes_l3(target_ip, vp_coordinates_per_ip, rtt_per_src, target_real_location, delta)
            return probes, "success"
        elif strategy == 'd3':
            probes = self.select_probes_d3(target_ip, vp_coordinates_per_ip, rtt_per_src, target_real_location, delta)
            return probes, "success"
        elif strategy == 't3':
            # T3策略直接返回带状态的结果
            return self.select_probes_t3(target_ip, vp_coordinates_per_ip, rtt_per_src, target_real_location, delta)
        else:
            logger.warning(f"未知的探针选择策略: {strategy}，使用默认策略 'all'")
            probes = self.select_probes_all(target_ip, vp_coordinates_per_ip, rtt_per_src, target_real_location, delta)
            return probes, "success"


def create_probe_selector() -> ProbeSelector:
    """创建探针选择器实例"""
    return ProbeSelector()


# 测试函数
if __name__ == "__main__":
    # 示例测试
    selector = create_probe_selector()
    
    # 模拟数据
    vp_coordinates = {
        "probe1": (116.4074, 39.9042),  # 北京
        "probe2": (121.4737, 31.2304),  # 上海  
        "probe3": (113.2644, 23.1291),  # 广州
        "probe4": (104.0668, 30.5728),  # 成都
        "target": (120.1551, 30.2741),  # 杭州（目标）
    }
    
    rtt_data = {
        "probe1": 50.0,
        "probe2": 20.0, 
        "probe3": 80.0,
        "probe4": 70.0,
        "target": 0.0,
    }
    
    target_location = vp_coordinates["target"]
    
    # 测试各种策略
    strategies = ['all', 'l3', 'd3', 't3']
    for strategy in strategies:
        selected, status = selector.select_probes(
            strategy, "target", vp_coordinates, rtt_data, target_location
        )
        print(f"策略 {strategy}: 选择的探针数量 = {len(selected)}")
        print(f"选择的探针: {list(selected.keys())}")
        print(f"选择状态: {status}")
        print() 