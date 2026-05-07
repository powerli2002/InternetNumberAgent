#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
凸包方法分析距离-延迟关系

基于Octant论文中的方法，通过构建凸包来分析网络延迟与地理距离的关系，
计算距离-延迟转换系数。

"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy.spatial import ConvexHull
from geopy.distance import geodesic
import json
import os
import warnings
from typing import Dict, Tuple, List, Optional
import logging
from datetime import datetime

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 忽略警告
warnings.filterwarnings('ignore')

# 设置中文字体支持
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

class CityGeocoder:
    """城市地理编码器"""
    
    def __init__(self):
        """初始化地理编码器，包含美国主要城市的经纬度信息"""
        self.city_coordinates = {
            # 标准化城市名映射到经纬度
            'ashburn': (39.0438, -77.4874),
            'atlanta': (33.7490, -84.3880),
            'boston': (42.3601, -71.0589),
            'buffalo': (42.8864, -78.8784),
            'chicago': (41.8781, -87.6298),
            'dallas': (32.7767, -96.7970),
            'durham': (35.9940, -78.8986),
            'flint': (43.0125, -83.6875),
            'greenwoodvillage': (39.6134, -104.8511),
            'honolulu': (21.3099, -157.8581),
            'kansas': (39.0997, -94.5786),  # Kansas City
            'lasvegas': (36.1699, -115.1398),
            'layton': (41.0602, -111.9711),
            'losangeles': (34.0522, -118.2437),
            'miami': (25.7617, -80.1918),
            'newark': (40.7357, -74.1724),
            'newyorkcity': (40.7128, -74.0060),
            'ottoville': (40.9370, -84.3528),
            'phoenix': (33.4484, -112.0740),
            'portland': (45.5152, -122.6784),
            'saltlake': (40.7608, -111.8910),
            'seattle': (47.6062, -122.3321),
            'southfield': (42.4734, -83.2219),
            'taos': (36.4072, -105.5731),
            'vinings': (33.8696, -84.4636),
            'portedwards': (44.3167, -89.8667),  # Port Edwards, WI
        }
    
    def normalize_city_name(self, city_region: str) -> str:
        """标准化城市名称"""
        # 移除国家前缀和后缀，转换为小写
        city = city_region.lower()
        
        # 移除常见前缀
        prefixes = ['us-', 'usa-', 'united states-']
        for prefix in prefixes:
            if city.startswith(prefix):
                city = city[len(prefix):]
                break
        
        # # 特殊映射
        # special_mappings = {
        #     'kansas': 'kansas',
        #     'greenwoodvillage': 'greenwoodvillage',
        #     'portedwards': 'portedwards',
        #     'newyorkcity': 'newyorkcity'
        # }
        
        # for key, value in special_mappings.items():
        #     if key in city:
        #         return value
        
        return city
    
    def get_coordinates(self, city_region: str) -> Optional[Tuple[float, float]]:
        """获取城市的经纬度坐标"""
        normalized = self.normalize_city_name(city_region)
        return self.city_coordinates.get(normalized)

