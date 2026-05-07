#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于Octant框架启发的环形区域地理定位器

该模块实现了一个新的地理定位方法，通过计算多个环形区域的交集来估计目标位置。
直接使用CBG方法生成的圆形数据，对距离进行比例放缩来创建环形约束。
支持使用凸包分析得到的多项式约束。
"""

import sys
import os
import numpy as np
import json
import math
from typing import List, Dict, Tuple, Optional, Union, Any

# 添加项目根目录到路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shapely.geometry import Point, Polygon, MultiPolygon, GeometryCollection
from shapely.ops import unary_union
from shapely.geometry import mapping
from scripts.utils.logging_manager import logger

# 导入凸包工具函数
try:
    from src.convex_hull_utils import load_convex_hull_polynomials, calculate_boundary_distances, validate_polynomial_constraints
except ImportError:
    logger.warning("无法导入凸包工具函数，多项式模式将不可用")
    load_convex_hull_polynomials = None
    calculate_boundary_distances = None
    validate_polynomial_constraints = None


class NoIntersectionError(Exception):
    """当环形区域没有交集时抛出的异常"""
    pass


class OctantRingLocalizer:
    """
    基于环形区域交集的地理定位器
    
    该类实现了受Octant框架启发的地理定位方法，通过计算多个环形区域的交集
    来估计目标位置。直接使用CBG方法生成的圆形数据，避免重复计算距离。
    
    支持两种模式：
    1. 固定比例模式：使用内外半径比例（默认）
    2. 多项式模式：使用凸包分析得到的多项式约束
    """
    
    def __init__(self, buffer_resolution: int = 32, inner_ratio: float = 2/3, outer_ratio: float = 4/3,
                 use_polynomial: bool = False, polynomial_file: str = None):
        """
        初始化OctantRingLocalizer
        
        Args:
            buffer_resolution: 用于创建圆形缓冲区的多边形边数，影响精度和性能
            inner_ratio: 内半径与CBG距离的比例，默认2/3（仅在非多项式模式下使用）
            outer_ratio: 外半径与CBG距离的比例，默认4/3（仅在非多项式模式下使用）
            use_polynomial: 是否使用凸包多项式约束，默认False
            polynomial_file: 凸包分析结果文件路径，如果为None则使用默认路径
        """
        self.buffer_resolution = buffer_resolution
        self.inner_ratio = inner_ratio
        self.outer_ratio = outer_ratio
        self.use_polynomial = use_polynomial
        self.polynomials = None
        
        # 如果启用多项式模式，加载多项式系数
        if self.use_polynomial:
            if load_convex_hull_polynomials is None:
                logger.error("凸包工具函数不可用，无法启用多项式模式")
                self.use_polynomial = False
            else:
                self.polynomials = load_convex_hull_polynomials(polynomial_file)
                if self.polynomials is None:
                    logger.error("无法加载凸包多项式，回退到固定比例模式")
                    self.use_polynomial = False
                else:
                    # 验证多项式约束
                    if not validate_polynomial_constraints(self.polynomials):
                        logger.error("多项式约束验证失败，回退到固定比例模式")
                        self.use_polynomial = False
                    else:
                        logger.info("成功启用凸包多项式约束模式")
        
        if not self.use_polynomial:
            logger.info(f"使用固定比例模式: 内半径比例={inner_ratio}, 外半径比例={outer_ratio}")
        
    def _degrees_to_meters_approx(self, lat: float) -> float:
        """
        在给定纬度处将度转换为米的近似值
        
        Args:
            lat: 纬度（度）
            
        Returns:
            float: 1度经纬度对应的米数
        """
        # 在赤道处，1度纬度 ≈ 111,320米
        # 1度经度随纬度变化：111,320 * cos(lat)
        lat_rad = np.radians(lat)
        meters_per_degree_lat = 111320.0
        meters_per_degree_lon = 111320.0 * np.cos(lat_rad)
        return (meters_per_degree_lat + meters_per_degree_lon) / 2
    
    def _meters_to_degrees_approx(self, distance_meters: float, lat: float) -> float:
        """
        在给定纬度处将米转换为度的近似值
        
        Args:
            distance_meters: 距离（米）
            lat: 纬度（度）
            
        Returns:
            float: 对应的度数
        """
        meters_per_degree = self._degrees_to_meters_approx(lat)
        return distance_meters / meters_per_degree
    
    def _create_geographic_circle(self, center_lon: float, center_lat: float, radius_meters: float, resolution: int = 64) -> Polygon:
        """
        创建地理圆形，使用与Leaflet完全一致的算法
        
        Args:
            center_lon: 圆心经度
            center_lat: 圆心纬度  
            radius_meters: 半径（米）
            resolution: 多边形边数
            
        Returns:
            Polygon: 圆形多边形
        """
        points = []
        
        # 使用WGS84椭球体参数，与Leaflet保持一致
        # Leaflet内部使用的地球半径（米）
        R = 6378137.0  # WGS84椭球长半轴
        
        # 将半径转换为角距离（弧度）
        angular_distance = radius_meters / R
        
        # 中心点坐标转弧度
        center_lat_rad = math.radians(center_lat)
        center_lon_rad = math.radians(center_lon)
        
        # 生成圆周上的点，使用与Leaflet相同的球面几何算法
        for i in range(resolution):
            # 方位角（0到2π）
            bearing = 2 * math.pi * i / resolution
            
            # 使用球面三角法计算圆周上的点（与Leaflet CRS.Earth.distance方法一致）
            # 这是标准的球面距离公式的逆运算
            lat_rad = math.asin(
                math.sin(center_lat_rad) * math.cos(angular_distance) +
                math.cos(center_lat_rad) * math.sin(angular_distance) * math.cos(bearing)
            )
            
            dlon = math.atan2(
                math.sin(bearing) * math.sin(angular_distance) * math.cos(center_lat_rad),
                math.cos(angular_distance) - math.sin(center_lat_rad) * math.sin(lat_rad)
            )
            
            lon_rad = center_lon_rad + dlon
            
            # 处理经度越界问题（-180到180度范围）
            while lon_rad > math.pi:
                lon_rad -= 2 * math.pi
            while lon_rad < -math.pi:
                lon_rad += 2 * math.pi
            
            # 转换回度
            lat = math.degrees(lat_rad)
            lon = math.degrees(lon_rad)
            
            points.append((lon, lat))
        
        # 闭合多边形
        if points and points[0] != points[-1]:
            points.append(points[0])
        
        return Polygon(points)
    
    def _calculate_ring_radii(self, cbg_data) -> Tuple[Optional[float], Optional[float]]:
        """
        根据模式计算环形的内外半径
        
        Args:
            cbg_data: CBG圆形数据
            
        Returns:
            Tuple[Optional[float], Optional[float]]: (内半径_km, 外半径_km)
        """
        try:
            if len(cbg_data) >= 7:
                # 扩展格式: [lon, lat, rtt, d_km, r_radians, inner_radius_km, outer_radius_km]
                lon, lat, rtt, d_km, r_radians, existing_inner, existing_outer = cbg_data[:7]
                
                if self.use_polynomial and self.polynomials and calculate_boundary_distances:
                    # 使用多项式模式，传递CBG距离作为fallback
                    lower_dist, upper_dist = calculate_boundary_distances(rtt, self.polynomials, d_km)
                    if lower_dist is not None and upper_dist is not None:
                        return lower_dist, upper_dist
                    else:
                        logger.warning(f"多项式计算失败，回退到固定比例模式: RTT={rtt}ms")
                        
                # 回退到固定比例模式或使用预计算的值
                if existing_inner is not None and existing_outer is not None:
                    return existing_inner, existing_outer
                else:
                    # 使用固定比例计算
                    if d_km is not None and d_km > 0:
                        return d_km * self.inner_ratio, d_km * self.outer_ratio
                        
            else:
                # 原始格式: (lon, lat, rtt, d_km, r_radians)
                lon, lat, rtt, d_km, r_radians = cbg_data
                
                if self.use_polynomial and self.polynomials and calculate_boundary_distances:
                    # 使用多项式模式，传递CBG距离作为fallback
                    lower_dist, upper_dist = calculate_boundary_distances(rtt, self.polynomials, d_km)
                    if lower_dist is not None and upper_dist is not None:
                        return lower_dist, upper_dist
                    else:
                        logger.warning(f"多项式计算失败，回退到固定比例模式: RTT={rtt}ms")
                
                # 使用固定比例模式
                if d_km is not None and d_km > 0:
                    return d_km * self.inner_ratio, d_km * self.outer_ratio
                    
        except Exception as e:
            logger.error(f"计算环形半径时出错: {e}")
            
        return None, None
    
    def _create_annulus_from_cbg_circle(self, cbg_data):
        """
        从CBG圆形数据创建环形区域（支持多项式和固定比例两种模式）
        
        Args:
            cbg_data: CBG圆形数据，支持多种格式：
                1. 原始元组格式: (lon, lat, rtt, d_km, r_radians)
                2. 扩展列表格式: [lon, lat, rtt, d_km, r_radians, inner_radius_km, outer_radius_km]
            
        Returns:
            Optional[Polygon]: 环形区域的多边形，如果创建失败返回None
        """
        try:
            # 提取基本信息
            if isinstance(cbg_data, (list, tuple)) and len(cbg_data) >= 5:
                lon, lat, rtt, d_km, r_radians = cbg_data[:5]
            else:
                logger.error(f"CBG圆形数据格式不正确: {cbg_data}")
                return None
            
            # 计算内外半径
            R_inner_km, R_outer_km = self._calculate_ring_radii(cbg_data)
            
            if R_inner_km is None or R_outer_km is None:
                logger.warning(f"无法计算环形半径: {cbg_data}")
                return None
            
            # 转换为米
            R_outer_m = R_outer_km * 1000
            R_inner_m = R_inner_km * 1000
            
            # 验证半径有效性
            if R_inner_m <= 0 or R_outer_m <= 0:
                logger.warning(f"计算的半径无效: 内半径={R_inner_km:.2f}km, 外半径={R_outer_km:.2f}km")
                return None
                
            if R_inner_m >= R_outer_m:
                logger.warning(f"内半径大于等于外半径: 内半径={R_inner_km:.2f}km, 外半径={R_outer_km:.2f}km")
                return None
            
            # 使用精确地理计算创建圆形
            outer_circle = self._create_geographic_circle(lon, lat, R_outer_m, self.buffer_resolution)
            inner_circle = self._create_geographic_circle(lon, lat, R_inner_m, self.buffer_resolution)
            
            # 检查几何体有效性
            if not outer_circle.is_valid or not inner_circle.is_valid:
                return None
            
            # 创建环形区域（外圆减去内圆）
            annulus = outer_circle.difference(inner_circle)
            
            if annulus.is_empty or not annulus.is_valid:
                return None
                
            return annulus
            
        except Exception as e:
            logger.error(f"创建环形区域时出错: {e}")
            return None
    
    def _get_largest_polygon(self, geometry) -> Optional[Polygon]:
        """
        从几何体中获取面积最大的多边形
        
        Args:
            geometry: Shapely几何体
            
        Returns:
            Optional[Polygon]: 面积最大的多边形，如果没有找到返回None
        """
        polygons = []
        
        if isinstance(geometry, Polygon):
            polygons = [geometry]
        elif isinstance(geometry, MultiPolygon):
            polygons = list(geometry.geoms)
        elif isinstance(geometry, GeometryCollection):
            for geom in geometry.geoms:
                if isinstance(geom, Polygon):
                    polygons.append(geom)
                elif isinstance(geom, MultiPolygon):
                    polygons.extend(list(geom.geoms))
        
        if not polygons:
            return None
            
        # 返回面积最大的多边形
        return max(polygons, key=lambda p: p.area)
    
    def _compute_centroid(self, geometry) -> Optional[Tuple[float, float]]:
        """
        计算几何体的质心
        
        Args:
            geometry: Shapely几何体
            
        Returns:
            Optional[Tuple[float, float]]: 质心坐标(经度, 纬度)，计算失败返回None
        """
        try:
            if geometry.is_empty:
                return None
                
            # 对于复杂几何体，找到面积最大的多边形
            if isinstance(geometry, (MultiPolygon, GeometryCollection)):
                largest_polygon = self._get_largest_polygon(geometry)
                if largest_polygon is None:
                    return None
                geometry = largest_polygon
            
            # 计算质心
            centroid = geometry.centroid
            return (centroid.x, centroid.y)
            
        except Exception as e:
            logger.error(f"计算质心时出错: {e}")
            return None
    
    def _compute_intersection_from_cbg_circles(self, cbg_circles) -> Optional[Polygon]:
        """
        从CBG圆形数据计算环形区域交集（内部方法）
        
        Args:
            cbg_circles: CBG圆形数据列表
            
        Returns:
            Optional[Polygon]: 交集几何体，计算失败返回None
            
        Raises:
            NoIntersectionError: 当环形区域没有交集时
        """
        if not cbg_circles:
            logger.warning("CBG圆形数据为空")
            return None
        
        # 创建环形区域
        all_annuli = []
        for i, cbg_circle in enumerate(cbg_circles):
            try:
                annulus = self._create_annulus_from_cbg_circle(cbg_circle)
                if annulus and annulus.is_valid and not annulus.is_empty:
                    all_annuli.append(annulus)
                else:
                    pass
                    # logger.warning(f"无法为第 {i+1} 个CBG圆形创建有效的环形区域")
            except Exception as e:
                logger.error(f"处理第 {i+1} 个CBG圆形数据时出错: {e}")
                continue
        
        if not all_annuli:
            # logger.error("没有生成任何有效的环形区域")
            return None
        
        # 计算交集
        try:
            current_intersection = all_annuli[0]
            for i in range(1, len(all_annuli)):
                current_intersection = current_intersection.intersection(all_annuli[i])
                if current_intersection.is_empty:
                    pass
                    # raise NoIntersectionError("环形区域没有公共交集")
            return current_intersection
        except Exception as e:
            if isinstance(e, NoIntersectionError):
                raise
            logger.error(f"计算交集时出错: {e}")
            return None

    def locate_target_from_cbg_circles(self, cbg_circles) -> Optional[Tuple[float, float]]:
        """
        使用CBG圆形数据进行Octant环形区域定位
        
        Args:
            cbg_circles: CBG方法生成的圆形数据列表
            
        Returns:
            Optional[Tuple[float, float]]: 目标位置坐标(经度, 纬度)，失败返回None
        """
        try:
            intersection = self._compute_intersection_from_cbg_circles(cbg_circles)
            if intersection is None or intersection.is_empty:
                return None
            return self._compute_centroid(intersection)
        except Exception as e:
            logger.error(f"定位过程出错: {e}")
            return None

    def get_intersection_area_from_cbg_circles(self, cbg_circles: List[Tuple]) -> Optional[float]:
        """
        从CBG圆形数据获取环形区域交集的面积
        
        Args:
            cbg_circles: CBG圆形数据列表
            
        Returns:
            Optional[float]: 交集面积，计算失败返回None
        """
        try:
            intersection = self._compute_intersection_from_cbg_circles(cbg_circles)
            return 0.0 if intersection is None or intersection.is_empty else intersection.area
        except Exception as e:
            logger.error(f"计算交集面积时出错: {e}")
            return None

    def get_intersection_geojson_from_cbg_circles(self, cbg_circles: List[Tuple]) -> Optional[Dict[str, Any]]:
        """
        从CBG圆形数据获取环形区域交集的GeoJSON格式数据
        
        Args:
            cbg_circles: CBG圆形数据列表
            
        Returns:
            Optional[Dict[str, Any]]: 交集的GeoJSON格式数据，计算失败返回None
        """
        try:
            intersection = self._compute_intersection_from_cbg_circles(cbg_circles)
            if intersection is None or intersection.is_empty:
                return None
            return mapping(intersection)
        except Exception as e:
            logger.error(f"计算交集GeoJSON时出错: {e}")
            return None


if __name__ == "__main__":
    # 简单测试示例
    test_cbg_circles = [
        [116.3974, 39.9093, 15.0, 10.0, 10.0/6371, 6.67, 13.33],  # 扩展格式
        [116.4000, 39.8800, 12.0, 8.0, 8.0/6371, 5.33, 10.67],
        [116.3800, 39.9200, 18.0, 12.0, 12.0/6371, 8.0, 16.0],
    ]
    
    try:
        # 测试固定比例模式
        print("=== 测试固定比例模式 ===")
        localizer_ratio = OctantRingLocalizer(buffer_resolution=16, use_polynomial=False)
        result_ratio = localizer_ratio.locate_target_from_cbg_circles(test_cbg_circles)
        if result_ratio:
            print(f"固定比例模式定位结果: 经度 {result_ratio[0]:.6f}, 纬度 {result_ratio[1]:.6f}")
        else:
            print("固定比例模式定位失败")
            
        # 测试多项式模式
        print("\n=== 测试多项式模式 ===")
        localizer_poly = OctantRingLocalizer(buffer_resolution=16, use_polynomial=True)
        result_poly = localizer_poly.locate_target_from_cbg_circles(test_cbg_circles)
        if result_poly:
            print(f"多项式模式定位结果: 经度 {result_poly[0]:.6f}, 纬度 {result_poly[1]:.6f}")
        else:
            print("多项式模式定位失败")
            
    except NoIntersectionError:
        print("环形区域没有交集")
    except Exception as e:
        print(f"定位过程出错: {e}") 