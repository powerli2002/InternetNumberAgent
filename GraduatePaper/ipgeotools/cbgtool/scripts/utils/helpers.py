# Mathematical functions helpful for geolocation problems

import itertools
import numpy as np

from math import asin, cos, log, radians, sin, sqrt, pi



def internet_speed(rtt, speed_threshold):
    # if speed_threshold is not None:
    #     return speed_threshold

    # if rtt >= 80:
    #     speed_threshold = 4 / 9
    # if rtt >= 5 and rtt < 80:
    #     speed_threshold = 3 / 9
    # if rtt >= 0 and rtt < 5:
    #     speed_threshold = 1 / 6


    # return speed_threshold

    return 0.398 # 最终km(1ms往返) = delta * 300  
 

def rtt_to_km(rtt, speed_threshold=None, c=300):
    if DELTA:
        return DELTA * rtt * c/ 2  
    else:
        return internet_speed(rtt, speed_threshold) * rtt * c / 2


def is_within_cirle(vp_geo, rtt, candidate_geo, speed_threshold=None):
    d = rtt_to_km(rtt, speed_threshold)
    d_vp_candidate = haversine(vp_geo, candidate_geo)
    if d < d_vp_candidate:
        return False
    else:
        return True


def geo_to_cartesian(lon, lat):
    """
    将地理坐标转换为3D笛卡尔坐标
    """
    lat *= np.pi / 180
    lon *= np.pi / 180

    x = np.cos(lon) * np.cos(lat)
    y = np.sin(lon) * np.cos(lat)
    z = np.sin(lat)

    return x, y, z


def check_circle_inclusion(c_1, c_2):
    lon_1, lat_1, rtt_1, d_1, r_1 = c_1
    lon_2, lat_2, rtt_2, d_2, r_2 = c_2
    d = haversine((lon_1, lat_1), (lon_2, lat_2))
    if d_1 > (d + d_2): # 如果c_1的半径大于c_1和c_2的距离加上c_2的半径，则c_1完全包含c_2，移除 c_1
        return c_1, c_2
    elif d_2 > (d + d_1):
        return c_2, c_1
    return None, None


def circle_preprocessing(circles, speed_threshold=None):
    circles_to_ignore = set()

    circles_with_r_info = []
    for c in circles:
        lon, lat, rtt, d, r = c
        if d is None:
            d = rtt_to_km(rtt, speed_threshold)
        if r is None:
            r = d / 6371
        circles_with_r_info.append((lon, lat, rtt, d, r))

    for i in range(len(circles_with_r_info)):
        c_1 = circles_with_r_info[i]
        if c_1 in circles_to_ignore:
            continue
        lon_1, lat_1, rtt_1, d_1, r_1 = c_1
        for j in range(i + 1, len(circles_with_r_info)):
            c_2 = circles_with_r_info[j]
            if c_2 in circles_to_ignore:
                continue
            lon_2, lat_2, rtt_2, d_2, r_2 = c_2
            remove, keep = check_circle_inclusion(
                (lon_1, lat_1, rtt_1, d_1, r_1), (lon_2, lat_2, rtt_2, d_2, r_2)
            )
            if remove:
                circles_to_ignore.add(remove)

    circles_to_keep = set(circles_with_r_info) - circles_to_ignore

    return circles_to_keep


def get_points_on_circle(lon_c, lat_c, r_c, nb_points: int = 4):
    """从一个圆上获取一组点"""
    circle_points = []
    for k in range(nb_points):
        # compute
        angle = pi * 2 * k / nb_points
        dx = r_c * 1000 * cos(angle)
        dy = r_c * 1000 * sin(angle)
        lat = lat_c + (180 / pi) * (dy / 6378137)
        lon = lon_c + (180 / pi) * (dx / 6378137) / cos(lat_c * pi / 180)

        circle_points.append((lon, lat))

    return circle_points

