# Functions for analysis

import random
import numpy as np

from multiprocessing.pool import Pool
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ipaddress import ip_network

from scripts.utils.file_utils import load_json

from scripts.utils.logging_manager import logger
from scripts.utils.helpers import (
    haversine,
    select_best_guess_centroid,
    is_within_cirle,
    polygon_centroid,
    circle_intersections,
    circle_preprocessing,
)
from default import (
    SPEED_OF_INTERNET,
    SPEED_OF_INTERNET,
)

from default import *

########## MILLION SCALE ##########

def get_prefix_from_ip(addr):
    """from an ip addr return /24 prefix"""
    prefix = addr.split(".")[:-1]
    prefix.append("0")
    prefix = ".".join(prefix)
    return prefix


def compute_closest_rtt_probes(
    rtts_per_dst_prefix,
    vp_coordinates_per_ip,
    vp_distance_matrix,
    is_prefix,
    n_shortest=10,
):
    """
    计算每个目的地址或前缀的最短RTT（Round Trip Time）探测点。

    本函数根据给定的目的地址或前缀，以及探测点的RTT信息，找出每个目的地址或前缀的
    最短RTT探测点，并检查这些探测点是否满足互联网速度的理论限制。

    :param rtts_per_dst_prefix: 字典，包含每个目的地址或前缀及其对应的源-最小RTT映射。
    :param vp_coordinates_per_ip: 字典，包含每个虚拟探测点（VP）的坐标信息。
    :param vp_distance_matrix: 字典，包含每个VP之间的距离矩阵。
    :param is_prefix: 布尔值，指示是否使用前缀作为目的地址。
    :param n_shortest: 整数，要返回的最短RTT探测点数量，默认为10。
    :return: 字典，包含每个目的地址或前缀及其对应的最短RTT探测点。
    """
    # 初始化用于存储每个目的地址或前缀的最短RTT探测点的字典
    vps_per_prefix = {}
    for dst, src_min_rtt in rtts_per_dst_prefix.items():
        # 如果不是前缀查询，且目的地址不在VP坐标字典中，则跳过当前迭代
        if not is_prefix:
            if dst not in vp_coordinates_per_ip:
                continue
        # 对每个目的地址或前缀的源-最小RTT映射进行排序
        sorted_probes = sorted(src_min_rtt.items(), key=lambda x: x[1][0])

        # 获取排序后的前n_shortest个最短RTT探测点
        n_shortest_probes = dict(sorted_probes[:n_shortest])
        # 初始化用于存储经过距离检查的最短RTT探测点的字典
        n_shortest_probes_checked = {}
        # 初始化最小RTT和对应探测点变量
        min_rtt_probe, min_rtt = None, 1000
        # 如果不是前缀查询，对每个探测点进行距离检查
        if not is_prefix:
            for probe, rtts in n_shortest_probes.items():
                min_rtt_probe = min(rtts)
                # 如果探测点不在目的地址的VP距离矩阵中，则跳过当前探测点
                if probe not in vp_distance_matrix[dst]:
                    continue
                # 计算理论上的最大距离
                max_theoretical_distance = (
                    SPEED_OF_INTERNET * min_rtt_probe / 1000
                ) / 2
                # 如果实际距离大于理论上的最大距离，则认为距离不合理
                if vp_distance_matrix[dst][probe] > max_theoretical_distance:
                    # Impossible distance
                    continue
                # 将合理的探测点添加到经过检查的探测点字典中
                n_shortest_probes_checked[probe] = n_shortest_probes[probe]
        else:
            # 如果是前缀查询，直接使用未检查的最短RTT探测点
            n_shortest_probes_checked = n_shortest_probes

        # 将每个目的地址或前缀的最短RTT探测点添加到最终结果字典中
        vps_per_prefix[dst] = n_shortest_probes_checked

    # 返回包含每个目的地址或前缀的最短RTT探测点的字典
    return vps_per_prefix




