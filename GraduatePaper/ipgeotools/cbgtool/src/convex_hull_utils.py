#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
凸包分析工具模块

提供加载和使用凸包分析结果的工具函数，支持Octant方法使用多项式约束。
"""

import json
import os
import numpy as np
from typing import Dict, Tuple, Optional, Any
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.utils.logging_manager import logger


def load_convex_hull_polynomials(analysis_result_file: str = None) -> Optional[Dict[str, Any]]:
    """
    加载凸包分析结果中的多项式系数
    
    Args:
        analysis_result_file: 分析结果文件路径，如果为None则使用默认路径
        
    Returns:
        Optional[Dict]: 包含多项式系数的字典，加载失败返回None
    """
    if analysis_result_file is None:
        # 默认路径
        default_path = os.path.join(
            os.path.dirname(__file__), '..', 
            'scripts', 'culcate_convex_hull', 'analysis_results.json'
        )
        analysis_result_file = os.path.abspath(default_path)
    
    try:
        with open(analysis_result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        boundary_functions = data.get('boundary_functions', {})
        
        if not boundary_functions:
            logger.warning(f"凸包分析结果文件中未找到boundary_functions: {analysis_result_file}")
            return None
            
        # 验证必要的字段
        required_fields = ['upper_poly', 'lower_poly']
        for field in required_fields:
            if field not in boundary_functions:
                logger.warning(f"凸包分析结果中缺少字段: {field}")
                return None
                
        logger.info(f"成功加载凸包多项式系数: {analysis_result_file}")
        return boundary_functions
        
    except FileNotFoundError:
        logger.warning(f"凸包分析结果文件未找到: {analysis_result_file}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"解析凸包分析结果文件失败: {e}")
        return None
    except Exception as e:
        logger.error(f"加载凸包分析结果时出错: {e}")
        return None


def calculate_boundary_distances(latency_ms: float, polynomials: Dict[str, Any], 
                                   fallback_distance_km: float = None) -> Tuple[Optional[float], Optional[float]]:
    """
    根据延迟和多项式计算上下边界距离
    
    Args:
        latency_ms: 延迟时间（毫秒）
        polynomials: 多项式系数字典，包含upper_poly和lower_poly
        fallback_distance_km: 当多项式计算失败时的回退距离（km），用于计算最小下边界
        
    Returns:
        Tuple[Optional[float], Optional[float]]: (下边界距离, 上边界距离)，单位km
    """
    try:
        upper_poly = np.array(polynomials['upper_poly'])
        lower_poly = np.array(polynomials['lower_poly'])
        
        # 计算多项式值：distance = a*latency^2 + b*latency + c
        # np.polyval 处理的是降序系数，即 [a, b, c] 表示 a*x^2 + b*x + c
        upper_distance = np.polyval(upper_poly, latency_ms)
        lower_distance = np.polyval(lower_poly, latency_ms)
        
        # 确保上边界为正值
        upper_distance = max(0, upper_distance)
        
        # 处理下边界：如果为负值或很小，使用fallback_distance的30%作为最小值
        min_lower_distance = 0.1  # 最小下边界距离（km）
        if fallback_distance_km is not None:
            min_lower_distance = max(min_lower_distance, fallback_distance_km * 0.3)
        
        lower_distance = max(min_lower_distance, lower_distance)
        
        # 确保下边界 <= 上边界
        if lower_distance > upper_distance:
            logger.warning(f"下边界距离({lower_distance:.2f}km)大于上边界距离({upper_distance:.2f}km)，延迟={latency_ms}ms")
            # 调整边界：下边界取上边界的70%，上边界保持不变
            lower_distance = upper_distance * 0.7
            
        return lower_distance, upper_distance
        
    except Exception as e:
        logger.error(f"计算边界距离时出错: {e}")
        return None, None


def validate_polynomial_constraints(polynomials: Dict[str, Any], min_latency: float = 0.1, max_latency: float = 200.0) -> bool:
    """
    验证多项式约束的有效性
    
    Args:
        polynomials: 多项式系数字典
        min_latency: 最小延迟（毫秒）
        max_latency: 最大延迟（毫秒）
        
    Returns:
        bool: True如果多项式有效，False否则
    """
    try:
        # 测试几个延迟值
        test_latencies = [min_latency, max_latency/2, max_latency]
        
        for latency in test_latencies:
            lower_dist, upper_dist = calculate_boundary_distances(latency, polynomials)
            
            if lower_dist is None or upper_dist is None:
                return False
                
            if lower_dist < 0 or upper_dist < 0:
                logger.warning(f"多项式产生负距离: 延迟={latency}ms, 下边界={lower_dist}km, 上边界={upper_dist}km")
                return False
                
            if lower_dist > upper_dist:
                logger.warning(f"下边界大于上边界: 延迟={latency}ms, 下边界={lower_dist}km, 上边界={upper_dist}km")
                return False
        
        logger.info("多项式约束验证通过")
        return True
        
    except Exception as e:
        logger.error(f"验证多项式约束时出错: {e}")
        return False


# 用于调试和测试的函数
def print_polynomial_info(polynomials: Dict[str, Any]):
    """
    打印多项式信息，用于调试
    
    Args:
        polynomials: 多项式系数字典
    """
    if not polynomials:
        print("多项式数据为空")
        return
        
    print("=== 凸包多项式信息 ===")
    
    if 'upper_poly' in polynomials:
        upper_poly = polynomials['upper_poly']
        print(f"上边界多项式: {upper_poly[0]:.6f}*x² + {upper_poly[1]:.6f}*x + {upper_poly[2]:.6f}")
        
    if 'lower_poly' in polynomials:
        lower_poly = polynomials['lower_poly']
        print(f"下边界多项式: {lower_poly[0]:.6f}*x² + {lower_poly[1]:.6f}*x + {lower_poly[2]:.6f}")
        
    if 'delta' in polynomials:
        print(f"光速比例 (δ): {polynomials['delta']:.4f}")
        
    # 测试几个延迟值
    test_latencies = [10, 30, 50, 100]
    print("\n延迟测试:")
    print("延迟(ms)\t下边界(km)\t上边界(km)")
    print("-" * 40)
    
    for latency in test_latencies:
        lower_dist, upper_dist = calculate_boundary_distances(latency, polynomials)
        if lower_dist is not None and upper_dist is not None:
            print(f"{latency}\t\t{lower_dist:.2f}\t\t{upper_dist:.2f}")
        else:
            print(f"{latency}\t\t计算失败\t\t计算失败")


if __name__ == "__main__":
    # 测试功能
    polynomials = load_convex_hull_polynomials()
    if polynomials:
        print_polynomial_info(polynomials)
        
        # 验证约束
        is_valid = validate_polynomial_constraints(polynomials)
        print(f"\n多项式约束有效性: {is_valid}")
    else:
        print("无法加载凸包多项式数据") 