def circle_intersections(circles, delta=None, speed_threshold=None):
    """
    计算多个圆在球面上的交集点
    
    这个函数用于网络延迟测量的地理定位，通过计算多个测量圆的交集来确定目标位置。
    每个圆代表从一个观测点（VP）到目标的可能距离范围。
    
    参数:
        circles: 包含圆信息的列表，每个元素为 (lon, lat, rtt, d, r) 元组
        delta: 延迟-距离转换系数
        speed_threshold: 速度阈值，用于RTT到距离的转换
    
    返回值:
        tuple: (filtered_points, circles)
            - filtered_points: 所有圆交集内的点列表
            - circles: 预处理后的圆列表
    
    算法详情:
        参考链接: https://gis.stackexchange.com/questions/48937/calculating-intersection-of-two-circles
        使用球面几何学计算圆的交点，然后筛选出位于所有圆内的点
    """

    global DELTA

    if delta is not None:
        DELTA = delta
    else:
        DELTA = None

    intersect_points = []  # 存储所有交点

    # 第一步：预处理圆，移除被其他圆完全包含的圆
    circles = circle_preprocessing(circles, speed_threshold=speed_threshold)

    # 特殊情况：只有一个圆时，返回圆周上的采样点
    if len(circles) == 1:
        single_circle = list(circles)[0]
        lon, lat, rtt, d, r = single_circle
        filtered_points = get_points_on_circle(lon, lat, d)
        return filtered_points, circles

    # 第二步：计算每对圆的交点
    for c_1, c_2 in itertools.combinations(circles, 2):
        # 提取两个圆的参数
        lon_1, lat_1, rtt_1, d_1, r_1 = c_1
        lon_2, lat_2, rtt_2, d_2, r_2 = c_2

        # 将地理坐标转换为3D笛卡尔坐标
        x1 = np.array(list(geo_to_cartesian(lon_1, lat_1)))
        x2 = np.array(list(geo_to_cartesian(lon_2, lat_2)))

        # 计算两圆心向量的点积
        q = np.dot(x1, x2)

        # 计算交点所在平面的系数
        a = (np.cos(r_1) - np.cos(r_2) * q) / (1 - (q**2))
        b = (np.cos(r_2) - np.cos(r_1) * q) / (1 - (q**2))

        # 计算交点所在直线与球面的基础交点
        x0 = a * x1 + b * x2

        # 计算垂直于两圆心所在平面的法向量
        n = np.cross(x1, x2)
        
        # 检查是否存在实际交点（避免数值错误导致的负数开方）
        if (1 - np.dot(x0, x0)) / np.dot(n, n) <= 0:
            # 两圆不相交或相切，跳过
            continue

        # 计算沿法向量的偏移量
        t = np.sqrt((1 - np.dot(x0, x0)) / np.dot(n, n))

        # 计算两个交点的3D坐标
        i1 = x0 + t * n  # 第一个交点
        i2 = x0 - t * n  # 第二个交点

        # 将3D笛卡尔坐标转换回地理坐标
        # 第一个交点
        i_lon_1 = np.arctan2(i1[1], i1[0]) * (180 / np.pi)
        i_lat_1 = np.arctan(i1[2] / np.sqrt((i1[0] ** 2) + (i1[1] ** 2))) / (
            np.pi / 180
        )
        intersect_points.append((i_lon_1, i_lat_1))

        # 第二个交点
        i_lon_2 = np.arctan2(i2[1], i2[0]) * (180 / np.pi)
        i_lat_2 = np.arctan(i2[2] / np.sqrt((i2[0] ** 2) + (i2[1] ** 2))) / (
            np.pi / 180
        )
        intersect_points.append((i_lon_2, i_lat_2))

    # 第三步：筛选出位于所有圆内的交点
    filtred_points = []
    for point_geo in intersect_points:
        # 检查该点是否在所有圆内
        for lon_c, lat_c, rtt_c, d_c, r_c in circles:
            if not is_within_cirle((lon_c, lat_c), rtt_c, point_geo, speed_threshold):
                break  # 如果不在某个圆内，直接跳出
        else:
            # 如果在所有圆内，添加到结果列表
            filtred_points.append(point_geo)

    return filtred_points, circles


def polygon_centroid(points):
    """
    使用有限点集方法计算多边形质心
    (see https://en.wikipedia.org/wiki/Centroid#Of_a_finite_set_of_points)
    """
    x = 0
    y = 0
    for point in points:
        x += point[0]  # 经度
        y += point[1]  # 纬度
    return x / len(points), y / len(points)


def haversine(input_location, block_location):
    """计算地球上两个位置之间的距离"""
    in_lon, in_lat, block_lon, block_lat = map(
        np.radians, [*input_location, *block_location]
    )

    dlat = block_lat - in_lat
    dlon = block_lon - in_lon

    distances = (
        np.sin(dlat / 2.0) ** 2
        + np.cos(in_lat) * np.cos(block_lat) * np.sin(dlon / 2.0) ** 2
    )

    return 6367 * 2 * np.arcsin(np.sqrt(distances))


def distance(lon1, lon2, lat1, lat2):
    """使用Haversine公式计算距离"""
    lon1 = radians(lon1)
    lon2 = radians(lon2)
    lat1 = radians(lat1)
    lat2 = radians(lat2)

    # Haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2

    c = 2 * asin(sqrt(a))

    r = 6371

    return c * r