def compute_geolocation_features_per_ip_impl(
    dst,
    rtt_per_src,
    vps_per_target,
    vp_coordinates_per_ip,
    vp_distance_matrix_dst,
    threshold_distances,
    distance_operator,
    max_vps,
    is_use_prefix,
):
    features = {}
    if is_use_prefix:
        dst_prefix = get_prefix_from_ip(dst)
        if dst_prefix not in vps_per_target:
            logger.info(
                f"Error, prefix {dst_prefix} not in measurements for VP selection algorithm"
            )
            return features
    else:
        if dst not in vps_per_target:
            logger.info(
                f"Error, prefix {dst} not in measurements for VP selection algorithm"
            )
            return features
    # Compute error with different configurations
    errors = []

    for threshold_distance in threshold_distances:
        if is_use_prefix:
            vp_per_target_allowed = vps_per_target[dst_prefix]
        else:
            vp_per_target_allowed = vps_per_target[dst]

        if distance_operator == ">":
            vp_coordinates_per_ip_filter = {
                vp: vp_coordinates_per_ip[vp]
                for vp in vp_coordinates_per_ip
                if(
                    vp in vp_distance_matrix_dst and 
                    vp_distance_matrix_dst[vp] > threshold_distance
                    and vp in vp_per_target_allowed
                )
                or vp == dst
            }

        elif distance_operator == "<=":
            vp_coordinates_per_ip_filter = {
                vp: vp_coordinates_per_ip[vp]
                for vp in vp_coordinates_per_ip
                if (
                    vp in vp_distance_matrix_dst and 
                    vp_distance_matrix_dst[vp] <= threshold_distance
                    and vp in vp_per_target_allowed
                )
                or vp == dst
            }
        else:
            raise Exception("Not a good operator. Please > or <= ")

        if len(vp_coordinates_per_ip_filter) > max_vps:
            vp_coordinates_per_ip_filter_no_dst = dict(vp_coordinates_per_ip_filter)
            del vp_coordinates_per_ip_filter_no_dst[dst]
            vp_coordinates_per_ip_filter_sample = dict(
                random.sample(
                    list(vp_coordinates_per_ip_filter_no_dst.items()), max_vps
                )
            )
            vp_coordinates_per_ip_filter_sample[dst] = vp_coordinates_per_ip_filter[dst]
        else:
            vp_coordinates_per_ip_filter_sample = vp_coordinates_per_ip_filter # 取出所有能用的VP(经过过滤，挑选(>0/40/100km),等))
        # 传入，目的ip，ip周围的vp:经纬度，ip周围vp的rtt
        error, circles = compute_error(
            dst, vp_coordinates_per_ip_filter_sample, rtt_per_src
        )
        errors.append((error, circles))
        features.setdefault(threshold_distance, []).append((dst, error, len(circles)))
    return features


def compute_geolocation_features_per_ip(
    rtt_per_srcs_dst,
    vp_coordinates_per_ip,
    threshold_distances,
    vps_per_target,
    distance_operator,
    max_vps,
    is_use_prefix,
    vp_distance_matrix,
    is_multiprocess=False,
):
    """
    Compute some features to get some scatter plots in functions of the accuracy
    Features are:
    Topological distance from the closest VP
    Geographical distance from the closest VP
    """
    features = {}
    args = []
    # 遍历 rtt_per_srcs_dst 中的每个目标 IP 地址及其对应的 RTT 数据，
    # 检查目标 IP 是否在 vp_coordinates_per_ip 中，如果不在则跳过。
    for dst, rtt_per_src in sorted(rtt_per_srcs_dst.items()):
        if dst not in vp_coordinates_per_ip:
            # We do not know the geolocation of the anchor.
            continue
        args.append(
            (
                dst,
                rtt_per_src,
                vps_per_target,
                vp_coordinates_per_ip,
                vp_distance_matrix[dst],
                threshold_distances,
                distance_operator,
                max_vps,
                is_use_prefix,
            )
        )
    if is_multiprocess:
        with Pool(24) as p:
            features_all_process = p.starmap(
                compute_geolocation_features_per_ip_impl, args[:]
            )
            for features_process in features_all_process:
                for threshold, dst_error_distances in features_process.items():
                    features.setdefault(threshold, []).extend(dst_error_distances)
    else:
        for arg in args:
            (
                dst,
                rtt_per_src,
                vps_per_target,
                vp_coordinates_per_ip,
                vp_distance_matrix_dst,
                threshold_distances,
                distance_operator,
                max_vps,
                is_use_prefix,
            ) = arg

            features_process = compute_geolocation_features_per_ip_impl(
                dst,
                rtt_per_src,
                vps_per_target,
                vp_coordinates_per_ip,
                vp_distance_matrix_dst,
                threshold_distances,
                distance_operator,
                max_vps,
                is_use_prefix,
            )
            for threshold, dst_error_distances in features_process.items():
                features.setdefault(threshold, []).extend(dst_error_distances)
    return features


