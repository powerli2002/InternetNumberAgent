"""
Octant方法alpha和beta参数的网格搜索脚本

该脚本对Octant方法的环形边界系数alpha和beta进行网格搜索，
记录每个(alpha,beta)组合的P50、P95和CDF目标函数值，
最终生成三维可视化图表。
"""

import sys
import os
import numpy as np
import json
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import wandb
from typing import List, Tuple, Dict, Optional

# 添加项目根目录到路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# 导入项目模块
from scripts.optimized.utils import (
    load_dataset_from_files,
    prepare_octant_circles_for_target,
    get_target_anchors_with_sufficient_probes,
    get_ground_truth_location,
    calculate_haversine_distance,
    calculate_normalized_area_under_cdf,
    calculate_statistics_from_errors
)
from src.octant_ring_localizer import OctantRingLocalizer

# 全局变量
PROBE_DATA = None
ANCHOR_DATA = None
PING_DATA = None
TARGET_ANCHORS = None
X_MAX_CDF = 8000.0  # CDF计算的最大误差范围
OCTANT_LOCALIZER = None  # 全局Octant定位器


def load_global_data(data_dir: str):
    """加载全局数据"""
    global PROBE_DATA, ANCHOR_DATA, PING_DATA, TARGET_ANCHORS, OCTANT_LOCALIZER
    
    print("正在加载数据集...")
    PROBE_DATA, ANCHOR_DATA, PING_DATA = load_dataset_from_files(data_dir)
    
    print(f"加载完成：")
    print(f"  - Probe点(观测点)数量: {len(PROBE_DATA)}")
    print(f"  - Anchor点(待定位目标)数量: {len(ANCHOR_DATA)}")
    print(f"  - RTT测量数据条数: {len(PING_DATA)}")
    
    # 获取有足够probe测量数据的anchor列表
    TARGET_ANCHORS = get_target_anchors_with_sufficient_probes(ANCHOR_DATA, PING_DATA, min_measurements=3)
    print(f"  - 有足够测量数据的anchor数量: {len(TARGET_ANCHORS)}")
    
    # 初始化Octant定位器
    OCTANT_LOCALIZER = OctantRingLocalizer(
        buffer_resolution=32,
        inner_ratio=2/3,
        outer_ratio=4/3
    )


def perform_octant_localization(octant_circles: List[List], delta: float, alpha: float, beta: float) -> Optional[Tuple[float, float]]:
    """
    执行Octant定位
    
    Args:
        octant_circles: Octant环形数据列表
        delta: 延迟-距离转换系数
        alpha: 外边界系数
        beta: 内边界系数
    
    Returns:
        Optional[Tuple[float, float]]: (lon, lat) 或 None
    """
    if not octant_circles or OCTANT_LOCALIZER is None:
        return None
    
    try:
        # 调用Octant定位器
        result = OCTANT_LOCALIZER.locate_target_from_cbg_circles(octant_circles)
        return result
    
    except Exception as e:
        return None


