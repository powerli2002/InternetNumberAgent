import sys
import os
import requests
import json
import time
import argparse

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.utils.file_utils import load_json
from scripts.analysis.analysis import *
from default import *
from scripts.utils.logging_manager import logger
from src.octant_ring_localizer import OctantRingLocalizer, NoIntersectionError
from src.probe_select import create_probe_selector

class CBGTool:
    def __init__(self, limit=1000, use_cbg=True, use_ncr=False, use_octant=False, 
                 probe_strategy='all', delta=0.398, offline_mode=False, use_octant_polynomial=False):
        self.LIMIT = limit
        self.location_cache = {}
        self.result_ori = []  # 原始CBG（仅在use_cbg=True时保存）
        self.result_ncr = []  # 使用ncr解析延迟系数和定位
        self.result_ncr_ori = []  # 使用ncr的delta的结果 , CBG定位
        self.result_octant = []  # 使用Octant环形方法的结果
        self.use_cbg = use_cbg
        self.use_ncr = use_ncr
        self.use_octant = use_octant
        self.use_octant_polynomial = use_octant_polynomial  # 是否使用凸包多项式
        self.circle_map = {}
        self.octant_circle_map = {}  # 记录Octant环形区域数据
        self.sort_circles = 0 # 设置 延迟前三的圆进行绘图，如果为0，则画所有圆
        
        # 探针选择策略
        self.probe_strategy = probe_strategy.lower()
        self.probe_selector = create_probe_selector()
        
        # 距离延迟转换系数
        self.delta = delta
        
        # 离线模式（不进行网络请求获取地址信息）
        self.offline_mode = offline_mode
        
        # 初始化Octant定位器
        if self.use_octant:
            self.octant_localizer = OctantRingLocalizer(use_polynomial=self.use_octant_polynomial)
            if self.use_octant_polynomial:
                logger.info("已启用Octant环形区域定位方法（凸包多项式模式）")
            else:
                logger.info("已启用Octant环形区域定位方法（固定比例模式）")
        
        logger.info(f"使用探针选择策略: {self.probe_strategy}")
        if self.delta:
            logger.info(f"使用距离延迟转换系数: {self.delta}")
        if self.offline_mode:
            logger.info("启用离线模式，不获取地址信息")
    
    def format_delta_for_filename(self, delta_value):
        """
        将delta值格式化为文件名格式
        例如: 1/3 -> 1_3, 0.398 -> 0.398, 0.3333333333333333 -> 0.333
        """
        if delta_value is None:
            return "default"
        
        if isinstance(delta_value, str):
            # 处理分数形式，如 "1/3" -> "1_3"
            if '/' in delta_value:
                return delta_value.replace('/', '_')
            return delta_value
        elif isinstance(delta_value, float):
            # 处理小数形式，限制小数位数为3位
            if delta_value == int(delta_value):
                return str(int(delta_value))
            else:
                # 保留3位小数并去除末尾的0
                formatted = f"{delta_value:.3f}".rstrip('0').rstrip('.')
                return formatted
        else:
            return str(delta_value)

    def get_result_filename(self, method, file_type):
        """
        根据方法、delta和探针策略生成结果文件名
        
        Args:
            method: 定位方法 ('cbg', 'ncr', 'cbgncr', 'octant')
            file_type: 文件类型 ('loc', 'circle')
            
        Returns:
            str: 文件名
        """
        delta_str = self.format_delta_for_filename(self.delta)
        strategy_str = self.probe_strategy
        
        # 如果是Octant方法且使用多项式模式，添加标识
        if method == 'octant' and self.use_octant_polynomial:
            method = 'octant_poly'
        
        if file_type == 'loc':
            return f"user_result_loc_{method}_{delta_str}_{strategy_str}.json"
        elif file_type == 'circle':
            if method.startswith('octant'):
                return f"user_circle_map_{method}_{delta_str}_{strategy_str}.json"
            else:
                return f"user_circle_map_{method}_{delta_str}_{strategy_str}.json"
        else:
            raise ValueError(f"未知的文件类型: {file_type}")

    def initialize_cache(self):
        """
        初始化位置缓存
        """
        self.location_cache = {}
        IF_LONLAT = True  # 结果文件中目前是lat lon格式，需要转换为 lon lat
        
        # 根据当前的delta值和探针策略选择合适的缓存文件
        delta_str = self.format_delta_for_filename(self.delta)
        
        # 基本缓存文件列表
        cache_files = []
        
        # 1. 首先尝试加载与当前参数完全匹配的缓存文件
        if self.use_cbg:
            cbg_cache = DEFAULT_DIR / f"data/output/user_result_loc_cbg_{delta_str}_{self.probe_strategy}.json"
            if os.path.exists(cbg_cache):
                cache_files.append(cbg_cache)
                
        if self.use_octant:
            octant_cache = DEFAULT_DIR / f"data/output/user_result_loc_octant_{delta_str}_{self.probe_strategy}.json"
            if os.path.exists(octant_cache):
                cache_files.append(octant_cache)
        
        # 2. 如果没有找到完全匹配的缓存，尝试使用相同delta值的其他策略缓存
        if not cache_files:
            # 搜索所有可能的缓存文件
            output_dir = DEFAULT_DIR / "data/output"
            if os.path.exists(output_dir):
                for file_name in os.listdir(output_dir):
                    # 匹配相同delta值的缓存文件
                    if file_name.startswith(f"user_result_loc_cbg_{delta_str}_") or \
                       file_name.startswith(f"user_result_loc_octant_{delta_str}_"):
                        cache_files.append(output_dir / file_name)
        
        # 3. 如果仍然没有找到匹配的缓存，使用默认缓存
        if not cache_files:
            if self.use_cbg:
                # 使用CBG方法时的默认缓存文件
                default_cache_files = [
                    DEFAULT_DIR / "data/output/user_result_loc_cbg_0.398_t3.json",
                    DEFAULT_DIR / "data/output/user_result_loc_octant_0.398_t3.json",
                ]
                for file in default_cache_files:
                    if os.path.exists(file):
                        cache_files.append(file)
            else:
                # 使用NCR方法时的默认缓存文件
                default_cache_files = [
                    DEFAULT_DIR / "data/output/user_result_loc_ori.json",
                    DEFAULT_DIR / "data/output/user_result_loc_ncr_ori.json",
                    DEFAULT_DIR / "data/output/user_result_loc_ncr.json"
                ]
                for file in default_cache_files:
                    if os.path.exists(file):
                        cache_files.append(file)
        
        # 加载缓存文件
        if cache_files:
            logger.info(f"找到 {len(cache_files)} 个缓存文件")
            for cache_file in cache_files:
                try:
                    cache_data = self.load_location_cache(cache_file, IF_LONLAT)
                    if cache_data:
                        self.location_cache.update(cache_data)
                        logger.info(f"加载位置缓存: {cache_file}")
                except Exception as e:
                    logger.error(f"加载缓存文件失败: {cache_file}, 错误: {e}")
        else:
            logger.warning("未找到匹配的缓存文件，将使用空缓存")
                
        return self.location_cache
        
    def get_address_from_coordinates(self, lon, lat, offline_mode=False, timeout=10, max_retries=3):
        """
        逆地理编码，从经纬度获取地址信息
        支持重试机制和错误处理
        
        Args:
            lon: 经度
            lat: 纬度
            offline_mode: 是否使用离线模式（不进行网络请求）
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
            
        Returns:
            str: 地址信息（省份）
        """
        # 离线模式直接返回未知
        if offline_mode:
            return "Unknown"
            
        # Nominatim API需要lat, lon顺序
        url = f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={lat}&lon={lon}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Ubuntu 22.04) CBGLocTool/1.0',
            'Accept': 'application/json',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache'
        }
        
        # 重试机制
        for retry_count in range(max_retries):
            try:
                # 添加请求间隔，避免频率过高
                if retry_count > 0:
                    import time
                    wait_time = 2 ** retry_count  # 指数退避：2秒、4秒、8秒
                    logger.info(f"等待 {wait_time} 秒后重试 (重试 {retry_count}/{max_retries})")
                    time.sleep(wait_time)
                
                # 直接请求，不使用代理
                response = requests.get(url, headers=headers, timeout=timeout)
                
                # 检查响应状态
                response.raise_for_status()
                
                # 解析响应
                data = response.json()
                
                # Extract address from the response
                address = data.get('address', 'Address not found')
                if address == "Address not found":
                    return address
                    
                # 获取省份信息
                state = address.get('state', 'Unknown State')
                
                # 添加短暂延迟，避免请求过于频繁
                if retry_count == 0:  # 仅在成功的首次请求后添加延迟
                    import time
                    time.sleep(1)  # 1秒延迟
                    
                return state

            except requests.exceptions.ConnectionError as e:
                logger.warning(f"连接错误 (重试 {retry_count + 1}/{max_retries}): {e}")
                if retry_count == max_retries - 1:
                    logger.error(f"连接失败，已达到最大重试次数")
                    logger.error(f"URL: {url}")
                    return "Connection Failed"
                    
            except requests.exceptions.Timeout as e:
                logger.warning(f"请求超时 (重试 {retry_count + 1}/{max_retries}): {e}")
                if retry_count == max_retries - 1:
                    logger.error(f"请求超时，已达到最大重试次数")
                    logger.error(f"URL: {url}")
                    return "Timeout"
                    
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:  # Too Many Requests
                    logger.warning(f"请求频率过高 (重试 {retry_count + 1}/{max_retries}): {e}")
                    if retry_count < max_retries - 1:
                        import time
                        time.sleep(10)  # 被限制时等待更长时间
                    else:
                        logger.error(f"请求被限制，已达到最大重试次数")
                        return "Rate Limited"
                else:
                    logger.warning(f"HTTP错误 (重试 {retry_count + 1}/{max_retries}): {e}")
                    if retry_count == max_retries - 1:
                        logger.error(f"HTTP错误，已达到最大重试次数")
                        logger.error(f"URL: {url}")
                        return "HTTP Error"
                        
            except requests.exceptions.RequestException as e:
                logger.warning(f"请求异常 (重试 {retry_count + 1}/{max_retries}): {e}")
                if retry_count == max_retries - 1:
                    logger.error(f"请求异常，已达到最大重试次数")
                    logger.error(f"URL: {url}")
                    return "Request Failed"
                    
            except json.JSONDecodeError as e:
                logger.warning(f"JSON解析错误 (重试 {retry_count + 1}/{max_retries}): {e}")
                if retry_count == max_retries - 1:
                    logger.error(f"JSON解析错误，已达到最大重试次数")
                    logger.error(f"URL: {url}")
                    return "JSON Parse Error"
                    
            except KeyError as e:
                logger.warning(f"地址数据格式错误 (重试 {retry_count + 1}/{max_retries}): {e}")
                if retry_count == max_retries - 1:
                    logger.error(f"地址数据格式错误，已达到最大重试次数")
                    logger.error(f"URL: {url}")
                    logger.error(f"响应数据: {data if 'data' in locals() else 'N/A'}")
                    return "Address Format Error"
                    
            except Exception as e:
                logger.warning(f"未知错误 (重试 {retry_count + 1}/{max_retries}): {e}")
                if retry_count == max_retries - 1:
                    logger.error(f"获取地址信息出错: {e}")
                    logger.error(f"URL: {url}")
                    return "Unknown Error"
        
        # 如果所有重试都失败，返回None
        return None

    def add_result_by_method(self, result, result_tmp, location_cache, probe_selection_status=None):
        """
        更新结果列表，添加预测和真实的省份信息。
        
        :param result: 结果列表。
        :param result_tmp: 当前迭代的临时结果。
        :param location_cache: 地理位置缓存字典。
        :param probe_selection_status: 探针选择状态 ("success" 或 "fail")，仅用于T3策略
        :return: 更新后的结果列表。
        """
        result_tmp1 = result_tmp.copy()
        dst_guess_loc, dst_real_loc = result_tmp[2], result_tmp[3]
        
        
        dst_guess_province = "null"
        dst_real_province = "null"

        # 查询预测位置的省份信息
        if dst_guess_loc is not None:
            loc_key = dst_guess_loc
            if loc_key in location_cache:
                dst_guess_province = location_cache[loc_key]
            elif not self.offline_mode:
                dst_guess_province = self.get_address_from_coordinates(dst_guess_loc[0], dst_guess_loc[1], offline_mode=self.offline_mode)
                location_cache[loc_key] = dst_guess_province

        # 查询真实位置的省份信息
        if dst_real_loc is not None:
            loc_key = dst_real_loc
            if loc_key in location_cache:
                dst_real_province = location_cache[loc_key]
            elif not self.offline_mode:
                dst_real_province = self.get_address_from_coordinates(dst_real_loc[0], dst_real_loc[1], offline_mode=self.offline_mode)
                location_cache[loc_key] = dst_real_province

        
        if isinstance(result_tmp, tuple):
            logger.info(f"结果临时数据: {result_tmp}")
        else:
            result_tmp1.append(dst_guess_province)
            result_tmp1.append(dst_real_province)
            
            # 如果是T3策略，添加探针选择状态
            if probe_selection_status is not None and self.probe_strategy == 't3':
                result_tmp1.append(probe_selection_status)

        result.append(result_tmp1)
        return result

    def load_location_cache(self, json_file_path, IF_LONLAT):
        """
        从指定的 JSON 文件加载经纬度-城市缓存。

        :param json_file_path: JSON 文件路径。
        :param IF_LONLAT: 如果为True，表示文件中已经是lon,lat格式；如果为False，需要转换
        :return: 经纬度-城市的缓存字典。
        """
        location_cache = {}
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not data or not isinstance(data, list):
                    logger.warning(f"缓存文件格式不正确: {json_file_path}")
                    return location_cache
                    
                for entry in data:
                    try:
                        # 确保entry是列表且至少有4个元素
                        if not isinstance(entry, list) or len(entry) < 4:
                            continue
                            
                        # 确保坐标数据存在
                        if entry[2] is None or entry[3] is None:
                            continue
                            
                        # 确保坐标是可迭代的
                        if not hasattr(entry[2], '__iter__') or not hasattr(entry[3], '__iter__'):
                            continue
                            
                        # 确保坐标有两个元素
                        if len(entry[2]) != 2 or len(entry[3]) != 2:
                            continue
                            
                        if not IF_LONLAT:
                            # 转换为lon,lat格式
                            entry[2] = (entry[2][1], entry[2][0])
                            entry[3] = (entry[3][1], entry[3][0])
                            
                        # 确保坐标是数值类型
                        if not all(isinstance(x, (int, float)) for x in entry[2]) or not all(isinstance(x, (int, float)) for x in entry[3]):
                            continue
                            
                        guessed_coords = tuple(entry[2])
                        real_coords = tuple(entry[3])
                        
                        # 确保城市信息存在
                        if len(entry) >= 6:  # 至少包含6个元素才有城市信息
                            guessed_city = entry[-2] if entry[-2] is not None else "null"
                            real_city = entry[-1] if entry[-1] is not None else "null"
                            
                            location_cache[guessed_coords] = guessed_city
                            location_cache[real_coords] = real_city
                    except Exception as e:
                        logger.error(f"加载位置缓存出错: {e}")
                        continue
        except FileNotFoundError:
            logger.warning(f"缓存文件未找到: {json_file_path}")
        except json.JSONDecodeError:
            logger.error(f"JSON解析错误: {json_file_path}")
        except Exception as e:
            logger.error(f"加载缓存文件时发生未知错误: {e}")
            
        return location_cache
        
    def dump_json(self, data, file_path):
        """
        将数据保存为JSON文件
        """
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            
    def rtt_to_distance_km(self, rtt_ms, speed_factor=1/3, light_speed_km_ms=300):
        """
        将RTT（往返时间）转换为距离估计（公里）
        
        Args:
            rtt_ms: RTT时间（毫秒）
            speed_factor: 互联网传输速度系数，默认1/3光速
            light_speed_km_ms: 光速（公里/毫秒），默认300
            
        Returns:
            float: 估计距离（公里）
        """
        return rtt_ms * speed_factor * light_speed_km_ms / 2
    
    def convert_cbg_circles_to_octant_format(self, cbg_circles):
        """
        将CBG生成的圆形数据转换为Octant需要的格式
        
        Args:
            cbg_circles: CBG生成的圆形数据列表，每个元素为 (lon, lat, rtt, d, r)
            
        Returns:
            List[List]: 适用于OctantRingLocalizer的环形区域数据列表
            格式: [
                [经度, 纬度, RTT, 距离_公里, 半径_弧度, 内半径_公里, 外半径_公里],
                ...
            ]
        """
        octant_rings = []
        
        # Octant环形比例
        inner_ratio = 2/3
        outer_ratio = 4/3
        
        for circle in cbg_circles:
            try:
                lon, lat, rtt, d, r = circle
                
                # 如果d为None，使用RTT计算距离
                if d is None:
                    d_km = self.rtt_to_distance_km(rtt)
                else:
                    d_km = d
                
                # 确保所有数值都有效
                if d_km is not None and d_km > 0:
                    # 计算内外半径
                    inner_radius_km = d_km * inner_ratio
                    outer_radius_km = d_km * outer_ratio
                    
                    # 保持与原始circle_map相同的格式，只是多加两列
                    octant_rings.append([
                        lon,                    # 经度
                        lat,                    # 纬度
                        rtt,                    # RTT
                        d_km,                   # 距离_公里
                        r,                      # 半径_弧度
                        inner_radius_km,        # 内半径_公里
                        outer_radius_km         # 外半径_公里
                    ])
                    
            except (ValueError, TypeError) as e:
                logger.warning(f"转换CBG圆形数据时出错: {e}")
                continue
                
        return octant_rings
    
    
        
    def run(self):
        """
        运行CBG定位工具
        """
        # 初始化位置缓存
        logger.info("初始化位置缓存...")
        self.initialize_cache()
        
        # 设置数据集文件
        PROBES_AND_ANCHORS_FILE = USER_PROBES_AND_ANCHORS_FILE
        
        # 加载所有探针
        logger.info("加载所有探针...")
        all_probes = load_json(PROBES_AND_ANCHORS_FILE)
        
        # 准备VP信息
        logger.info("准备VP信息...")
        asn_per_vp_ip = {}
        vp_coordinates_per_ip = {}
        for probe in all_probes:
            if (
                "address_v4" in probe
                and "geometry" in probe
                and "coordinates" in probe["geometry"]
            ):
                ip_v4_address = probe["address_v4"]
                if ip_v4_address is None:
                    continue
                # JSON文件中坐标格式是[lat, lon]，需要转换为(lon, lat)
                lat, lon = probe["geometry"]["coordinates"]
                asn_v4 = probe["asn_v4"]
                asn_per_vp_ip[ip_v4_address] = asn_v4
                vp_coordinates_per_ip[ip_v4_address] = lon, lat
        
        # 获取每对源（src）和目的（dst）节点的最小往返时间（RTT）
        logger.info("获取每对源和目的节点的最小往返时间...")
        rtt_per_srcs_dst = compute_rtts_per_dst_src_with_csv(
            PROBES_TO_ANCHORS_PING_TABLE, filter, threshold=100
        )

        
        # 加载探针和锚点
        logger.info("加载探针和锚点...")

        # 初始化结果列表
        self.result_ori = []  # 原始CBG
        self.result_ncr = []  # 使用ncr解析延迟系数和定位
        self.result_ncr_ori = []  # 使用ncr的delta的结果 , CBG定位
        
        # 处理每个目标
        logger.info("开始处理每个目标...")
        processed_count = 0
        for i, (dst, rtt_per_src) in enumerate(sorted(rtt_per_srcs_dst.items())):
            # 检查是否达到处理限制
            if processed_count >= self.LIMIT:
                logger.info(f"已达到处理限制 {self.LIMIT}，停止处理")
                break
                
            if i % 25 == 0:
                logger.info(f"正在处理第 {i} 个目标...")
            
            # 获取目标真实位置（用于d3和t3策略）
            target_real_location = vp_coordinates_per_ip.get(dst, None)
            
            # 应用探针选择策略
            selected_rtt_per_src, probe_selection_status = self.probe_selector.select_probes(
                self.probe_strategy, dst, vp_coordinates_per_ip, rtt_per_src, target_real_location, self.delta
            )
            
            # CBG方法总是运行（其他方法需要这些圆形数据）
            result_tmp, circles = compute_guessed_and_real_loc(dst, vp_coordinates_per_ip, selected_rtt_per_src, self.sort_circles, self.delta)
            
            # 如果启用NCR方法，也进行NCR计算
            if self.use_ncr:
                # 使用NCR方法计算
                result_ncr_tmp, iter_times = compute_by_NCRGeo(dst, vp_coordinates_per_ip, selected_rtt_per_src)
                ncr_delta = result_ncr_tmp[4] / 300 # 调整delta，需要*2吗？
            
                # 使用NCR的delta结果进行CBG定位
                if ncr_delta and iter_times > 0 and iter_times < 3:
                    result_ncr_ori_tmp, circles_ncr = compute_guessed_and_real_loc(dst, vp_coordinates_per_ip, selected_rtt_per_src, self.sort_circles, ncr_delta)
                    self.result_ncr_ori = self.add_result_by_method(self.result_ncr_ori, result_ncr_ori_tmp, self.location_cache, probe_selection_status)
                    # 如果NCR结果更好，可以选择使用NCR的circles（这里保持原始CBG circles）
                else:
                    # 如果NCR失败，使用原始CBG结果
                    self.result_ncr_ori = self.add_result_by_method(self.result_ncr_ori, result_tmp, self.location_cache, probe_selection_status)

                self.result_ncr = self.add_result_by_method(self.result_ncr, result_ncr_tmp, self.location_cache, probe_selection_status)
            
            # 只有在启用CBG时才保存CBG结果
            if self.use_cbg:
                self.result_ori = self.add_result_by_method(self.result_ori, result_tmp, self.location_cache, probe_selection_status)
                self.circle_map[dst] = list(circles)
            
            # 如果启用了Octant环形方法，也进行Octant定位
            if self.use_octant:
                try:
                    # 直接使用CBG生成的圆形数据，转换为Octant格式
                    octant_rings = self.convert_cbg_circles_to_octant_format(circles)
                    
                    if len(octant_rings) >= 2:  # 至少需要2个圆形才能进行定位
                        # 使用Octant方法定位
                        octant_result = self.octant_localizer.locate_target_from_cbg_circles(octant_rings)
                        
                        # 计算交集几何数据
                        intersection_geojson = self.octant_localizer.get_intersection_geojson_from_cbg_circles(octant_rings)
                        
                        # 保存到octant_circle_map中，包含环形数据和交集几何数据
                        self.octant_circle_map[dst] = {
                            "rings": octant_rings,
                            "intersection_geometry": intersection_geojson
                        }
                        
                        # if intersection_geojson:
                            # logger.info(f"成功计算目标 {dst} 的交集几何数据")
                        
                        if octant_result:
                            guessed_geolocation = octant_result
                            real_geolocation = vp_coordinates_per_ip.get(dst, (None, None))
                            
                            # 计算定位误差
                            error = None
                            if real_geolocation[0] is not None and real_geolocation[1] is not None:
                                from scripts.utils.helpers import haversine
                                error = haversine(guessed_geolocation, real_geolocation)
                            
                            # 创建结果格式与CBG方法保持一致
                            result_octant_tmp = [dst, error, guessed_geolocation, real_geolocation, None]
                            self.result_octant = self.add_result_by_method(self.result_octant, result_octant_tmp, self.location_cache, probe_selection_status)
                            
                            logger.debug(f"Octant方法成功定位目标 {dst}: {guessed_geolocation}")
                        else:
                            # 定位失败，添加空结果
                            result_octant_tmp = [dst, None, None, vp_coordinates_per_ip.get(dst, (None, None)), None]
                            self.result_octant = self.add_result_by_method(self.result_octant, result_octant_tmp, self.location_cache, probe_selection_status)
                            logger.debug(f"Octant方法无法定位目标 {dst}")
                    else:
                        # 圆形数量不足，添加空结果和空的octant_circle_map条目
                        result_octant_tmp = [dst, None, None, vp_coordinates_per_ip.get(dst, (None, None)), None]
                        self.result_octant = self.add_result_by_method(self.result_octant, result_octant_tmp, self.location_cache, probe_selection_status)
                        
                        # 仍然保存环形数据，即使没有交集
                        self.octant_circle_map[dst] = {
                            "rings": octant_rings,
                            "intersection_geometry": None
                        }
                        logger.debug(f"目标 {dst} 的CBG圆形数量不足: {len(octant_rings)}")
                        
                except NoIntersectionError:
                    # 环形区域没有交集
                    result_octant_tmp = [dst, None, None, vp_coordinates_per_ip.get(dst, (None, None)), None]
                    self.result_octant = self.add_result_by_method(self.result_octant, result_octant_tmp, self.location_cache, probe_selection_status)
                    logger.debug(f"Octant方法：目标 {dst} 的环形区域没有交集")
                    
                except Exception as e:
                    # 其他错误
                    result_octant_tmp = [dst, None, None, vp_coordinates_per_ip.get(dst, (None, None)), None]
                    self.result_octant = self.add_result_by_method(self.result_octant, result_octant_tmp, self.location_cache, probe_selection_status)
                    logger.error(f"Octant方法处理目标 {dst} 时出错: {e}")

            # 增加已处理计数
            processed_count += 1
        
        # 确保结果目录存在
        results_dir = DEFAULT_DIR / "data/output"
        results_dir.mkdir(exist_ok=True, parents=True)
        
        # 保存结果 - 使用新的命名格式
        logger.info("保存结果...")
        
        # 只有在启用CBG时才保存CBG结果
        if self.use_cbg:
            cbg_result_file = results_dir / self.get_result_filename('cbg', 'loc')
            cbg_circle_file = results_dir / self.get_result_filename('cbg', 'circle')
            
            self.dump_json(self.result_ori, cbg_result_file)
            self.dump_json(self.circle_map, cbg_circle_file)
            logger.info(f"已保存CBG方法的定位结果: {cbg_result_file}")
            logger.info(f"已保存CBG方法的圆形数据: {cbg_circle_file}")
        
        # 只有在启用NCR时才保存NCR结果
        if self.use_ncr:
            ncr_result_file = results_dir / self.get_result_filename('ncr', 'loc')
            cbgncr_result_file = results_dir / self.get_result_filename('cbgncr', 'loc')
            
            self.dump_json(self.result_ncr, ncr_result_file)
            self.dump_json(self.result_ncr_ori, cbgncr_result_file)
            logger.info(f"已保存NCR方法的定位结果: {ncr_result_file}")
            logger.info(f"已保存CBG+NCR方法的定位结果: {cbgncr_result_file}")
        
        # 保存Octant方法的结果
        if self.use_octant and self.result_octant:
            octant_result_file = results_dir / self.get_result_filename('octant', 'loc')
            octant_circle_file = results_dir / self.get_result_filename('octant', 'circle')
            
            self.dump_json(self.result_octant, octant_result_file)
            self.dump_json(self.octant_circle_map, octant_circle_file)
            logger.info(f"已保存Octant环形方法的定位结果: {octant_result_file}")
            logger.info(f"已保存Octant环形方法的环形区域数据: {octant_circle_file}")

        logger.info("CBGTool运行完成")
        return {
            "result_ori": self.result_ori,
            "result_ncr": self.result_ncr,
            "result_ncr_ori": self.result_ncr_ori,
            "result_octant": self.result_octant
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='CBG地理定位工具')
    parser.add_argument('--cbg', action='store_true', default=True,
                       help='使用CBG方法进行地理定位')
    parser.add_argument('--octant', action='store_true', default=False,
                       help='使用Octant环形区域定位方法')
    parser.add_argument('--ncr', action='store_true', default=False,
                       help='使用NCR方法')
    parser.add_argument('--limit', type=int, default=1000,
                       help='处理的目标数量限制')
    parser.add_argument('--probe-strategy', type=str, default='t3',
                       choices=['all', 'l3', 'd3', 't3'],
                       help='探针选择策略: all=所有探针, l3=延迟最短的三个探针, d3=地理距离最短的三个探针, t3=能形成三角形的最近三个探针')
    parser.add_argument('--delta', type=str, default="0.398",
                       help='距离延迟转换系数，例如: 1/3, 0.398')
    parser.add_argument('--octant-polynomial', action='store_true', default=False,
                       help='使用Octant环形区域定位方法的凸包多项式模式')
    parser.add_argument('--offline', action='store_true', default=False,
                       help='使用离线模式，不进行网络请求获取地址信息')
    
    args = parser.parse_args()
    
    # 解析delta参数
    delta_value = None
    if args.delta:
        if '/' in args.delta:
            # 处理分数形式
            num, den = args.delta.split('/')
            delta_value = float(num) / float(den)
        else:
            # 处理小数形式
            delta_value = float(args.delta)
    
    tool = CBGTool(
        limit=args.limit,
        use_cbg=args.cbg,
        use_ncr=args.ncr,
        use_octant=args.octant,
        probe_strategy=args.probe_strategy,
        delta=delta_value,
        offline_mode=args.offline,
        use_octant_polynomial=args.octant_polynomial
    )
    
    tool.run()