def compute_accuracy_vs_number_of_vps_impl(
    rtt_per_srcs_dst,
    vp_distance_matrix,
    available_vps,
    random_n_vp,
    vp_coordinates_per_ip,
):
    random_vps = random.sample(available_vps, random_n_vp)
    vps_per_target = {x: list(set(random_vps)) for x in rtt_per_srcs_dst}
    features = compute_geolocation_features_per_ip(
        rtt_per_srcs_dst,
        vp_coordinates_per_ip,
        [0],
        vps_per_target=vps_per_target,
        distance_operator=">",
        max_vps=100000,
        is_use_prefix=False,
        vp_distance_matrix=vp_distance_matrix,
        is_multiprocess=True,
    )

    features = features[0]
    median_error = np.median([x[1] for x in features if x[1] is not None])
    return median_error


def compute_accuracy_vs_number_of_vps(
    available_vps,
    rtt_per_srcs_dst,
    vp_coordinates_per_ip,
    vp_distance_matrix,
    subset_sizes,
):
    random.seed(42)

    accuracy_vs_n_vps = {}
    for random_n_vp in subset_sizes:
        logger.info(f"Starting computing for random VPs {random_n_vp}")
        median_error_cdf = []
        for trial in range(0, 100):
            median_error = compute_accuracy_vs_number_of_vps_impl(
                rtt_per_srcs_dst,
                vp_distance_matrix,
                available_vps,
                random_n_vp,
                vp_coordinates_per_ip,
            )
            median_error_cdf.append(median_error)
        accuracy_vs_n_vps[random_n_vp] = median_error_cdf
    return accuracy_vs_n_vps



