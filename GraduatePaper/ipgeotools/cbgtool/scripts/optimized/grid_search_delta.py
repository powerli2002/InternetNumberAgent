"""
CBG方法delta参数的网格搜索脚本

该脚本对CBG方法的延迟-距离转换系数delta进行网格搜索，
记录每个delta值的P50、P95和CDF目标函数值，
最终生成二维可视化图表。
"""

import sys
import os
import numpy as np
import json
import matplotlib.pyplot as plt
import seaborn as sns
import wandb
from typing import List, Tuple, Dict, Optional

# 添加项目根目录到路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# 导入项目模块
from scripts.optimized.utils import (
    load_dataset_from_files,
    prepare_cbg_circles_for_target,
    get_target_anchors_with_sufficient_probes,
    get_ground_truth_location,
    calculate_haversine_distance,
    calculate_normalized_area_under_cdf,
    calculate_statistics_from_errors
)
from scripts.utils.helpers import circle_intersections, polygon_centroid

# 全局变量
PROBE_DATA = None
ANCHOR_DATA = None
PING_DATA = None
TARGET_ANCHORS = None
X_MAX_CDF = 8000.0  # CDF计算的最大误差范围


def load_global_data(data_dir: str):
    """加载全局数据"""
    global PROBE_DATA, ANCHOR_DATA, PING_DATA, TARGET_ANCHORS
    
    print("正在加载数据集...")
    PROBE_DATA, ANCHOR_DATA, PING_DATA = load_dataset_from_files(data_dir)
    
    print(f"加载完成：")
    print(f"  - Probe点(观测点)数量: {len(PROBE_DATA)}")
    print(f"  - Anchor点(待定位目标)数量: {len(ANCHOR_DATA)}")
    print(f"  - RTT测量数据条数: {len(PING_DATA)}")
    
    # 获取有足够probe测量数据的anchor列表
    TARGET_ANCHORS = get_target_anchors_with_sufficient_probes(ANCHOR_DATA, PING_DATA, min_measurements=3)
    print(f"  - 有足够测量数据的anchor数量: {len(TARGET_ANCHORS)}")


def perform_cbg_localization(cbg_circles: List[Tuple], delta: float) -> Optional[Tuple[float, float]]:
    """
    执行CBG定位
    
    Args:
        cbg_circles: CBG圆形数据列表
        delta: 延迟-距离转换系数
    
    Returns:
        Optional[Tuple[float, float]]: (lon, lat) 或 None
    """
    if not cbg_circles:
        return None
    
    try:
        # 调用现有的CBG核心算法
        filtered_points, processed_circles = circle_intersections(cbg_circles, delta=delta, speed_threshold=None)
        
        if not filtered_points:
            return None
        
        # 计算质心
        centroid_lon, centroid_lat = polygon_centroid(filtered_points)
        return (centroid_lon, centroid_lat)
    
    except Exception as e:
        return None


def evaluate_delta(delta: float) -> Dict[str, float]:
    """
    评估某个delta值的性能
    
    Args:
        delta: 延迟-距离转换系数
    
    Returns:
        Dict[str, float]: 包含各种性能指标的字典
    """
    errors_list = []
    successful_localizations = 0
    total_attempts = 0
    
    for target_anchor_ip in TARGET_ANCHORS:
        total_attempts += 1
        
        # 获取真实位置
        ground_truth = get_ground_truth_location(target_anchor_ip, ANCHOR_DATA)
        if ground_truth is None:
            continue
        
        true_lat, true_lon = ground_truth
        
        # 准备CBG圆形数据
        cbg_circles = prepare_cbg_circles_for_target(target_anchor_ip, PROBE_DATA, PING_DATA, delta)
        
        if len(cbg_circles) < 3:  # 至少需要3个圆才能定位
            continue
        
        # 执行CBG定位
        predicted_location = perform_cbg_localization(cbg_circles, delta)
        
        if predicted_location is None:
            continue
        
        pred_lon, pred_lat = predicted_location
        
        # 计算误差
        error_km = calculate_haversine_distance(true_lat, true_lon, pred_lat, pred_lon)
        errors_list.append(error_km)
        successful_localizations += 1
    
    # 计算各项指标
    if not errors_list:
        return {
            "delta": delta,
            "P50": float('inf'),
            "P95": float('inf'),
            "cdf_objective": 1.0,
            "normalized_area_under_cdf": 0.0,
            "successful_localizations": 0,
            "total_attempts": total_attempts,
            "success_rate": 0.0,
            "mean_error_km": float('inf'),
            "min_error_km": float('inf'),
            "max_error_km": float('inf')
        }
    
    # 计算统计指标
    stats = calculate_statistics_from_errors(errors_list)
    normalized_area = calculate_normalized_area_under_cdf(errors_list, X_MAX_CDF)
    cdf_objective = 1.0 - normalized_area
    
    results = {
        "delta": delta,
        "P50": np.percentile(errors_list, 50),
        "P95": np.percentile(errors_list, 95),
        "cdf_objective": cdf_objective,
        "normalized_area_under_cdf": normalized_area,
        "successful_localizations": successful_localizations,
        "total_attempts": total_attempts,
        "success_rate": successful_localizations / total_attempts if total_attempts > 0 else 0,
        **stats
    }
    
    return results