class LatencyDistanceAnalyzer:
    """延迟-距离分析器"""
    
    def __init__(self, data_file: str, output_dir: str = '.'):
        """
        初始化分析器
        
        Args:
            data_file: CSV数据文件路径
            output_dir: 输出目录
        """
        self.data_file = data_file
        self.output_dir = output_dir
        self.geocoder = CityGeocoder()
        self.raw_data = None
        self.processed_data = None
        self.outlier_data = None
        self.convex_hull = None
        self.results = {}
        
        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)
        
    def load_data(self) -> pd.DataFrame:
        """加载和初步处理数据"""
        logger.info("加载数据文件...")
        
        # 读取CSV文件
        df = pd.read_csv(self.data_file)
        
        # 移除延迟为空的记录
        df = df.dropna(subset=['ms'])
        
        # 移除自环（源和目标相同的记录）
        df = df[df['source_region'] != df['target_region']]
        
        logger.info(f"加载完成，共有 {len(df)} 条有效记录")
        self.raw_data = df
        return df
    
    def geocode_cities(self) -> pd.DataFrame:
        """为城市添加地理坐标"""
        logger.info("进行地理编码...")
        
        df = self.raw_data.copy()
        
        # 获取所有唯一的城市
        all_cities = set(df['source_region'].unique()) | set(df['target_region'].unique())
        
        # 为每个城市获取坐标
        city_coords = {}
        missing_cities = []
        
        for city in all_cities:
            coords = self.geocoder.get_coordinates(city)
            if coords:
                city_coords[city] = coords
            else:
                missing_cities.append(city)
        
        if missing_cities:
            logger.warning(f"无法找到以下城市的坐标: {missing_cities}")
        
        # 添加坐标列
        df['source_lat'] = df['source_region'].map(lambda x: city_coords.get(x, (None, None))[0])
        df['source_lon'] = df['source_region'].map(lambda x: city_coords.get(x, (None, None))[1])
        df['target_lat'] = df['target_region'].map(lambda x: city_coords.get(x, (None, None))[0])
        df['target_lon'] = df['target_region'].map(lambda x: city_coords.get(x, (None, None))[1])
        
        # 移除缺少坐标的记录
        df = df.dropna(subset=['source_lat', 'source_lon', 'target_lat', 'target_lon'])
        
        logger.info(f"地理编码完成，剩余 {len(df)} 条记录")
        return df
    
    def calculate_distances(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算大圆距离"""
        logger.info("计算地理距离...")
        
        distances = []
        for _, row in df.iterrows():
            source = (row['source_lat'], row['source_lon'])
            target = (row['target_lat'], row['target_lon'])
            dist = geodesic(source, target).kilometers
            distances.append(dist)
        
        df['distance_km'] = distances
        logger.info("距离计算完成")
        return df
    
    def detect_outliers(self, df: pd.DataFrame, method='iqr', factor=2.5) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """检测和移除离群点"""
        logger.info("检测离群点...")
        
        if method == 'iqr':
            # 使用IQR方法检测离群点
            Q1_lat = df['ms'].quantile(0.25)
            Q3_lat = df['ms'].quantile(0.75)
            IQR_lat = Q3_lat - Q1_lat
            
            Q1_dist = df['distance_km'].quantile(0.25)
            Q3_dist = df['distance_km'].quantile(0.75)
            IQR_dist = Q3_dist - Q1_dist
            
            # 定义离群点
            outlier_condition = (
                (df['ms'] < (Q1_lat - factor * IQR_lat)) |
                (df['ms'] > (Q3_lat + factor * IQR_lat)) |
                (df['distance_km'] < (Q1_dist - factor * IQR_dist)) |
                (df['distance_km'] > (Q3_dist + factor * IQR_dist))
            )
        
        elif method == 'zscore':
            # 使用Z-score方法
            from scipy import stats
            z_scores_lat = np.abs(stats.zscore(df['ms']))
            z_scores_dist = np.abs(stats.zscore(df['distance_km']))
            outlier_condition = (z_scores_lat > factor) | (z_scores_dist > factor)
        
        else:
            # 基于延迟/距离比率的方法
            df['latency_distance_ratio'] = df['ms'] / df['distance_km']
            Q1 = df['latency_distance_ratio'].quantile(0.25)
            Q3 = df['latency_distance_ratio'].quantile(0.75)
            IQR = Q3 - Q1
            outlier_condition = (
                (df['latency_distance_ratio'] < (Q1 - factor * IQR)) |
                (df['latency_distance_ratio'] > (Q3 + factor * IQR))
            )
        
        outliers = df[outlier_condition]
        clean_data = df[~outlier_condition]
        
        logger.info(f"检测到 {len(outliers)} 个离群点，保留 {len(clean_data)} 条记录")
        
        self.outlier_data = outliers
        return clean_data, outliers
    
    def compute_convex_hull(self, df: pd.DataFrame) -> Dict:
        """计算凸包"""
        logger.info("计算凸包...")
        
        # 更改坐标：横轴为延迟(ms)，纵轴为距离(km)
        points = np.column_stack([df['ms'], df['distance_km']])
        
        try:
            hull = ConvexHull(points)
            self.convex_hull = hull
            
            # 获取凸包顶点
            hull_points = points[hull.vertices]
            
            # 找到最左和最右的点（现在是最小和最大延迟）
            leftmost_idx = np.argmin(hull_points[:, 0])  # 最小延迟
            rightmost_idx = np.argmax(hull_points[:, 0])  # 最大延迟
            
            leftmost_point = hull_points[leftmost_idx]
            rightmost_point = hull_points[rightmost_idx]
            
            # 分离上下边界
            upper_hull = []
            lower_hull = []
            
            # 从最左点开始，按凸包顶点顺序遍历
            vertices = hull.vertices
            # 找到最左点在vertices中的索引
            left_vertex_idx = np.where(vertices == np.where((points == leftmost_point).all(axis=1))[0][0])[0][0]
            
            # 重新排列vertices，从最左点开始
            reordered_vertices = np.concatenate([vertices[left_vertex_idx:], vertices[:left_vertex_idx]])
            
            # 按凸包边界分离上下部分
            for i, vertex_idx in enumerate(reordered_vertices):
                point = points[vertex_idx]
                
                # 判断该点是在上边界还是下边界
                # 通过计算点相对于连接最左和最右点的直线的位置来判断
                if len(upper_hull) == 0 and len(lower_hull) == 0:
                    # 第一个点（最小延迟点）
                    upper_hull.append(point)
                    lower_hull.append(point)
                else:
                    # 计算点相对于最小延迟-最大延迟连线的位置
                    # 使用叉积判断点在直线的上方还是下方
                    v1 = rightmost_point - leftmost_point
                    v2 = point - leftmost_point
                    cross_product = v1[0] * v2[1] - v1[1] * v2[0]
                    
                    if cross_product >= 0:  # 上方
                        upper_hull.append(point)
                    else:  # 下方
                        lower_hull.append(point)
            
            # 确保最右点在两个边界中
            if not any(np.array_equal(rightmost_point, p) for p in upper_hull):
                upper_hull.append(rightmost_point)
            if not any(np.array_equal(rightmost_point, p) for p in lower_hull):
                lower_hull.append(rightmost_point)
            
            # 按x坐标排序（现在是延迟）
            upper_hull = np.array(sorted(upper_hull, key=lambda p: p[0]))
            lower_hull = np.array(sorted(lower_hull, key=lambda p: p[0]))
            
            hull_info = {
                'hull_object': hull,
                'all_points': hull_points,
                'upper_boundary': upper_hull,
                'lower_boundary': lower_hull,
                'leftmost_point': leftmost_point,
                'rightmost_point': rightmost_point
            }
            
            logger.info(f"凸包计算完成，包含 {len(hull.vertices)} 个顶点")
            logger.info(f"上边界包含 {len(upper_hull)} 个点，下边界包含 {len(lower_hull)} 个点")
            
            return hull_info
            
        except Exception as e:
            logger.error(f"计算凸包时出错: {e}")
            return None
    
    def fit_boundary_functions(self, hull_info: Dict) -> Dict:
        """拟合上下边界函数"""
        logger.info("拟合边界函数...")
        
        upper_points = hull_info['upper_boundary']
        lower_points = hull_info['lower_boundary']
        
        # 拟合上边界（多项式拟合）：延迟->距离
        upper_poly = np.polyfit(upper_points[:, 0], upper_points[:, 1], deg=2)
        upper_func = np.poly1d(upper_poly)
        
        # 拟合下边界：延迟->距离
        lower_poly = np.polyfit(lower_points[:, 0], lower_points[:, 1], deg=2)
        lower_func = np.poly1d(lower_poly)
        
        # 计算整体的延迟-距离转换系数
        # 使用线性拟合计算平均斜率
        all_latencies = self.processed_data['ms'].values
        all_distances = self.processed_data['distance_km'].values
        
        # 线性拟合: distance = slope * latency + intercept
        linear_fit = np.polyfit(all_latencies, all_distances, 1)
        slope = linear_fit[0]  # km/ms
        
        # 转换为速度: speed = distance / time
        # slope = distance / latency，所以 speed = slope * 1000 (m/s = km/ms * 1000000)
        speed_mps = slope * 1000000  # km/ms * 1000 = m/s
        
        # 光速 c = 299,792,458 m/s
        speed_of_light = 299792458  # m/s
        
        # 计算是几分之一光速
        delta = speed_mps / speed_of_light
        
        functions = {
            'upper_poly': upper_poly,
            'lower_poly': lower_poly,
            'upper_func': upper_func,
            'lower_func': lower_func,
            'linear_slope': slope,
            'speed_mps': speed_mps,
            'delta': delta,
            'linear_fit': linear_fit
        }
        
        logger.info(f"边界函数拟合完成")
        logger.info(f"计算得到的传播速度: {speed_mps:.0f} m/s")
        logger.info(f"相当于光速的: {delta:.3f} 倍")
        
        return functions
    
    def create_visualization(self, save_path: str = None) -> None:
        """创建可视化图表"""
        logger.info("创建可视化图表...")
        
        plt.figure(figsize=(12, 8))
        
        # 绘制清理后的数据点：横轴延迟，纵轴距离
        plt.scatter(self.processed_data['ms'], self.processed_data['distance_km'], 
                   alpha=0.6, s=30, c='blue', label='Valid Data Points')
        
        # 绘制离群点
        if self.outlier_data is not None and len(self.outlier_data) > 0:
            plt.scatter(self.outlier_data['ms'], self.outlier_data['distance_km'], 
                       alpha=0.8, s=30, c='red', marker='x', label='Outliers')
        
        # 绘制凸包
        if self.convex_hull is not None:
            # 注意：hull_points现在是[latency, distance]格式
            hull_points = np.column_stack([self.processed_data['ms'], self.processed_data['distance_km']])
            hull = self.convex_hull
            
            for simplex in hull.simplices:
                plt.plot(hull_points[simplex, 0], hull_points[simplex, 1], 'k-', alpha=0.8, linewidth=2)
        
        # 绘制拟合的边界函数
        if 'boundary_functions' in self.results:
            funcs = self.results['boundary_functions']
            # x轴范围现在是延迟范围
            x_range = np.linspace(self.processed_data['ms'].min(), 
                                self.processed_data['ms'].max(), 100)
            
            # 上边界：根据延迟预测距离
            upper_y = funcs['upper_func'](x_range)
            plt.plot(x_range, upper_y, 'g-', linewidth=2, label='Upper Boundary')
            
            # 下边界：根据延迟预测距离
            lower_y = funcs['lower_func'](x_range)
            plt.plot(x_range, lower_y, 'r-', linewidth=2, label='Lower Boundary')
            
            # 线性拟合：distance = slope * latency + intercept
            linear_y = funcs['linear_fit'][0] * x_range + funcs['linear_fit'][1]
            plt.plot(x_range, linear_y, 'purple', linestyle='--', linewidth=2, 
                    label=f'Linear Fit (δ={funcs["delta"]:.3f}c)')
        
        # 更新坐标轴标签
        plt.xlabel('Latency (ms)')
        plt.ylabel('Distance (km)')
        plt.title('Latency vs Distance Analysis with Convex Hull')
        plt.legend()
        plt.grid(True, alpha=0.3)
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"图表已保存到: {save_path}")
        
        plt.show()
    
    def generate_report(self, save_path: str = None) -> str:
        """生成分析报告"""
        logger.info("生成分析报告...")
        
        report = f"""
# 凸包方法距离-延迟分析报告

## 分析概况
- 分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 数据文件: {self.data_file}
- 原始数据点: {len(self.raw_data) if self.raw_data is not None else 0}
- 有效数据点: {len(self.processed_data)}
- 离群点数量: {len(self.outlier_data) if self.outlier_data is not None else 0}

## 统计信息
### 距离统计
- 最小距离: {self.processed_data['distance_km'].min():.2f} km
- 最大距离: {self.processed_data['distance_km'].max():.2f} km
- 平均距离: {self.processed_data['distance_km'].mean():.2f} km
- 距离标准差: {self.processed_data['distance_km'].std():.2f} km

### 延迟统计
- 最小延迟: {self.processed_data['ms'].min():.2f} ms
- 最大延迟: {self.processed_data['ms'].max():.2f} ms
- 平均延迟: {self.processed_data['ms'].mean():.2f} ms
- 延迟标准差: {self.processed_data['ms'].std():.2f} ms

## 凸包分析结果
"""
        
        if 'boundary_functions' in self.results:
            funcs = self.results['boundary_functions']
            report += f"""
### 距离-延迟转换系数
- 线性拟合斜率: {funcs['linear_slope']:.6f} km/ms
- 计算得到的传播速度: {funcs['speed_mps']:.0f} m/s
- 相当于光速的倍数 (δ): {funcs['delta']:.4f}
- 即传播速度为光速的 {funcs['delta']*100:.2f}%

### 边界函数
- 上边界多项式系数: {funcs['upper_poly']}
- 下边界多项式系数: {funcs['lower_poly']}
"""
        
        report += f"""
## 方法说明
本分析使用了Octant论文中描述的凸包方法:
1. 数据预处理: 移除空值和自环
2. 地理编码: 将城市名映射到经纬度坐标
3. 距离计算: 使用大圆距离公式计算地理距离
4. 离群点检测: 使用IQR方法检测并移除离群点
5. 凸包构建: 使用scipy.spatial.ConvexHull计算凸包
6. 边界拟合: 拟合上下边界函数
7. 转换系数计算: 通过线性拟合计算距离-延迟转换系数

## 结果解释
δ (delta) 值表示网络传播速度相对于光速的比例。理论上：
- δ = 1.0: 信号以光速传播（理论最大值）
- δ = 0.67: 信号在光纤中的典型传播速度
- δ < 0.67: 存在额外的处理延迟、路由迂回等因素

本次分析得到的 δ = {self.results['boundary_functions']['delta']:.4f}，
{'符合' if self.results['boundary_functions']['delta'] <= 0.67 else '高于'} 光纤传播的理论预期。
"""
        
        if save_path:
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(report)
            logger.info(f"报告已保存到: {save_path}")
        
        return report
    
    def run_analysis(self) -> Dict:
        """运行完整的分析流程"""
        logger.info("开始凸包分析...")
        
        # 1. 加载数据
        self.load_data()
        
        # 2. 地理编码
        geocoded_data = self.geocode_cities()
        
        # 3. 计算距离
        distance_data = self.calculate_distances(geocoded_data)
        
        # 4. 检测离群点
        self.processed_data, self.outlier_data = self.detect_outliers(distance_data)
        
        # 5. 计算凸包
        hull_info = self.compute_convex_hull(self.processed_data)
        self.results['convex_hull'] = hull_info
        
        # 6. 拟合边界函数
        if hull_info:
            boundary_functions = self.fit_boundary_functions(hull_info)
            self.results['boundary_functions'] = boundary_functions
        
        # 7. 保存结果
        results_file = os.path.join(self.output_dir, 'analysis_results.json')
        self.save_results(results_file)
        
        # 8. 创建可视化
        viz_file = os.path.join(self.output_dir, 'distance_latency_analysis.png')
        self.create_visualization(viz_file)
        
        # 9. 生成报告
        report_file = os.path.join(self.output_dir, 'analysis_report.md')
        self.generate_report(report_file)
        
        logger.info("分析完成！")
        return self.results
    
    def save_results(self, filepath: str) -> None:
        """保存分析结果到JSON文件"""
        # 准备可序列化的结果
        serializable_results = {}
        
        if 'boundary_functions' in self.results:
            funcs = self.results['boundary_functions']
            serializable_results['boundary_functions'] = {
                'upper_poly': funcs['upper_poly'].tolist(),
                'lower_poly': funcs['lower_poly'].tolist(),
                'linear_slope': float(funcs['linear_slope']),
                'speed_mps': float(funcs['speed_mps']),
                'delta': float(funcs['delta']),
                'linear_fit': funcs['linear_fit'].tolist()
            }
        
        # 添加统计信息
        serializable_results['statistics'] = {
            'total_points': len(self.processed_data),
            'outlier_points': len(self.outlier_data) if self.outlier_data is not None else 0,
            'distance_stats': {
                'min': float(self.processed_data['distance_km'].min()),
                'max': float(self.processed_data['distance_km'].max()),
                'mean': float(self.processed_data['distance_km'].mean()),
                'std': float(self.processed_data['distance_km'].std())
            },
            'latency_stats': {
                'min': float(self.processed_data['ms'].min()),
                'max': float(self.processed_data['ms'].max()),
                'mean': float(self.processed_data['ms'].mean()),
                'std': float(self.processed_data['ms'].std())
            }
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(serializable_results, f, indent=2, ensure_ascii=False)
        
        logger.info(f"结果已保存到: {filepath}")

def main():
    """主函数"""
    # 配置路径
    data_file = '../../data/format/tmp_ip_cus_beiy_prob_ttl_20250704.csv'
    output_dir = '.'
    
    # 创建分析器并运行分析
    analyzer = LatencyDistanceAnalyzer(data_file, output_dir)
    results = analyzer.run_analysis()
    
    # 打印主要结果
    if 'boundary_functions' in results:
        funcs = results['boundary_functions']
        print(f"\n=== 主要结果 ===")
        print(f"传播速度: {funcs['speed_mps']:.0f} m/s")
        print(f"光速比例 (δ): {funcs['delta']:.4f}")
        print(f"相当于光速的 {funcs['delta']*100:.2f}%")

if __name__ == "__main__":
    main() 