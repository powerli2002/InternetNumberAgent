"""
优化脚本的辅助函数工具集

包含用于CBG和Octant超参数优化的各种辅助函数。
"""

import numpy as np
import pandas as pd
import json
import math
from typing import List, Tuple, Dict, Optional, Any


def calculate_haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    使用Haversine公式计算两个地理坐标点之间的球面距离（公里）
    
    Args:
        lat1, lon1: 第一个点的纬度和经度（度）
        lat2, lon2: 第二个点的纬度和经度（度）
    
    Returns:
        float: 两点之间的距离（公里）
    """
    # 将度转换为弧度
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    # Haversine公式
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = (math.sin(dlat / 2) ** 2 + 
         math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    
    c = 2 * math.asin(math.sqrt(a))
    
    # 地球半径（公里）
    r = 6371.0
    
    return c * r


def calculate_normalized_area_under_cdf(errors_list: List[float], X_max_cdf: float = 200.0) -> float:
    """
    计算CDF曲线下方到指定最大误差的归一化面积
    
    Args:
        errors_list: 包含所有有效定位误差的列表（公里）
        X_max_cdf: 计算CDF面积的误差上限（公里），默认8000
    
    Returns:
        float: 归一化面积，值在[0, 1]区间
    """
    if not errors_list:
        return 0.0
    
    # 对误差列表进行排序
    sorted_errors = sorted(errors_list)
    n = len(sorted_errors)
    
    # 构建CDF曲线的点集
    x_coords = [0.0]  # 从0开始
    y_coords = [0.0]  # 对应的累积概率
    
    # 添加排序后的误差值和对应的累积概率
    for i, error in enumerate(sorted_errors):
        if error <= X_max_cdf:
            x_coords.append(error)
            y_coords.append((i + 1) / n)
    
    # 确保包含X_max_cdf这一点
    if x_coords[-1] < X_max_cdf:
        # 找到在X_max_cdf处的累积概率
        cum_prob_at_max = sum(1 for e in sorted_errors if e <= X_max_cdf) / n
        x_coords.append(X_max_cdf)
        y_coords.append(cum_prob_at_max)
    
    # 使用梯形法则计算CDF曲线下的面积
    area_under_cdf = np.trapz(y_coords, x_coords)
    
    # 计算归一化面积
    # area_under_cdf 的最大可能值是 1.0 * X_max_cdf (在理想情况下，Y值恒为1)。因此，用它除以 X_max_cdf 可以将结果缩放到 [0, 1] 区间
    normalized_area = area_under_cdf / X_max_cdf
    
    # 确保值在[0, 1]区间
    return max(0.0, min(1.0, normalized_area))


def load_dataset_from_files(data_dir: str) -> Tuple[Dict, Dict, Dict]:
    """
    从数据文件中加载完整的数据集
    
    Args:
        data_dir: 数据文件目录路径
    
    Returns:
        Tuple[Dict, Dict, Dict]: (probe_data, anchor_data, ping_data)
            - probe_data: {ip: {lat, lon, city, ...}} 观测点数据
            - anchor_data: {ip: {lat, lon, city, ...}} 待定位目标数据
            - ping_data: {(src_ip, dst_ip): rtt} RTT测量数据
    """
    import os
    
    # 尝试多个可能的文件路径
    possible_paths = [
        os.path.join(data_dir, "format"),  # 优先查找format子目录
        data_dir  # 备选项：直接在数据目录下
    ]
    
    json_file = None
    ping_file = None
    
    # 查找JSON文件
    for path in possible_paths:
        candidate_json = os.path.join(path, "user_probes_and_anchors.json")
        if os.path.exists(candidate_json):
            json_file = candidate_json
            break
    
    # 查找CSV文件
    for path in possible_paths:
        candidate_csv = os.path.join(path, "ping_to_anchors.csv")
        if os.path.exists(candidate_csv):
            ping_file = candidate_csv
            break
    
    if json_file is None:
        raise FileNotFoundError(f"找不到 user_probes_and_anchors.json 文件，在以下路径中查找: {possible_paths}")
    
    if ping_file is None:
        raise FileNotFoundError(f"找不到 ping_to_anchors.csv 文件，在以下路径中查找: {possible_paths}")
    
    print(f"使用数据文件：")
    print(f"  - JSON文件: {json_file}")
    print(f"  - CSV文件: {ping_file}")
    
    # 解析probes和anchors数据
    probe_data = {}  # 观测点 (is_anchor=false)
    anchor_data = {}  # 待定位目标 (is_anchor=true)
    
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        for item in data:
            ip = item['address_v4']
            coords = item['geometry']['coordinates']  # [lat, lon]
            
            info = {
                'lat': coords[0],
                'lon': coords[1],
                'city': item.get('city', ''),
                'country_code': item.get('country_code', ''),
                'asn_v4': item.get('asn_v4', ''),
                'is_anchor': item.get('is_anchor', False)
            }
            
            if item.get('is_anchor', False):
                anchor_data[ip] = info  # 待定位目标
            else:
                probe_data[ip] = info   # 观测点
    
    # 加载ping数据
    ping_data = {}
    df = pd.read_csv(ping_file)
    
    for _, row in df.iterrows():
        src_ip = row['src']  # probe
        dst_ip = row['dst']  # anchor
        rtt = row['min_rtt']
        
        ping_data[(src_ip, dst_ip)] = rtt
    
    return probe_data, anchor_data, ping_data


def prepare_cbg_circles_for_target(target_anchor_ip: str, probe_data: Dict, ping_data: Dict, delta: float) -> List[Tuple]:
    """
    为指定目标anchor IP准备CBG圆形数据
    
    Args:
        target_anchor_ip: 目标anchor IP地址
        probe_data: probe点(观测点)数据字典
        ping_data: ping数据字典
        delta: 延迟-距离转换系数（将在circle_intersections内部使用）
    
    Returns:
        List[Tuple]: CBG圆形数据列表，格式为 [(probe_lon, probe_lat, rtt_ms, None, None), ...]
                    距离和半径将由circle_intersections函数内部计算
    """
    cbg_circles = []
    
    for (src_ip, dst_ip), rtt in ping_data.items():
        if dst_ip == target_anchor_ip and src_ip in probe_data:
            # 获取probe坐标
            probe_info = probe_data[src_ip]
            probe_lon = probe_info['lon']
            probe_lat = probe_info['lat']
            
            # 只传入坐标和RTT，距离计算交给circle_intersections函数
            # 格式：(lon, lat, rtt, d, r) - d和r设为None让circle_intersections内部计算
            cbg_circles.append((probe_lon, probe_lat, rtt, None, None))
    
    return cbg_circles


def prepare_octant_circles_for_target(target_anchor_ip: str, probe_data: Dict, ping_data: Dict, 
                                    delta: float, alpha: float, beta: float) -> List[List]:
    """
    为指定目标anchor IP准备Octant环形数据
    
    Args:
        target_anchor_ip: 目标anchor IP地址
        probe_data: probe点(观测点)数据字典
        ping_data: ping数据字典
        delta: 延迟-距离转换系数
        alpha: 外边界系数
        beta: 内边界系数
    
    Returns:
        List[List]: Octant环形数据列表，格式为 [[lon, lat, rtt, base_d_km, r_radians, inner_radius_km, outer_radius_km], ...]
    """
    octant_circles = []
    
    for (src_ip, dst_ip), rtt in ping_data.items():
        if dst_ip == target_anchor_ip and src_ip in probe_data:
            # 获取probe坐标
            probe_info = probe_data[src_ip]
            probe_lon = probe_info['lon']
            probe_lat = probe_info['lat']
            
            # 计算基础距离（统一使用delta参数）
            c = 300.0  # km/ms
            base_distance_km = delta * rtt * c / 2
            
            # 计算内外边界半径
            outer_radius_km = alpha * base_distance_km
            inner_radius_km = beta * base_distance_km
            
            # 转换为弧度（用于CBG兼容）
            earth_radius_km = 6371.0
            radius_radians = base_distance_km / earth_radius_km
            
            # Octant格式: [lon, lat, rtt, d_km, r_radians, inner_radius_km, outer_radius_km]
            octant_circles.append([probe_lon, probe_lat, rtt, base_distance_km, radius_radians, 
                                 inner_radius_km, outer_radius_km])
    
    return octant_circles


def get_target_anchors_with_sufficient_probes(anchor_data: Dict, ping_data: Dict, min_measurements: int = 3) -> List[str]:
    """
    获取有足够probe测量数据的目标anchor IP列表
    
    Args:
        anchor_data: anchor数据字典
        ping_data: ping数据字典
        min_measurements: 最少需要的测量数量
    
    Returns:
        List[str]: 符合条件的anchor IP列表
    """
    target_anchors = []
    
    # 统计每个anchor IP的测量数量
    measurement_counts = {}
    for (src_ip, dst_ip), rtt in ping_data.items():
        if dst_ip in anchor_data:  # 只考虑有真实位置的anchor
            measurement_counts[dst_ip] = measurement_counts.get(dst_ip, 0) + 1
    
    # 筛选有足够测量数据的anchor IP
    for anchor_ip, count in measurement_counts.items():
        if count >= min_measurements:
            target_anchors.append(anchor_ip)
    
    return target_anchors


def get_ground_truth_location(anchor_ip: str, anchor_data: Dict) -> Optional[Tuple[float, float]]:
    """
    获取目标anchor IP的真实地理位置
    
    Args:
        anchor_ip: 目标anchor IP地址
        anchor_data: anchor数据字典
    
    Returns:
        Optional[Tuple[float, float]]: (lat, lon) 或 None
    """
    if anchor_ip in anchor_data:
        info = anchor_data[anchor_ip]
        return (info['lat'], info['lon'])
    return None


def calculate_statistics_from_errors(errors_list: List[float]) -> Dict[str, float]:
    """
    从误差列表计算各种统计指标
    
    Args:
        errors_list: 误差列表（公里）
    
    Returns:
        Dict[str, float]: 包含各种统计指标的字典
    """
    if not errors_list:
        return {
            "mean_error_km": float('inf'),
            "median_error_km": float('inf'),
            "p75_error_km": float('inf'),
            "p90_error_km": float('inf'),
            "accuracy_at_200km": 0.0,
            "accuracy_at_500km": 0.0,
            "accuracy_at_800km": 0.0,
        }
    
    errors_array = np.array(errors_list)
    
    return {
        "mean_error_km": np.mean(errors_array),
        "median_error_km": np.median(errors_array),
        "p75_error_km": np.percentile(errors_array, 75),
        "p90_error_km": np.percentile(errors_array, 90),
        "accuracy_at_200km": len([e for e in errors_list if e <= 200]) / len(errors_list),
        "accuracy_at_500km": len([e for e in errors_list if e <= 500]) / len(errors_list),
        "accuracy_at_800km": len([e for e in errors_list if e <= 800]) / len(errors_list),
    } 