def grid_search_delta(data_dir: str, delta_min: float = 0.001, delta_max: float = 0.1, num_points: int = 50):
    """
    对delta参数进行网格搜索
    
    Args:
        data_dir: 数据文件目录
        delta_min: delta最小值
        delta_max: delta最大值
        num_points: 搜索点数
    """
    # 初始化wandb
    wandb.init(
        project="cbg-octant-grid-search",
        name="cbg-delta-grid-search",
        config={
            "method": "CBG",
            "parameter": "delta",
            "search_type": "grid_search",
            "delta_min": delta_min,
            "delta_max": delta_max,
            "num_points": num_points,
            "X_max_cdf": X_MAX_CDF,
            "data_directory": data_dir
        }
    )
    
    try:
        # 加载数据
        load_global_data(data_dir)
        
        # 生成delta搜索网格
        delta_values = np.linspace(delta_min, delta_max, num_points)
        
        print(f"\n开始CBG delta参数网格搜索...")
        print(f"搜索范围: [{delta_min}, {delta_max}]")
        print(f"搜索点数: {num_points}")
        print(f"CDF最大误差范围: {X_MAX_CDF} km")
        print(f"待定位anchor数量: {len(TARGET_ANCHORS)}")
        print("-" * 80)
        
        results = []
        for i, delta in enumerate(delta_values):
            print(f"进度: {i+1}/{num_points} | delta={delta:.6f}")
            
            # 评估当前delta值
            result = evaluate_delta(delta)
            results.append(result)
            
            # 记录到wandb
            wandb.log(result)
            
            print(f"  成功: {result['successful_localizations']}/{result['total_attempts']} | "
                  f"P50: {result['P50']:.2f}km | P95: {result['P95']:.2f}km | "
                  f"CDF目标: {result['cdf_objective']:.6f}")
        
        # 保存结果到JSON文件
        output_file = "delta_grid_search_results.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"\n结果已保存到: {output_file}")
        
        # 生成可视化图表
        generate_delta_visualization(results)
        
        # 找到最优delta值
        valid_results = [r for r in results if r['P50'] != float('inf')]
        if valid_results:
            best_p50 = min(valid_results, key=lambda x: x['P50'])
            best_p95 = min(valid_results, key=lambda x: x['P95'])
            best_cdf = min(valid_results, key=lambda x: x['cdf_objective'])
            
            print(f"\n最优结果：")
            print(f"最佳P50误差: delta={best_p50['delta']:.6f}, P50={best_p50['P50']:.2f}km")
            print(f"最佳P95误差: delta={best_p95['delta']:.6f}, P95={best_p95['P95']:.2f}km")
            print(f"最佳CDF目标: delta={best_cdf['delta']:.6f}, CDF目标={best_cdf['cdf_objective']:.6f}")
            
            # 记录最优结果到wandb
            wandb.log({
                "best_p50_delta": best_p50['delta'],
                "best_p50_value": best_p50['P50'],
                "best_p95_delta": best_p95['delta'],
                "best_p95_value": best_p95['P95'],
                "best_cdf_delta": best_cdf['delta'],
                "best_cdf_value": best_cdf['cdf_objective']
            })
    
    finally:
        wandb.finish()