def evaluate_octant_params(alpha: float, beta: float, delta: float = 0.05) -> Dict[str, float]:
    """
    评估某个(alpha, beta)参数组合的性能
    
    Args:
        alpha: 外边界系数
        beta: 内边界系数
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
        
        # 准备Octant环形数据
        octant_circles = prepare_octant_circles_for_target(target_anchor_ip, PROBE_DATA, PING_DATA, delta, alpha, beta)
        
        if len(octant_circles) < 3:  # 至少需要3个环才能定位
            continue
        
        # 执行Octant定位
        predicted_location = perform_octant_localization(octant_circles, delta, alpha, beta)
        
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
            "alpha": alpha,
            "beta": beta,
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
        "alpha": alpha,
        "beta": beta,
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


def grid_search_octant(data_dir: str, alpha_min: float = 1.1, alpha_max: float = 2.0, 
                      beta_min: float = 0.1, beta_max: float = 0.9, 
                      num_points_alpha: int = 20, num_points_beta: int = 20,
                      delta: float = 0.05):
    """
    对Octant的alpha和beta参数进行网格搜索
    
    Args:
        data_dir: 数据文件目录
        alpha_min: alpha最小值
        alpha_max: alpha最大值
        beta_min: beta最小值
        beta_max: beta最大值
        num_points_alpha: alpha搜索点数
        num_points_beta: beta搜索点数
        delta: 固定的delta值
    """
    # 初始化wandb
    wandb.init(
        project="cbg-octant-grid-search",
        name="octant-alpha-beta-grid-search",
        config={
            "method": "Octant",
            "parameters": "alpha_beta",
            "search_type": "grid_search",
            "alpha_min": alpha_min,
            "alpha_max": alpha_max,
            "beta_min": beta_min,
            "beta_max": beta_max,
            "num_points_alpha": num_points_alpha,
            "num_points_beta": num_points_beta,
            "delta_fixed": delta,
            "X_max_cdf": X_MAX_CDF,
            "data_directory": data_dir
        }
    )
    
    try:
        # 加载数据
        load_global_data(data_dir)
        
        # 生成搜索网格
        alpha_values = np.linspace(alpha_min, alpha_max, num_points_alpha)
        beta_values = np.linspace(beta_min, beta_max, num_points_beta)
        
        print(f"\n开始Octant alpha-beta参数网格搜索...")
        print(f"Alpha搜索范围: [{alpha_min}, {alpha_max}], 点数: {num_points_alpha}")
        print(f"Beta搜索范围: [{beta_min}, {beta_max}], 点数: {num_points_beta}")
        print(f"固定Delta值: {delta}")
        print(f"总搜索点数: {num_points_alpha * num_points_beta}")
        print(f"CDF最大误差范围: {X_MAX_CDF} km")
        print(f"待定位anchor数量: {len(TARGET_ANCHORS)}")
        print("-" * 80)
        
        results = []
        total_combinations = num_points_alpha * num_points_beta
        current_combination = 0
        
        for i, alpha in enumerate(alpha_values):
            for j, beta in enumerate(beta_values):
                current_combination += 1
                print(f"进度: {current_combination}/{total_combinations} | "
                      f"alpha={alpha:.3f}, beta={beta:.3f}")
                
                # 评估当前参数组合
                result = evaluate_octant_params(alpha, beta, delta)
                results.append(result)
                
                # 记录到wandb
                wandb.log(result)
                
                print(f"  成功: {result['successful_localizations']}/{result['total_attempts']} | "
                      f"P50: {result['P50']:.2f}km | P95: {result['P95']:.2f}km | "
                      f"CDF目标: {result['cdf_objective']:.6f}")
        
        # 保存结果到JSON文件
        output_file = "octant_alpha_beta_grid_search_results.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"\n结果已保存到: {output_file}")
        
        # 生成可视化图表
        generate_octant_visualization(results, alpha_values, beta_values)
        
        # 找到最优参数组合
        valid_results = [r for r in results if r['P50'] != float('inf')]
        if valid_results:
            best_p50 = min(valid_results, key=lambda x: x['P50'])
            best_p95 = min(valid_results, key=lambda x: x['P95'])
            best_cdf = min(valid_results, key=lambda x: x['cdf_objective'])
            
            print(f"\n最优结果：")
            print(f"最佳P50误差: alpha={best_p50['alpha']:.3f}, beta={best_p50['beta']:.3f}, P50={best_p50['P50']:.2f}km")
            print(f"最佳P95误差: alpha={best_p95['alpha']:.3f}, beta={best_p95['beta']:.3f}, P95={best_p95['P95']:.2f}km")
            print(f"最佳CDF目标: alpha={best_cdf['alpha']:.3f}, beta={best_cdf['beta']:.3f}, CDF目标={best_cdf['cdf_objective']:.6f}")
            
            # 记录最优结果到wandb
            wandb.log({
                "best_p50_alpha": best_p50['alpha'],
                "best_p50_beta": best_p50['beta'],
                "best_p50_value": best_p50['P50'],
                "best_p95_alpha": best_p95['alpha'],
                "best_p95_beta": best_p95['beta'],
                "best_p95_value": best_p95['P95'],
                "best_cdf_alpha": best_cdf['alpha'],
                "best_cdf_beta": best_cdf['beta'],
                "best_cdf_value": best_cdf['cdf_objective']
            })
    
    finally:
        wandb.finish()


def generate_octant_visualization(results: List[Dict[str, float]], alpha_values: np.ndarray, beta_values: np.ndarray):
    """
    生成Octant参数的三维可视化图表
    
    Args:
        results: 网格搜索结果列表
        alpha_values: alpha值数组
        beta_values: beta值数组
    """
    # 重新整理数据为网格格式
    alpha_grid, beta_grid = np.meshgrid(alpha_values, beta_values)
    
    # 初始化结果网格
    p50_grid = np.full(alpha_grid.shape, np.nan)
    p95_grid = np.full(alpha_grid.shape, np.nan)
    cdf_grid = np.full(alpha_grid.shape, np.nan)
    
    # 填充结果网格
    for result in results:
        alpha_idx = np.argmin(np.abs(alpha_values - result['alpha']))
        beta_idx = np.argmin(np.abs(beta_values - result['beta']))
        
        p50_val = result['P50'] if result['P50'] != float('inf') else np.nan
        p95_val = result['P95'] if result['P95'] != float('inf') else np.nan
        cdf_val = result['cdf_objective']
        
        p50_grid[beta_idx, alpha_idx] = p50_val
        p95_grid[beta_idx, alpha_idx] = p95_val
        cdf_grid[beta_idx, alpha_idx] = cdf_val
    
    # 不设置中文字体，使用默认英文字体
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['axes.unicode_minus'] = False
    
    # 创建三维图表
    fig = plt.figure(figsize=(20, 15))
    
    # P50误差三维图
    ax1 = fig.add_subplot(2, 3, 1, projection='3d')
    surf1 = ax1.plot_surface(alpha_grid, beta_grid, p50_grid, cmap='viridis', alpha=0.8)
    ax1.set_xlabel('Alpha Value')
    ax1.set_ylabel('Beta Value')
    ax1.set_zlabel('P50 Error (km)')
    ax1.set_title('Octant Method: Alpha-Beta vs P50 Error')
    plt.colorbar(surf1, ax=ax1, shrink=0.5)
    
    # P95误差三维图
    ax2 = fig.add_subplot(2, 3, 2, projection='3d')
    surf2 = ax2.plot_surface(alpha_grid, beta_grid, p95_grid, cmap='plasma', alpha=0.8)
    ax2.set_xlabel('Alpha Value')
    ax2.set_ylabel('Beta Value')
    ax2.set_zlabel('P95 Error (km)')
    ax2.set_title('Octant Method: Alpha-Beta vs P95 Error')
    plt.colorbar(surf2, ax=ax2, shrink=0.5)
    
    # CDF目标函数三维图
    ax3 = fig.add_subplot(2, 3, 3, projection='3d')
    surf3 = ax3.plot_surface(alpha_grid, beta_grid, cdf_grid, cmap='coolwarm', alpha=0.8)
    ax3.set_xlabel('Alpha Value')
    ax3.set_ylabel('Beta Value')
    ax3.set_zlabel('CDF Objective Value')
    ax3.set_title('Octant Method: Alpha-Beta vs CDF Objective')
    plt.colorbar(surf3, ax=ax3, shrink=0.5)
    
    # P50误差热力图
    ax4 = fig.add_subplot(2, 3, 4)
    im1 = ax4.imshow(p50_grid, cmap='viridis', aspect='auto', origin='lower',
                     extent=[alpha_values.min(), alpha_values.max(), 
                            beta_values.min(), beta_values.max()])
    ax4.set_xlabel('Alpha Value')
    ax4.set_ylabel('Beta Value')
    ax4.set_title('P50 Error Heatmap')
    plt.colorbar(im1, ax=ax4)
    
    # P95误差热力图
    ax5 = fig.add_subplot(2, 3, 5)
    im2 = ax5.imshow(p95_grid, cmap='plasma', aspect='auto', origin='lower',
                     extent=[alpha_values.min(), alpha_values.max(), 
                            beta_values.min(), beta_values.max()])
    ax5.set_xlabel('Alpha Value')
    ax5.set_ylabel('Beta Value')
    ax5.set_title('P95 Error Heatmap')
    plt.colorbar(im2, ax=ax5)
    
    # CDF目标函数热力图
    ax6 = fig.add_subplot(2, 3, 6)
    im3 = ax6.imshow(cdf_grid, cmap='coolwarm', aspect='auto', origin='lower',
                     extent=[alpha_values.min(), alpha_values.max(), 
                            beta_values.min(), beta_values.max()])
    ax6.set_xlabel('Alpha Value')
    ax6.set_ylabel('Beta Value')
    ax6.set_title('CDF Objective Heatmap')
    plt.colorbar(im3, ax=ax6)
    
    plt.tight_layout()
    
    # 保存图表
    plt.savefig('octant_alpha_beta_grid_search_visualization.png', dpi=300, bbox_inches='tight')
    
    # 记录图表到wandb
    wandb.log({"octant_alpha_beta_visualization": wandb.Image('octant_alpha_beta_grid_search_visualization.png')})
    
    print(f"Visualization chart saved as: octant_alpha_beta_grid_search_visualization.png")
    plt.show()


def main():
    """主函数"""
    data_dir = "data"
    
    # 运行网格搜索
    grid_search_octant(
        data_dir=data_dir,
        alpha_min=1.1,
        alpha_max=2.0,
        beta_min=0.1,
        beta_max=0.9,
        num_points_alpha=20,
        num_points_beta=20,
        delta=0.05  # 使用固定的delta值
    )


if __name__ == "__main__":
    main() 