def compute_rtts_per_dst_src_with_csv(csv_path, filter=None, threshold=None):
    import csv
    """
    csv结构：
    src,dst,prb_id,min_rtt
    100.33.80.250,107.172.196.228,0,17.2
    从csv文件中获取每对源（src）和目的（dst）节点的最小往返时间（RTT），
    并且返回一个字典结构，其中包含了从每个目的节点到各个源节点的最小RTT值。
    """
    rtt_per_srcs_dst = {}

    with open(csv_path, mode='r', newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            src = row['src']
            dst = row['dst']
            min_rtt = float(row['min_rtt'])

            # 应用过滤条件和阈值
            if filter and not filter(src, dst):
                continue
            if threshold and min_rtt > threshold:
                continue

            rtt_per_srcs_dst.setdefault(dst, {})[src] = min_rtt

    return rtt_per_srcs_dst



def compute_geo_info(probes, serialized_file):
    """ 
    计算与探针相关的地理信息，包括国家、ASN、坐标等。
    
    参数:
        probes: 包含探针信息的列表。
        serialized_file: 存储距离矩阵的文件路径。
    
    返回:
        包含各类地理信息的元组。
    """
    country_per_vp_ip = {}
    asn_per_vp_ip = {}
    vp_coordinates_per_ip = {}
    ip_per_coordinates = {}
    anchors_per_ip_address = {}

    anchors = set()
    countries_anchors = set()
    countries_probes = set()
    ases_anchors = set()
    ases_probes = set()
    for probe in probes:
        try:
            if (
                "address_v4" in probe
                and "geometry" in probe
                and "coordinates" in probe["geometry"]
            ):
                ip_v4_address = probe["address_v4"]
                if ip_v4_address is None:
                    continue
                anchors_per_ip_address[ip_v4_address] = probe
                # JSON文件中坐标格式是[lat, lon]，转换为(lon, lat)
                lat, lon = probe["geometry"]["coordinates"]
                country = probe["country_code"]
                country_per_vp_ip[ip_v4_address] = country
                asn_v4 = probe["asn_v4"]
                asn_per_vp_ip[ip_v4_address] = asn_v4
                vp_coordinates_per_ip[ip_v4_address] = lon, lat
                ip_per_coordinates[lon, lat] = ip_v4_address

                ases_probes.add(asn_v4)
                countries_probes.add(country)

                if "is_anchor" in probe and probe["is_anchor"]:
                    anchors.add(ip_v4_address)
                    ases_anchors.add(asn_v4)
                    countries_anchors.add(country)

        except TypeError as e:
            logger.error(f"Probe: {probe} \n does not have coordinates")

    vp_distance_matrix = load_json(serialized_file)

    return (
        vp_coordinates_per_ip,
        ip_per_coordinates,
        country_per_vp_ip,
        asn_per_vp_ip,
        vp_distance_matrix,
        anchors_per_ip_address,
    )

def compute_error(dst, vp_coordinates_per_ip, rtt_per_src):
    error = None
    circles = []
    guessed_geolocation_circles = select_best_guess_centroid(
        dst, vp_coordinates_per_ip, rtt_per_src
    )
    if guessed_geolocation_circles is not None:
        guessed_geolocation, circles = guessed_geolocation_circles
        real_geolocation = vp_coordinates_per_ip[dst]
        error = haversine(guessed_geolocation, real_geolocation)
    return error, circles


def compute_guessed_and_real_loc(dst, vp_coordinates_per_ip, rtt_per_src, sort_circles, ncr_delta=None):
    error = None
    circles = []
    guessed_geolocation_circles = select_best_guess_centroid(
        dst, vp_coordinates_per_ip, rtt_per_src, sort_circles=sort_circles, ncr_delta=ncr_delta
    )
    if guessed_geolocation_circles is not None:
        guessed_geolocation, circles = guessed_geolocation_circles
        real_geolocation = vp_coordinates_per_ip[dst]
        error = haversine(guessed_geolocation, real_geolocation)
    else:
        return [dst,None,None,None,None]
    return [dst, error, guessed_geolocation, real_geolocation, ncr_delta], circles


def is_point_in_triangle(A, B, C, P):
    def cross(p1, p2, p3):
        x1, y1 = p2[0] - p1[0], p2[1] - p1[1]
        x2, y2 = p3[0] - p1[0], p3[1] - p1[1]
        return x1 * y2 - x2 * y1
    b1 = cross(P, A, B) < 0.0
    b2 = cross(P, B, C) < 0.0
    b3 = cross(P, C, A) < 0.0
    return (b1 == b2) and (b2 == b3)


# 使用NCRGeo算法计算目的地位置
def compute_by_NCRGeo(dst, vp_coordinates_per_ip, rtt_per_src):
    import math
    import itertools
    from scipy.optimize import least_squares, brentq

    if len(rtt_per_src) < 3:
        return [dst, None, None, None, None], 0  # 不足三点无法定位

    def get_min_rtt(val):
        if isinstance(val, list):
            return min(val)
        return val

    # 构造所有三点组合，并计算总RTT
    vp_rtt_list = [(vp, get_min_rtt(rtt)) for vp, rtt in rtt_per_src.items()]
    combs = []
    for comb in itertools.combinations(vp_rtt_list, 3):
        (A, t1), (B, t2), (C, t3) = comb
        t1 = t1 / 2
        t2 = t2 / 2
        t3 = t3 / 2
        total_rtt = t1 + t2 + t3
        if total_rtt > 100:
            continue
        combs.append(((A, t1), (B, t2), (C, t3), total_rtt))
    combs.sort(key=lambda x: x[3])
    iter_times = 0

    for (A, t1), (B, t2), (C, t3), total_rtt in combs:
        iter_times += 1
        try:
            lon1, lat1 = vp_coordinates_per_ip[A]
            lon2, lat2 = vp_coordinates_per_ip[B]
            lon3, lat3 = vp_coordinates_per_ip[C]

            d1 = haversine((lon1, lat1), (lon2, lat2))
            d2 = haversine((lon1, lat1), (lon3, lat3))
            d3 = haversine((lon2, lat2), (lon3, lat3))

            def cos_law_angle(a, b, c):
                try:
                    val = (a**2 + b**2 - c**2) / (2 * a * b)
                    val = min(1.0, max(-1.0, val))
                    return math.acos(val)
                except Exception:
                    return 0.0

            def delta_equation(delta):
                angle_BAC = cos_law_angle(d1, d2, d3)
                alpha = cos_law_angle(d1, delta * t1, delta * t2)
                beta = cos_law_angle(delta * t1, d2, delta * t3)
                return angle_BAC - (alpha + beta)

            def find_all_positive_roots(func, x_min, x_max, num=100):
                roots = []
                xs = np.linspace(x_min, x_max, num)
                for i in range(num - 1):
                    x0, x1 = xs[i], xs[i + 1]
                    try:
                        if func(x0) * func(x1) < 0: # 区间内变号说明有根
                            root = brentq(func, x0, x1)
                            if root > 0:
                                roots.append(root)
                    except Exception:
                        continue
                return roots

            roots = find_all_positive_roots(delta_equation, 0.01, 100, num=200)
            if not roots:
                continue
            delta = min(roots)

            r1 = delta * t1
            r2 = delta * t2
            r3 = delta * t3

            def residuals(x):
                return [
                    haversine((x[0], x[1]), (lon1, lat1)) - r1,
                    haversine((x[0], x[1]), (lon2, lat2)) - r2,
                    haversine((x[0], x[1]), (lon3, lat3)) - r3,
                ]
            lon0 = (lon1 + lon2 + lon3) / 3
            lat0 = (lat1 + lat2 + lat3) / 3
            res = least_squares(residuals, x0=[lon0, lat0])
            pred_lon, pred_lat = res.x

            real_lon, real_lat = vp_coordinates_per_ip.get(dst, (None, None))

            inside = is_point_in_triangle(
                (lon1, lat1), (lon2, lat2), (lon3, lat3), (pred_lon, pred_lat)
            )
            if inside:
                guessed_geolocation = (pred_lon, pred_lat)
                real_geolocation = (real_lon, real_lat)
                error = None
                if real_lon is not None and real_lat is not None:
                    error = haversine(guessed_geolocation, real_geolocation)
                return [dst, error, guessed_geolocation, real_geolocation, delta], iter_times
        except Exception:
            continue
    
    return [dst, None, None, None, None], iter_times





def compute_error_threshold_cdfs(errors_threshold, filter_dsts=None):
    error_threshold_cdfs = []
    circles_threshold_cdfs = []
    error_per_ip = {}
    for threshold, errors in sorted(errors_threshold.items(), key=lambda x: int(x[0])):
        if filter_dsts is not None and threshold in filter_dsts:
            allowed_dsts = set(x[0] for x in filter_dsts[threshold] if x[1] is not None)
        else:
            allowed_dsts = set()
        threshold_i = int(threshold)
        error_threshold_cdf = []
        circles_threshold_cdf = []
        n_no_geolocation = 0
        for dst, error, circles in errors:
            if filter_dsts is not None and dst not in allowed_dsts:
                continue
            if error is not None:
                if threshold_i == 0:
                    error_per_ip[dst] = error
                error_threshold_cdf.append(error)
                circles_threshold_cdf.append(circles)
            else:
                n_no_geolocation += 1
        error_threshold_cdfs.append(error_threshold_cdf)
        circles_threshold_cdfs.append(circles_threshold_cdf)

        logger.info(f"Threshold {threshold} no geolocation {n_no_geolocation}")

    return error_threshold_cdfs, circles_threshold_cdfs, error_per_ip


def compute_remove_wrongly_geolocated_probes(
    rtts_per_srcs_dst, vp_coordinates_per_ip, vp_distance_matrix, removed_anchors
):
    speed_of_internet_violations_per_ip = {}

    for dst, rtts_per_src in rtts_per_srcs_dst.items():
        if dst not in vp_coordinates_per_ip:
            continue

        if dst in removed_anchors or dst not in vp_distance_matrix:
            continue

        for probe, rtts in rtts_per_src.items():
            if probe in removed_anchors:
                continue
            min_rtt_probe = min(rtts)
            if probe not in vp_distance_matrix[dst]:
                continue
            max_theoretical_distance = (SPEED_OF_INTERNET * min_rtt_probe / 1000) / 2
            if vp_distance_matrix[dst][probe] > max_theoretical_distance:
                # Impossible distance
                speed_of_internet_violations_per_ip.setdefault(dst, set()).add(probe)
                speed_of_internet_violations_per_ip.setdefault(probe, set()).add(dst)

    # Greedily remove the IP address with the more SOI violations
    n_violations = sum([len(x) for x in speed_of_internet_violations_per_ip.values()])
    removed_probes = set()
    while n_violations > 0:
        logger.info(f"Violations: {n_violations}")
        # Remove the IP address with the highest number of SOI violations
        worse_ip, speed_of_internet_violations = max(
            speed_of_internet_violations_per_ip.items(), key=lambda x: len(x[1])
        )
        for (
            ip,
            speed_of_internet_violations,
        ) in speed_of_internet_violations_per_ip.items():
            speed_of_internet_violations.discard(worse_ip)
        del speed_of_internet_violations_per_ip[worse_ip]
        removed_probes.add(worse_ip)
        n_violations = sum(
            [len(x) for x in speed_of_internet_violations_per_ip.values()]
        )
    return removed_probes

# 定义一个基于轮次的算法实现
def round_based_algorithm_impl(
    dst,
    rtt_per_src,
    vp_coordinates_per_ip,
    vps_per_target_greedy,
    asn_per_vp,
    threshold,
):
    # 限制探针范围: 只选择前n个VP（测量点） 从所有探针中，选择贪婪子集内的探针。
    vp_coordinates_per_ip_allowed = {
        x: vp_coordinates_per_ip[x]
        for x in vp_coordinates_per_ip
        if x in vps_per_target_greedy
    }
    # 选择最佳估计质心位置
    guessed_geolocation_circles = select_best_guess_centroid( # 根据不同交圆数量选择计算方法
        dst, vp_coordinates_per_ip_allowed, rtt_per_src
    )
    if guessed_geolocation_circles is None:
        # 如果没有找到合适的质心，则返回目标地址和两个None值
        return dst, None, None
    # (-31.960499999999996, 115.79749999999999) , {(-31.9605, 115.7975, 83.570909, 8357.0909, 1.31173927169989)}
    guessed_geolocation, circles = guessed_geolocation_circles


    # 在区域内每个AS、城市选择一个探测器
    probes_in_intersection = {}
    for probe, probe_coordinates in vp_coordinates_per_ip.items():
        is_in_intersection = True
        for circle in circles:
            # 遍历所有探针，判断是否在质心的圆形区域内：
            lon_c, lat_c, rtt_c, d_c, r_c = circle
            if not is_within_cirle(
                (lon_c, lat_c), rtt_c, probe_coordinates, speed_threshold=2 / 3
            ):
                is_in_intersection = False
                break
        if is_in_intersection:
            probes_in_intersection[probe] = probe_coordinates

    # 现在只在交集中的probes中 选择每个AS/城市的单个probe
    selected_probes_per_asn = {}
    for probe in probes_in_intersection:
        asn = asn_per_vp[probe]
        if asn not in selected_probes_per_asn:
            selected_probes_per_asn.setdefault(asn, []).append(probe)
            continue
        else:
            is_already_found_close = False
            for selected_probe in selected_probes_per_asn[asn]:
                distance = haversine(
                    vp_coordinates_per_ip[probe], vp_coordinates_per_ip[selected_probe]
                )
                if distance < threshold:
                    is_already_found_close = True
                    break
            if not is_already_found_close:
                # 添加此探测器，因为我们还没有找到相同位置的探测器
                selected_probes_per_asn[asn].append(probe)

    # 收集选定的探测器
    selected_probes = set()
    for _, probes in selected_probes_per_asn.items():
        selected_probes.update(probes)

    # 更新第二层级的VP坐标信息
    vp_coordinates_per_ip_tier2 = {
        x: vp_coordinates_per_ip[x]
        for x in vp_coordinates_per_ip
        if x in selected_probes
    }
    vp_coordinates_per_ip_tier2[dst] = vp_coordinates_per_ip[dst]
    # 使用这个子集的探测器评估误差  (大幅提升精确度)
    error, circles = compute_error(dst, vp_coordinates_per_ip_tier2, rtt_per_src)
    dst_guess_loc,dst_real_loc = compute_guessed_and_real_loc(dst, vp_coordinates_per_ip_tier2, rtt_per_src) 
    # 返回目标地址、误差和选定的探测器数量
    return dst, error, len(selected_probes), dst_guess_loc, dst_real_loc

def round_based_algorithm(
    greedy_probes, rtt_per_srcs_dst, vp_coordinates_per_ip, asn_per_vp, n_vps, threshold
):
    """
    First is to use a subset of greedy probes, and then take 1 probe/AS in the given CBG area
    第一步使用VP子集,并在给定的CBG区域选择一个探针/AS
    :param greedy_probes:
    :return:
    """
    # 从贪婪选择的探针中选取前n_vps个VP
    vps_per_target_greedy = set(greedy_probes[:n_vps])

    args = []
    # 遍历所有源到目的地的RTT数据 ， 这个sort单纯是按照键排序，无实际作用
    for i, (dst, rtt_per_src) in enumerate(sorted(rtt_per_srcs_dst.items())):  # (dst, rtt_per_src) => ('101.53.31.6',{'103.19.166.85': [46.279334], '37.10.41.14': [41.066416], ...})
        if dst not in vp_coordinates_per_ip:
            continue
        args.append(
            (
                dst,
                rtt_per_src,
                vp_coordinates_per_ip,
                vps_per_target_greedy,
                asn_per_vp,
                threshold,
            )
        )
    with Pool(24) as p:
        results = p.starmap(round_based_algorithm_impl, args) # return dst, error, len(selected_probes)
        return results



def round_based_algorithm_with_loc(
    probes, rtt_per_srcs_dst, vp_coordinates_per_ip, asn_per_vp, threshold
):
    """
    First is to use a subset of greedy probes, and then take 1 probe/AS in the given CBG area
    第一步使用VP子集,并在给定的CBG区域选择一个探针/AS
    :param greedy_probes:
    :return:
    """
    # 从贪婪选择的探针中选取前n_vps个VP


    args = []
    # 遍历所有源到目的地的RTT数据 ， 这个sort单纯是按照键排序，无实际作用
    for i, (dst, rtt_per_src) in enumerate(sorted(rtt_per_srcs_dst.items())):  # (dst, rtt_per_src) => ('101.53.31.6',{'103.19.166.85': [46.279334], '37.10.41.14': [41.066416], ...})
        if dst not in vp_coordinates_per_ip:
            continue
        args.append(
            (
                dst,
                rtt_per_src,
                vp_coordinates_per_ip,
                probes,
                asn_per_vp,
                threshold,
            )
        )
    with Pool(24) as p:
        results = p.starmap(round_based_algorithm_impl, args) # return dst, error, len(selected_probes)
        return results

########## STREET LEVEL ##########


def every_tier_result(data):
    # data of one target if one tier is not succesful we take the previous one
    # for t1 we take cbg center, t2 the center of intercection cercles from the landmarks, t3 "closest" landmarks, t4 best landmark
    lon = 0
    lat = 0
    res = {
        "lon1": 0,
        "lat1": 0,
        "lon2": 0,
        "lat2": 0,
        "lon3": 0,
        "lat3": 0,
        "lon4": 0,
        "lat4": 0,
    }
    if not data["tier1:done"]:
        logger.info("Tier1 Failed")
        return res
    lon = data["tier1:lon"]
    lat = data["tier1:lat"]
    res["lon1"] = lon
    res["lat1"] = lat

    best_dist = 50000
    best_correct_lon = None
    best_correct_lat = None
    for f in ["tier2:landmarks", "tier3:landmarks"]:
        if f in data:
            for _, _, l_lon, l_lat in data[f]:
                dist = haversine((l_lon, l_lat), (data["RIPE:lon"], data["RIPE:lat"]))
                if dist < best_dist:
                    best_dist = dist
                    best_correct_lon = l_lon
                    best_correct_lat = l_lat

    if best_correct_lon != None and best_correct_lat != None:
        res["lon4"] = best_correct_lon
        res["lat4"] = best_correct_lat

    best_dist = 50000
    chosen_lon = None
    chosen_lat = None
    for f in ["tier2:traceroutes", "tier3:traceroutes"]:
        if f in data:
            for _, _, _, _, rtt, l_lon, l_lat, _ in data[f]:
                if rtt < 0:
                    continue
                if rtt < best_dist:
                    best_dist = rtt
                    chosen_lon = l_lon
                    chosen_lat = l_lat

    if chosen_lon != None and chosen_lat != None:
        res["lon3"] = chosen_lon
        res["lat3"] = chosen_lat

    if not data["tier2:done"]:
        res["lon2"] = res["lon1"]
        res["lat2"] = res["lat1"]
        if chosen_lon == None or chosen_lat == None:
            res["lon3"] = res["lon1"]
            res["lat3"] = res["lat1"]
        if best_correct_lon == None or best_correct_lat == None:
            res["lon4"] = res["lon1"]
            res["lat4"] = res["lat1"]
        return res

    points, circle = circle_intersections(
        data["tier2:final_circles"], data["speed_threshold"]
    )
    if len(points) > 0:
        lon, lat = polygon_centroid(points)
        res["lon2"] = lon
        res["lat2"] = lat
    else:
        res["lon2"] = res["lon1"]
        res["lat2"] = res["lat1"]

    if not data["tier3:done"]:
        if chosen_lon == None or chosen_lat == None:
            res["lon3"] = res["lon2"]
            res["lat3"] = res["lat2"]
        else:
            res["lon3"] = chosen_lon
            res["lat3"] = chosen_lat
        if best_correct_lat == None or best_correct_lon == None:
            res["lon4"] = res["lon1"]
            res["lat4"] = res["lat1"]
        return res

    if best_correct_lat != None and best_correct_lon != None:
        res["lon4"] = best_correct_lon
        res["lat4"] = best_correct_lat
    else:
        res["lon4"] = res["lon1"]
        res["lat4"] = res["lat1"]

    return res


def every_tier_result_and_errors(data):
    res = every_tier_result(data)
    res["error1"] = haversine(
        (res["lon1"], res["lat1"]), (data["RIPE:lon"], data["RIPE:lat"])
    )
    res["error2"] = haversine(
        (res["lon2"], res["lat2"]), (data["RIPE:lon"], data["RIPE:lat"])
    )
    res["error3"] = haversine(
        (res["lon3"], res["lat3"]), (data["RIPE:lon"], data["RIPE:lat"])
    )
    res["error4"] = haversine(
        (res["lon4"], res["lat4"]), (data["RIPE:lon"], data["RIPE:lat"])
    )
    return res


def local_circle_preprocessing(circles, speed_threshold=None):
    res_circles = []
    min_rtt = 5000
    for circle in circles:
        min_rtt = min(min_rtt, circle[2])

    # Remove large RTTs
    for circle in circles:
        if circle[2] < min_rtt * 5:
            res_circles.append(circle)

    return circle_preprocessing(res_circles, speed_threshold)



def is_same_bgp_prefix(ip1, ip2, prefixes):
    for i in range(8, 25):
        n1 = ip_network(ip1 + f"/{i}", strict=False).network_address
        n2 = ip_network(ip2 + f"/{i}", strict=False).network_address
        if n1 == n2:
            if f"{str(n1)}/{i}" in prefixes:
                return True
        else:
            break
    return False