def generate_delta_visualization(results: List[Dict[str, float]]):
    """
    生成delta参数的二维可视化图表
    
    Args:
        results: 网格搜索结果列表
    """
    # 提取数据
    delta_values = [r['delta'] for r in results]
    p50_values = [r['P50'] if r['P50'] != float('inf') else np.nan for r in results]
    p95_values = [r['P95'] if r['P95'] != float('inf') else np.nan for r in results]
    cdf_objectives = [r['cdf_objective'] for r in results]
    
    # 不设置中文字体，使用默认英文字体
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['axes.unicode_minus'] = False
    
    # 创建图表
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 12))
    
    # P50误差曲线
    ax1.plot(delta_values, p50_values, 'b-', linewidth=2, marker='o', markersize=4)
    ax1.set_xlabel('Delta Value')
    ax1.set_ylabel('P50 Error (km)')
    ax1.set_title('CBG Method: Delta vs P50 Error')
    ax1.grid(True, alpha=0.3)
    
    # P95误差曲线
    ax2.plot(delta_values, p95_values, 'r-', linewidth=2, marker='s', markersize=4)
    ax2.set_xlabel('Delta Value')
    ax2.set_ylabel('P95 Error (km)')
    ax2.set_title('CBG Method: Delta vs P95 Error')
    ax2.grid(True, alpha=0.3)
    
    # CDF目标函数曲线
    ax3.plot(delta_values, cdf_objectives, 'g-', linewidth=2, marker='^', markersize=4)
    ax3.set_xlabel('Delta Value')
    ax3.set_ylabel('CDF Objective (1-normalized_area)')
    ax3.set_title('CBG Method: Delta vs CDF Objective')
    ax3.grid(True, alpha=0.3)
    
    # 综合对比图
    # 为了在同一图中显示，对数值进行归一化
    p50_norm = np.array(p50_values)
    p95_norm = np.array(p95_values) 
    cdf_norm = np.array(cdf_objectives)
    
    # 去除无穷大值并归一化
    valid_mask = ~np.isnan(p50_norm) & ~np.isnan(p95_norm)
    if np.any(valid_mask):
        p50_valid = p50_norm[valid_mask]
        p95_valid = p95_norm[valid_mask]
        cdf_valid = cdf_norm[valid_mask]
        delta_valid = np.array(delta_values)[valid_mask]
        
        p50_normalized = (p50_valid - np.min(p50_valid)) / (np.max(p50_valid) - np.min(p50_valid)) if np.max(p50_valid) > np.min(p50_valid) else np.zeros_like(p50_valid)
        p95_normalized = (p95_valid - np.min(p95_valid)) / (np.max(p95_valid) - np.min(p95_valid)) if np.max(p95_valid) > np.min(p95_valid) else np.zeros_like(p95_valid)
        cdf_normalized = (cdf_valid - np.min(cdf_valid)) / (np.max(cdf_valid) - np.min(cdf_valid)) if np.max(cdf_valid) > np.min(cdf_valid) else np.zeros_like(cdf_valid)
        
        ax4.plot(delta_valid, p50_normalized, 'b-', label='P50 (normalized)', linewidth=2)
        ax4.plot(delta_valid, p95_normalized, 'r-', label='P95 (normalized)', linewidth=2)
        ax4.plot(delta_valid, cdf_normalized, 'g-', label='CDF Objective (normalized)', linewidth=2)
    
    ax4.set_xlabel('Delta Value')
    ax4.set_ylabel('Normalized Value')
    ax4.set_title('CBG Method: Normalized Metrics Comparison')
    ax4.legend()
    ax4.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # 保存图表
    plt.savefig('cbg_delta_grid_search_visualization.png', dpi=300, bbox_inches='tight')
    
    # 记录图表到wandb
    wandb.log({"delta_visualization": wandb.Image('cbg_delta_grid_search_visualization.png')})
    
    print(f"Visualization chart saved as: cbg_delta_grid_search_visualization.png")
    plt.show()


def main():
    """主函数"""
    data_dir = "data"
    
    # 运行网格搜索
    grid_search_delta(
        data_dir=data_dir,
        delta_min=0.001,
        delta_max=0.1,
        num_points=50
    )


if __name__ == "__main__":
    main() 