def get_middle_intersection(intersections):
    """在只有两个交点的情况下，返回中间线段"""
    (lon1, lat1) = intersections[0]
    (lon2, lat2) = intersections[1]

    # convert to radians
    lon1 = radians(lon1)
    lon2 = radians(lon2)
    lat1 = radians(lat1)
    lat2 = radians(lat2)

    # calculate the middle of two points
    Bx = np.cos(lat2) * np.cos(lon2 - lon1)
    By = np.cos(lat2) * np.sin(lon2 - lon1)
    latMid = np.arctan2(
        np.sin(lat1) + np.sin(lat2),
        np.sqrt((np.cos(lat1) + Bx) * (np.cos(lat1) + Bx) + By * By),
    )
    lonMid = lon1 + np.arctan2(By, np.cos(lat1) + Bx)

    # convert back to degrees
    latMid = latMid * (180 / pi)
    lonMid = lonMid * (180 / pi)

    return lonMid, latMid


def select_best_guess_centroid(target_ip, vp_coordinates_per_ip, rtt_per_vp_to_target, sort_circles, ncr_delta=None):
    """
    找到最佳猜测的位置，即离质心最近的观测点位置。

    :param target_ip: 目标的IP地址。
    :param vp_coordinates_per_ip: 观测点IP地址到其地理坐标的字典映射。
    :param rtt_per_vp_to_target: 观测点IP地址到其到目标的RTT（往返时间）的字典映射。
    :return: 包含估计质心坐标及一系列探测圆的元组。
    """
    probe_circles = {}
    closest_vp = None
    min_rtt_per_vp_ip = {}

    global IF_NCR
    global DELTA
    IF_NCR = False
    DELTA = 0
    if ncr_delta is not None:
        IF_NCR = True 
        DELTA = ncr_delta 

    for vp_ip, rtts in rtt_per_vp_to_target.items():
        if target_ip == vp_ip:
            continue
        if vp_ip not in vp_coordinates_per_ip:
            continue
        lon, lat = vp_coordinates_per_ip[vp_ip]
        if isinstance(rtts,float):
            min_rtt = rtts
        else:
            min_rtt = min(rtts)
        if min_rtt > 100:
            continue
        min_rtt_per_vp_ip[vp_ip] = min_rtt

        if isinstance(min_rtt, float):
            probe_circles[vp_ip] = (
                lon,
                lat,
                min_rtt,
                None,
                None,
            )

    # 绘制圆圈，所有的圆都
    if not probe_circles:
        return None
    circles = list(probe_circles.values())

    # 设置延迟最低的前sort_circles个圆画圆，如果为0，则画所有圆
    circles = sorted(circles, key=lambda x: x[2])
    if sort_circles == 0:
        circles = circles
    else:
        circles = circles[:sort_circles]
    
    
    intersections, circles = circle_intersections(circles, speed_threshold=2/3)
    
    if len(intersections) > 2:
        centroid = polygon_centroid(intersections)
    elif len(intersections) == 2:
        # 只有两个圆相交，质心为线段中点
        centroid = get_middle_intersection(intersections)
    else:
        # 只有一个圆，取距离最近的观测点作为质心
        closest_vp, _ = min(min_rtt_per_vp_ip.items(), key=lambda x: x[1])
        centroid = vp_coordinates_per_ip[closest_vp]

    IF_NCR = False
    return centroid, circles


def get_center_of_poly(circles, speed):
    points, circles = circle_intersections(circles, speed)
    if len(points) == 0:
        return None, None
    return polygon_centroid(points)


def get_points_in_poly(circles, rot, rad, speed, old_circles=[]):
    circles = circle_preprocessing(circles, speed_threshold=speed)
    points, circles = circle_intersections(circles, speed)
    if len(points) == 0:
        return []
    else:
        center = polygon_centroid(points)
    res = [center]
    iter_rad = 0
    points_added = True
    while points_added:
        iter_rad += rad
        points_added = False
        to_add_points = get_points_on_circle(
            center[0], center[1], iter_rad, int(360/rot))
        for point in to_add_points:
            all_in = True
            for vp in circles:
                if not is_within_cirle((vp[0], vp[1]), vp[2], point, speed):
                    all_in = False
                    break
            if all_in:
                for vp in old_circles:
                    if not is_within_cirle((vp[0], vp[1]), vp[2], point, speed):
                        all_in = False
                    break
                if all_in:
                    points_added = True
                    res.append(point)
    return res

def greedy_selection_probes_impl(probe, distance_per_probe, selected_probes):

    distances_log = [log(distance_per_probe[p]) for p in selected_probes
                     if p in distance_per_probe and distance_per_probe[p] > 0]
    total_distance = sum(distances_log)
    return probe, total_distance
    
