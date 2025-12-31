"""
本脚本实现AS的ipv4地理疆域分析

1. 读取中国区域的 AS 文件 data/as_entity_cn.csv
2. 读取pfx2as文件，并进行解析，输出去重的路由前缀与AS的对应关系。注意，前缀去重方法：
   - IPv4: 统一切分到/24前缀，超过/24的按照/24处理。然后将其存入set。
   - IPv6: 统一切分到/48前缀。
   - 中间结果可选地保存到 data/output/pfx2as_v4_processed.csv 和 data/output/pfx2as_v6_processed.csv，并在重复运行时直接读取。
3. 使用data/database中的IP离线数据库对AS名下的所有IPv4 /24前缀进行定位，并统计地址数量。
   - 统计地址和划定疆域时，输出一个最可能的地理疆域（省和市），并计算置信度（该位置占AS总地址的比例）。
   - 输出的地理疆域信息将添加到原AS文件中，并保存到 data/output/as_entity_cn_with_territory.csv。
4. 根据推断出的高置信度AS地理疆域，对IPv6地址进行地理定位，结果保存到 data/output/geolocated_ipv6_prefixes.csv。

优化改进：
- 集成高效的pfx2as解析器，支持分段跳过功能
- 使用pandas矢量化操作优化AS疆域汇聚和IPv6前缀定位性能
"""
import pandas as pd
import ipaddress
import sys
import os
import argparse
import pytricia
from collections import defaultdict, Counter
from typing import Dict, Set, List, Optional
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# 高效的pfx2as解析器，支持分段跳过功能
class Pfx2AsParse:
    """高效的pfx2as文件解析器，支持分段跳过功能"""

    def __init__(self):
        self.BASE_DATA_DIR = 'data'
        self.OUTPUT_DIR = os.path.join(self.BASE_DATA_DIR, 'output')
        self.PFX2AS_V4_RAW_FILE = os.path.join(self.BASE_DATA_DIR, 'pfx2as', 'routeviews-rv2-20250728-1200.pfx2as')
        self.PFX2AS_V6_RAW_FILE = os.path.join(self.BASE_DATA_DIR, 'pfx2as', 'routeviews-rv6-20250728-1200.pfx2as')
        self.PFX2AS_V4_PROCESSED_FILE = os.path.join(self.OUTPUT_DIR, 'pfx2as_v4_processed.csv')
        self.PFX2AS_V6_PROCESSED_FILE = os.path.join(self.OUTPUT_DIR, 'pfx2as_v6_processed.csv')

    def parse_pfx2as_file(self, pfx2as_raw_file: str, output_csv: str, ip_version: int, force_rerun: bool = False):
        """
        解析pfx2as文件，支持分段跳过功能

        Args:
            pfx2as_raw_file: 原始pfx2as文件路径
            output_csv: 输出CSV文件路径
            ip_version: IP版本 (4 or 6)
            force_rerun: 是否强制重新运行

        Returns:
            pd.DataFrame: 包含asn和prefix两列的DataFrame
        """
        if not force_rerun and os.path.exists(output_csv):
            print(f"Loading processed pfx2as data from cache: {output_csv}")
            return pd.read_csv(output_csv)

        print(f"Parsing raw pfx2as file: {pfx2as_raw_file}")
        os.makedirs(os.path.dirname(output_csv), exist_ok=True)

        # 第一步：解析所有前缀，收集到全局列表
        ip_class = ipaddress.IPv4Network if ip_version == 4 else ipaddress.IPv6Network

        try:
            # 使用pandas读取pfx2as文件，分隔符为\t，无表头
            df = pd.read_csv(
                pfx2as_raw_file,
                sep='\t',
                names=['prefix_str', 'prefix_len_str', 'asn_str'],
                dtype={'prefix_str': str, 'prefix_len_str': str, 'asn_str': str},
                comment='#',
                engine='python'
            ).dropna()
        except FileNotFoundError:
            raise Exception(f"pfx2as file not found: {pfx2as_raw_file}")

        df['prefix_len_str'] = df['prefix_len_str'].astype(int)
        # asn_str可能包含多个ASN，用逗号分隔，先保持为字符串

        def extract_records(row):
            result = []
            asns = [int(asn) for asn in row['asn_str'].replace('_', ',').split(',') if asn.strip()]
            if not asns:
                return result
            try:
                network = ip_class(f"{row['prefix_str']}/{row['prefix_len_str']}", strict=False)
                prefix = str(network)
            except (ValueError, ipaddress.AddressValueError, ipaddress.NetmaskValueError):
                return result
            for asn in asns:
                result.append((asn, prefix))
            return result

        # 展平成 (asn, prefix) 的list - 使用向量化操作优化
        print(f"Processing {len(df):,} pfx2as records...")
        flat_records = []
        for _, row in tqdm(df.iterrows(), total=len(df), desc=f"Parsing IPv{ip_version} pfx2as"):
            flat_records.extend(extract_records(row))

        # 收集AS号到前缀列表的映射 - 使用更高效的数据结构
        as_prefixes = defaultdict(list)
        for asn, prefix in flat_records:
            as_prefixes[asn].append(prefix)

        # 将字典转换为DataFrame返回
        df_result = pd.DataFrame([
            {'asn': asn, 'prefix': prefix}
            for asn, prefixes in as_prefixes.items()
            for prefix in prefixes
        ])

        # 保存到CSV缓存
        df_result.to_csv(output_csv, index=False)
        print(f"Saved processed pfx2as data to {output_csv}")

        return df_result

# 将脚本的父目录添加到Python路径，以便导入其他模块
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from scripts.database.BlueDatabase import BlueDatabase
from scripts.database.IPIPDatabase import IPIPDatabase
from scripts.database.AiwenDatabase import AiwenDatabase
from tqdm import tqdm

class ASTerritoryAnalyzer:
    # 定义文件路径常量
    BASE_DATA_DIR = 'data'
    OUTPUT_DIR = os.path.join(BASE_DATA_DIR, 'output')
    DATABASE_DIR = os.path.join(BASE_DATA_DIR, 'database')
    
    AS_ENTITY_CN_FILE = os.path.join(BASE_DATA_DIR, 'as_whois_cn_parsed_qwen_with_org.csv')
    PFX2AS_V4_RAW_FILE = os.path.join(BASE_DATA_DIR, 'pfx2as', 'routeviews-rv2-20250728-1200.pfx2as')
    PFX2AS_V6_RAW_FILE = os.path.join(BASE_DATA_DIR, 'pfx2as', 'routeviews-rv6-20250728-1200.pfx2as')
    
    PFX2AS_V4_PROCESSED_FILE = os.path.join(OUTPUT_DIR, 'pfx2as_v4_processed.csv')
    PFX2AS_V6_PROCESSED_FILE = os.path.join(OUTPUT_DIR, 'pfx2as_v6_processed.csv')
    AS_TERRITORY_FILE = os.path.join(OUTPUT_DIR, 'as_whois_cn_with_territory.csv')
    GEOLOCATED_IPV6_FILE = os.path.join(OUTPUT_DIR, 'geolocated_ipv6_prefixes.csv')

    def __init__(self):
        """初始化AS疆域分析器"""
        self.as_data: Optional[pd.DataFrame] = None
        self.databases = self._init_databases()
        self.pfx2as_parser = Pfx2AsParse()
        # 确保输出目录存在
        os.makedirs(self.OUTPUT_DIR, exist_ok=True)

    def _init_databases(self) -> Dict:
        """初始化所有可用的地理位置数据库"""
        databases = {}
        db_configs = {
            'blue': ('blue.xdb', BlueDatabase),
            'ipip': ('ipip.datx', IPIPDatabase),
            'aiwen': ('aiwen.txt', AiwenDatabase),
        }
        for name, (filename, db_class) in db_configs.items():
            try:
                databases[name] = db_class(self.DATABASE_DIR, filename)
            except Exception as e:
                print(f"Warning: Failed to initialize {name} database: {e}")

        if not databases:
            raise Exception("No geolocation databases could be initialized. Aborting.")
        print(f"Initialized databases: {list(databases.keys())}")
        return databases

    def load_as_data(self) -> None:
        """读取中国区域的AS文件"""
        try:
            self.as_data = pd.read_csv(self.AS_ENTITY_CN_FILE)
            print(f"Loaded {len(self.as_data)} AS entities from {self.AS_ENTITY_CN_FILE}")
        except FileNotFoundError:
            raise Exception(f"AS data file not found: {self.AS_ENTITY_CN_FILE}")

    def parse_pfx2as_file(self, pfx2as_raw_file: str, output_csv: str,
                          ip_version: int, force_rerun: bool = False) -> pd.DataFrame:
        """
        解析pfx2as文件，支持分段跳过功能

        Args:
            pfx2as_raw_file: 原始pfx2as文件路径
            output_csv: 输出CSV文件路径
            ip_version: IP版本 (4 or 6)
            force_rerun: 是否强制重新运行

        Returns:
            pd.DataFrame: 包含asn和prefix两列的DataFrame
        """
        # 使用高效的pfx2as解析器
        return self.pfx2as_parser.parse_pfx2as_file(pfx2as_raw_file, output_csv, ip_version, force_rerun)

    def _global_deduplicate_prefixes(self, prefix_asn_pairs: List[tuple], ip_version: int) -> List[tuple]:
        """
        全量去重前缀，保留更大粒度的前缀，不考虑AS边界
        
        Args:
            prefix_asn_pairs: (prefix, asn) 元组列表
            ip_version: IP版本 (4 or 6)
            
        Returns:
            List[tuple]: 去重后的 (prefix, asn) 元组列表
        """
        print(f"Global deduplicating IPv{ip_version} prefixes using prefix trie...")
        
        ip_class = ipaddress.IPv4Network if ip_version == 4 else ipaddress.IPv6Network
        
        # 创建全局前缀树
        if ip_version == 4:
            trie = pytricia.PyTricia(32)  # IPv4最大前缀长度32
        else:
            trie = pytricia.PyTricia(128)  # IPv6最大前缀长度128
        
        # 将所有前缀转换为网络对象并排序
        network_data = []
        unique_prefixes = set()
        
        for prefix_str, asn in prefix_asn_pairs:
            if prefix_str not in unique_prefixes:
                try:
                    network = ip_class(prefix_str, strict=False)
                    network_data.append((network.prefixlen, str(network), asn))
                    unique_prefixes.add(str(network))
                except (ipaddress.AddressValueError, ipaddress.NetmaskValueError):
                    continue
        
        print(f"Processing {len(network_data):,} unique prefixes for global deduplication...")
        
        # IPv6特殊处理：如果前缀数量过大，先进行预筛选
        if ip_version == 6 and len(network_data) > 100000:
            print("IPv6 dataset is large, applying pre-filtering for efficiency...")
            # 按前缀长度分组，优先处理更大粒度的前缀
            network_data.sort(key=lambda x: x[0])
            # 对于IPv6，只处理前50%最大粒度的前缀以提高效率
            cutoff_index = len(network_data) // 2
            network_data = network_data[:cutoff_index]
            print(f"Pre-filtered to {len(network_data):,} prefixes for IPv6 processing")
        else:
            # 按前缀长度排序，更大粒度(更小前缀长度)优先处理
            network_data.sort(key=lambda x: x[0])
        
        # 使用前缀树进行全量去重
        deduplicated_pairs = []
        processed = 0
        
        for prefix_len, prefix_str, asn in network_data:
            processed += 1
            if processed % 50000 == 0:
                print(f"Processed {processed:,}/{len(network_data):,} prefixes...")
                
            # 检查是否已经被更大粒度的前缀覆盖
            network_addr = prefix_str.split('/')[0]
            parent = trie.get_key(network_addr)
            
            if parent is None:
                # 没有被覆盖，添加到前缀树和结果中
                trie[prefix_str] = f"{asn}_{len(deduplicated_pairs)}"  # 使用唯一标识符
                deduplicated_pairs.append((prefix_str, asn))
            # 如果已被覆盖，则跳过此前缀
        
        # 输出去重统计
        total_original = len(prefix_asn_pairs)
        total_unique_original = len(unique_prefixes)
        total_deduplicated = len(deduplicated_pairs)
        
        print(f"Global deduplication completed:")
        print(f"  Original prefix-AS pairs: {total_original:,}")
        print(f"  Unique original prefixes: {total_unique_original:,}")
        print(f"  After global deduplication: {total_deduplicated:,}")
        
        if total_unique_original > 0:
            reduction_rate = (total_unique_original - total_deduplicated) / total_unique_original * 100
            print(f"  Removed redundant prefixes: {total_unique_original - total_deduplicated:,} ({reduction_rate:.1f}%)")
        
        return deduplicated_pairs
    
    def _print_prefix_statistics_simple(self, as_prefixes: Dict[str, List[str]], ip_version: int):
        """
        打印简化的前缀统计信息
        
        Args:
            as_prefixes: AS号到前缀列表的映射
            ip_version: IP版本
        """
        standard_prefix_len = 24 if ip_version == 4 else 48
        ip_class = ipaddress.IPv4Network if ip_version == 4 else ipaddress.IPv6Network
        
        total_prefixes = sum(len(prefixes) for prefixes in as_prefixes.values())
        total_std_prefixes = 0
        total_ip_addresses = 0
        
        # 计算统计信息
        for prefixes in as_prefixes.values():
            for prefix_str in prefixes:
                try:
                    network = ip_class(prefix_str, strict=False)
                    # 计算标准前缀数量
                    if network.prefixlen <= standard_prefix_len:
                        std_count = 2 ** (standard_prefix_len - network.prefixlen)
                    else:
                        std_count = 1
                    total_std_prefixes += std_count
                    total_ip_addresses += int(network.num_addresses)
                except (ipaddress.AddressValueError, ipaddress.NetmaskValueError):
                    continue
        
        print(f"\n=== IPv{ip_version} Prefix Statistics ===")
        print(f"Total ASNs: {len(as_prefixes):,}")
        print(f"Total prefixes: {total_prefixes:,}")
        print(f"Total /{standard_prefix_len} equivalent prefixes: {total_std_prefixes:,}")
        print(f"Total IP addresses: {total_ip_addresses:,}")
        
        if total_prefixes > 0:
            avg_std_per_original = total_std_prefixes / total_prefixes
            print(f"Average /{standard_prefix_len} prefixes per original prefix: {avg_std_per_original:.2f}")
        
        # 前缀长度分布统计
        prefix_len_stats = defaultdict(int)
        for prefixes in as_prefixes.values():
            for prefix_str in prefixes:
                try:
                    if ip_version == 4:
                        network = ipaddress.IPv4Network(prefix_str, strict=False)
                    else:
                        network = ipaddress.IPv6Network(prefix_str, strict=False)
                    prefix_len_stats[network.prefixlen] += 1
                except (ipaddress.AddressValueError, ipaddress.NetmaskValueError):
                    continue
        
        print(f"\nTop 10 most common prefix lengths:")
        for prefix_len, count in sorted(prefix_len_stats.items(), key=lambda x: x[1], reverse=True)[:10]:
            percentage = count / total_prefixes * 100
            print(f"  /{prefix_len}: {count:,} prefixes ({percentage:.1f}%)")

    def _split_to_24_prefixes(self, prefix_str: str) -> Set[str]:
        """
        将IPv4前缀拆分到/24前缀
        
        Args:
            prefix_str: IPv4前缀字符串，如 "192.168.1.0/23"
            
        Returns:
            Set[str]: /24前缀集合
        """
        try:
            network = ipaddress.IPv4Network(prefix_str, strict=False)
            
            if network.prefixlen >= 24:
                # 如果前缀长度已经是/24或更长，返回网络地址的/24前缀
                network_24 = ipaddress.IPv4Network(f"{network.network_address}/24", strict=False)
                return {str(network_24)}
            else:
                # 如果前缀长度小于/24，拆分成多个/24前缀
                prefixes_24 = set()
                for subnet in network.subnets(new_prefix=24):
                    prefixes_24.add(str(subnet))
                return prefixes_24
                
        except (ipaddress.AddressValueError, ipaddress.NetmaskValueError):
            return set()

    def geolocate_as_territory(self, as_prefixes_df: pd.DataFrame,
                               threshold: float = 0.8,
                               max_workers: int = 8) -> Dict[str, Dict]:
        """
        对每个AS的所有IPv4前缀进行地理定位，并计算疆域和置信度（优化版，使用pandas矢量化操作）

        Args:
            as_prefixes_df: 包含asn和prefix两列的DataFrame

        Returns:
            Dict: AS地理统计信息
        """
        if as_prefixes_df.empty:
            return {}

        print(f"Processing {len(as_prefixes_df):,} IPv4 prefixes for geolocation...")

        # 1. 使用pandas高效处理：将所有前缀拆分到/24前缀并去重
        def split_prefix_to_24(prefix_str):
            """将IPv4前缀拆分到/24前缀（向量化版本）"""
            try:
                network = ipaddress.IPv4Network(prefix_str, strict=False)
                if network.prefixlen >= 24:
                    # 如果前缀长度已经是/24或更长，返回网络地址的/24前缀
                    network_24 = ipaddress.IPv4Network(f"{network.network_address}/24", strict=False)
                    return [str(network_24)]
                else:
                    # 如果前缀长度小于/24，拆分成多个/24前缀
                    return [str(subnet) for subnet in network.subnets(new_prefix=24)]
            except (ipaddress.AddressValueError, ipaddress.NetmaskValueError):
                return []

        # 创建AS到前缀的映射
        as_groups = as_prefixes_df.groupby('asn')

        as_geo_stats = {}

        def process_one_as(asn: int, prefixes: List[str]) -> Optional[tuple]:
            all_24_prefixes = []
            total_ip_addresses = 0

            for prefix_str in prefixes:
                try:
                    network = ipaddress.IPv4Network(prefix_str, strict=False)
                    total_ip_addresses += int(network.num_addresses)
                    all_24_prefixes.extend(split_prefix_to_24(prefix_str))
                except (ipaddress.AddressValueError, ipaddress.NetmaskValueError):
                    continue

            unique_24_prefixes = list(set(all_24_prefixes))
            total_std_prefixes = len(unique_24_prefixes)
            if total_std_prefixes == 0:
                return None

            all_locations = []
            for prefix_24_str in unique_24_prefixes:
                try:
                    network_24 = ipaddress.IPv4Network(prefix_24_str, strict=False)
                    locations = self._get_locations_from_all_dbs(str(network_24.network_address))
                    voted_location = self._get_location_with_voting(locations)
                    if voted_location:
                        all_locations.append(voted_location)
                except (ipaddress.AddressValueError, ipaddress.NetmaskValueError):
                    continue

            if not all_locations:
                return None

            result = self._calculate_territory_confidence(
                all_locations, total_ip_addresses, total_std_prefixes, threshold=threshold
            )
            return (str(asn), result)

        # 并行处理每个AS
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            total_groups = len(as_groups)
            submitted = 0
            for asn, group in as_groups:
                prefixes = group['prefix'].tolist()
                future = executor.submit(process_one_as, asn, prefixes)
                futures[future] = asn
                submitted += 1

            processed = 0
            for future in tqdm(as_completed(futures), total=submitted, desc="Geolocating AS Territories"):
                processed += 1
                try:
                    res = future.result()
                    if res is None:
                        continue
                    asn_str, data = res
                    as_geo_stats[asn_str] = data
                except Exception:
                    continue

        print(f"Successfully geolocated {len(as_geo_stats)}/{len(as_groups)} ASNs")
        return as_geo_stats

    def _get_locations_from_all_dbs(self, ip: str) -> List[Dict]:
        """从所有数据库获取给定IP的地理位置信息，使用投票机制"""
        locations = []
        for db in self.databases.values():
            try:
                loc = db.get_info(ip)
                if loc and loc.get('province') and loc.get('city') and loc['province'] not in ['NULL', '']:
                    locations.append(loc)
            except Exception:
                continue
        return locations

    def _get_location_with_voting(self, locations: List[Dict]) -> Optional[Dict]:
        """
        使用投票机制从多个数据库结果中选择最可靠的位置

        Args:
            locations: 来自不同数据库的位置信息列表

        Returns:
            Dict: 最可靠的位置信息，包含投票统计
        """
        if not locations:
            return None

        if len(locations) == 1:
            loc = locations[0].copy()
            loc['vote_count'] = 1
            loc['total_votes'] = 1
            return loc

        # 统计投票结果，按完整位置路径投票
        location_votes = defaultdict(int)
        location_details = {}

        for loc in locations:
            # 创建位置键：国家-省-市（移除县级）
            country = loc.get('country', '')
            province = loc.get('province', '')
            city = loc.get('city', '')

            location_key = f"{country}|{province}|{city}"

            location_votes[location_key] += 1
            if location_key not in location_details:
                # 仅保留必要字段
                filtered = {
                    'country': country,
                    'province': province,
                    'city': city,
                }
                location_details[location_key] = filtered

        # 找出得票最多的位置
        if not location_votes:
            return None

        top_location_key = max(location_votes.items(), key=lambda x: x[1])[0]
        top_location = location_details[top_location_key]
        vote_count = location_votes[top_location_key]
        total_votes = len(locations)

        # 添加投票统计信息
        top_location['vote_count'] = vote_count
        top_location['total_votes'] = total_votes
        top_location['confidence'] = vote_count / total_votes

        return top_location

    def _calculate_territory_confidence(self, all_locations: List[Dict],
                                       total_ip_addresses: int, total_std_prefixes: int,
                                       threshold: float = 0.8) -> Dict:
        """
        根据位置信息列表计算最可能的疆域、置信度和AS级别（移除县级，支持阈值）

        Args:
            all_locations: 所有位置信息列表（已使用投票机制）
            total_ip_addresses: 总IP地址数量
            total_std_prefixes: 总标准前缀数量
        """
        if not all_locations:
            return {}

        # 统计各级别的位置分布
        province_stats = Counter()
        city_stats = Counter()
        location_details = {}

        for loc in all_locations:
            province = loc.get('province', '')
            city = loc.get('city', '')

            if province:
                province_stats[province] += 1
            if city:
                city_stats[city] += 1

            # 保存完整的位置信息
            location_key = f"{province}|{city}"
            location_details[location_key] = loc

        total_locations = len(all_locations)

        # 确定AS级别
        as_level = self._determine_as_level(province_stats, city_stats, threshold)

        # 获取各级别的主要位置
        top_province = province_stats.most_common(1)[0][0] if province_stats else ''
        top_city = city_stats.most_common(1)[0][0] if city_stats else ''

        # 计算各级别的置信度
        province_confidence = province_stats[top_province] / total_locations if province_stats else 0
        city_confidence = city_stats[top_city] / total_locations if city_stats else 0
        
        return {
            'province_territory': top_province,
            'city_territory': top_city,
            'as_level': as_level,
            'province_confidence': province_confidence,
            'city_confidence': city_confidence,
            'total_std_prefixes': total_std_prefixes,
        }

    def _determine_as_level(self, province_stats: Counter,
                           city_stats: Counter, threshold: float) -> str:
        """
        根据位置统计信息确定AS级别（无县级）

        Args:
            province_stats: 省统计
            city_stats: 市统计
            threshold: 判定阈值（默认0.8）

        Returns:
            str: AS级别（国家级、省级、市级、县级）
        """
        province_count = len(province_stats)
        city_count = len(city_stats)
        
        # 计算各级别的top占比
        top_city, top_city_count = (city_stats.most_common(1)[0] if city_stats else ('', 0))
        top_province, top_province_count = (province_stats.most_common(1)[0] if province_stats else ('', 0))
        total = sum(city_stats.values()) if city_stats else 0
        city_ratio = (top_city_count / total) if total else 0.0
        total_prov = sum(province_stats.values()) if province_stats else 0
        province_ratio = (top_province_count / total_prov) if total_prov else 0.0

        # 判定顺序：先市后省，再国家
        if top_city and city_ratio >= threshold:
            return '市级'
        if province_ratio >= threshold:
            return '省级'
        if province_count > 1:
            return '国家级'
        # 回退：若只有单省但城市不足阈值，仍视为省级
        if province_count == 1:
            return '省级'
        return '国家级'

    def add_territory_to_as_data(self, as_geo_stats: Dict[str, Dict]) -> pd.DataFrame:
        """将地理疆域信息添加到AS数据中"""
        if self.as_data is None:
            self.load_as_data()

        df = self.as_data.copy()

        # 如果没有地理信息，则添加空列并返回
        if not as_geo_stats:
            for col in ['province_territory', 'city_territory', 'as_level',
                       'province_confidence', 'city_confidence', 'total_std_prefixes']:
                df[col] = None
            return df

        geo_data = pd.DataFrame.from_dict(as_geo_stats, orient='index')
        geo_data.index.name = 'asn'
        geo_data.reset_index(inplace=True)

        # 重命名列以匹配期望的名称
        # 无需重命名，保留最终输出列

        geo_data['asn'] = geo_data['asn'].astype(int)

        # 重命名AS数据中的ASN列为asn，以便进行merge
        df = df.rename(columns={'ASN': 'asn'})

        df = df.merge(geo_data, on='asn', how='left')
        return df

    def geolocate_ipv6_from_ipv4(self, enhanced_as_data: pd.DataFrame,
                                pfx2as_v6_file: str, force_rerun: bool,
                                confidence_threshold: float = 0.7) -> Optional[pd.DataFrame]:
        """基于高置信度的IPv4疆域推断IPv6地址的地理位置（优化版，使用pandas矢量化操作）"""
        print("\n=== Starting IPv6 Geolocation based on IPv4 Territory ===")

        # 使用pandas高效筛选高置信度AS
        high_confidence_as = enhanced_as_data[
            (enhanced_as_data['province_confidence'] >= confidence_threshold) &
            (enhanced_as_data['province_territory'].notna())
        ].copy()

        if high_confidence_as.empty:
            print(f"No AS found with province confidence >= {confidence_threshold}. Skipping IPv6 geolocation.")
            return None

        print(f"Found {len(high_confidence_as)} ASNs with confidence >= {confidence_threshold} for IPv6 mapping.")

        # 创建AS地理映射（使用pandas高效操作）
        as_geo_mapping = high_confidence_as.set_index('asn')[['as-name', 'province_territory',
                                                             'city_territory', 'province_confidence']].to_dict('index')

        # 解析IPv6 pfx2as数据
        v6_df = self.parse_pfx2as_file(
            pfx2as_v6_file, self.PFX2AS_V6_PROCESSED_FILE, ip_version=6, force_rerun=force_rerun
        )

        if v6_df.empty:
            print("No IPv6 prefixes found.")
            return None

        print(f"Processing {len(v6_df):,} IPv6 prefixes for geolocation...")

        # 使用pandas高效的join操作进行匹配
        v6_df = v6_df.copy()
        v6_df['asn'] = v6_df['asn'].astype(int)

        # 只保留有地理信息的AS的IPv6前缀
        matched_v6 = v6_df[v6_df['asn'].isin(high_confidence_as['asn'])].copy()

        if matched_v6.empty:
            print("No matching IPv6 prefixes found for high-confidence ASNs.")
            return None

        # 使用pandas join高效地添加地理信息
        geo_info_df = high_confidence_as[['asn', 'as-name', 'province_territory',
                                        'city_territory', 'province_confidence']].copy()
        # geo_info_df = geo_info_df.rename(columns={'asn': 'asn'})  # 重命名为标准的asn列名
        geo_info_df['asn'] = geo_info_df['asn'].astype(int)

        v6_geo_df = matched_v6.merge(geo_info_df, on='asn', how='inner')

        # 计算IPv6前缀统计信息（向量化操作）
        def calculate_ipv6_stats(prefix_str):
            """计算IPv6前缀的统计信息"""
            try:
                network = ipaddress.IPv6Network(prefix_str, strict=False)
                # 计算/48等价数量和IP地址数量
                if network.prefixlen <= 48:
                    std_count = 2 ** (48 - network.prefixlen)
                else:
                    std_count = 1
                ip_count = int(network.num_addresses)
                return std_count, ip_count
            except (ipaddress.AddressValueError, ipaddress.NetmaskValueError):
                return 1, 0

        # 重命名列以保持一致性
        v6_geo_df = v6_geo_df.rename(columns={'prefix': 'ipv6_prefix'})

        # 使用pandas的apply进行向量化计算
        v6_geo_df[['std_count', 'ip_count']] = v6_geo_df['ipv6_prefix'].apply(
            lambda x: pd.Series(calculate_ipv6_stats(x))
        )

        # 去重并排序
        v6_geo_df = v6_geo_df.drop_duplicates().sort_values('province_confidence', ascending=False)

        # 重新组织AS前缀数据用于统计
        as_prefixes_v6 = v6_geo_df.groupby('asn')['ipv6_prefix'].apply(list).to_dict()
        as_prefixes_v6 = {str(k): v for k, v in as_prefixes_v6.items()}

        self._print_ipv6_summary(v6_geo_df, as_prefixes_v6)
        return v6_geo_df

    def _print_ipv6_summary(self, v6_geo_df: pd.DataFrame, all_v6_prefixes: Dict[str, List[str]]):
        """打印IPv6地理定位结果的摘要"""
        total_v6_prefixes = sum(len(prefixes) for prefixes in all_v6_prefixes.values())
        total_v6_std_prefixes = 0
        total_v6_addresses = 0
        
        # 计算总的/48等价前缀数量和IP地址数量
        for prefixes in all_v6_prefixes.values():
            for prefix_str in prefixes:
                try:
                    network = ipaddress.IPv6Network(prefix_str, strict=False)
                    if network.prefixlen <= 48:
                        std_count = 2 ** (48 - network.prefixlen)
                    else:
                        std_count = 1
                    total_v6_std_prefixes += std_count
                    total_v6_addresses += int(network.num_addresses)
                except (ipaddress.AddressValueError, ipaddress.NetmaskValueError):
                    continue
        
        print("\n=== IPv6 Geolocation Summary ===")
        print(f"Total unique IPv6 original prefixes processed: {total_v6_prefixes:,}")
        print(f"Total /48 equivalent prefixes: {total_v6_std_prefixes:,}")
        print(f"Total IPv6 addresses: {total_v6_addresses:,}")
        print(f"Successfully geolocated IPv6 prefixes: {len(v6_geo_df):,}")
        
        if total_v6_prefixes > 0:
            coverage = len(v6_geo_df) / total_v6_prefixes * 100
            print(f"Coverage rate (by original prefixes): {coverage:.2f}%")
            
        print(f"Unique ASNs with geolocated IPv6 prefixes: {v6_geo_df['asn'].nunique()}")
        
        province_stats = v6_geo_df['province_territory'].value_counts()
        print("\nTop 5 provinces by geolocated IPv6 prefix count:")
        print(province_stats.head().to_string())

    def analyze(self, force_rerun: bool = False, start_from: str = None, steps: List[str] = None) -> None:
        """执行AS疆域分析流程，支持从任意步骤开始

        Args:
            force_rerun: 是否强制重新运行所有步骤
            start_from: 起始步骤名称
            steps: 要执行的步骤列表，如果为None则执行从start_from开始的所有步骤
        """
        print("Starting AS territory analysis...")

        # 定义步骤顺序
        step_order = ['data_loading', 'pfx2as_parsing', 'ipv4_geolocation', 'ipv6_geolocation']

        # 确定起始步骤索引
        if start_from:
            if start_from not in step_order:
                raise ValueError(f"Invalid start_from step: {start_from}. Must be one of: {step_order}")
            start_idx = step_order.index(start_from)
        else:
            start_idx = 0

        # 确定要执行的步骤
        if steps:
            steps_to_run = [step for step in steps if step in step_order]
            if not steps_to_run:
                raise ValueError(f"No valid steps specified: {steps}. Must be one of: {step_order}")
        else:
            steps_to_run = step_order[start_idx:]

        print(f"Will execute steps: {steps_to_run}")

        # 执行步骤
        for step in steps_to_run:
            print(f"\n{'='*60}")
            print(f"EXECUTING STEP: {step.upper()}")
            print('='*60)

            if step == 'data_loading':
                self._execute_data_loading(force_rerun)
            elif step == 'pfx2as_parsing':
                self._execute_pfx2as_parsing(force_rerun)
            elif step == 'ipv4_geolocation':
                self._execute_ipv4_geolocation(force_rerun)
            elif step == 'ipv6_geolocation':
                self._execute_ipv6_geolocation(force_rerun)

        print("\n" + "="*60)
        print("SELECTED STEPS COMPLETED SUCCESSFULLY")
        print("="*60)

    def _execute_data_loading(self, force_rerun: bool) -> None:
        """执行数据加载步骤"""
        self.load_as_data()

    def _execute_pfx2as_parsing(self, force_rerun: bool) -> None:
        """执行pfx2as解析步骤"""
        print("Processing IPv4 pfx2as data...")
        self.parse_pfx2as_file(
            self.PFX2AS_V4_RAW_FILE, self.PFX2AS_V4_PROCESSED_FILE, ip_version=4, force_rerun=force_rerun
        )

        print("Processing IPv6 pfx2as data...")
        self.parse_pfx2as_file(
            self.PFX2AS_V6_RAW_FILE, self.PFX2AS_V6_PROCESSED_FILE, ip_version=6, force_rerun=force_rerun
        )

    def _execute_ipv4_geolocation(self, force_rerun: bool) -> None:
        """执行IPv4地理定位步骤"""
        # 确保AS数据已加载
        if self.as_data is None:
            self.load_as_data()

        # 解析IPv4 pfx2as数据（如果需要）
        pfx2as_v4_df = self.parse_pfx2as_file(
            self.PFX2AS_V4_RAW_FILE, self.PFX2AS_V4_PROCESSED_FILE, ip_version=4, force_rerun=force_rerun
        )

        # 筛选出中国的AS前缀（使用pandas高效操作）
        china_asns = set(self.as_data['ASN'])  # 注意：AS数据文件中列名是ASN而不是asn
        # 确保类型匹配：将pfx2as中的asn转换为整数进行比较
        pfx2as_v4_df = pfx2as_v4_df.copy()
        pfx2as_v4_df['asn'] = pfx2as_v4_df['asn'].astype(int)
        china_prefixes_v4_df = pfx2as_v4_df[pfx2as_v4_df['asn'].isin(china_asns)].copy()

        print(f"\nFound {china_prefixes_v4_df['asn'].nunique():,} Chinese ASNs with IPv4 prefixes out of {len(china_asns)} total China ASNs.")

        # 统计中国IPv4前缀信息
        total_china_addresses = china_prefixes_v4_df['prefix'].apply(
            lambda x: int(ipaddress.IPv4Network(x, strict=False).num_addresses)
        ).sum()

        print(f"中国路由AS数量: {china_prefixes_v4_df['asn'].nunique()}")
        print(f"中国IPv4地址总数: {total_china_addresses:,}")

        # 对中国IPv4前缀进行地理定位
        as_geo_stats = self.geolocate_as_territory(china_prefixes_v4_df)
        print(f"Successfully geolocated {len(as_geo_stats)} Chinese ASNs.")

        # 将地理信息添加到AS数据中
        enhanced_as_data = self.add_territory_to_as_data(as_geo_stats)

        # 保存IPv4分析结果
        enhanced_as_data.to_csv(self.AS_TERRITORY_FILE, index=False)
        print(f"\nIPv4 analysis results saved to {self.AS_TERRITORY_FILE}")
        self._print_ipv4_summary(enhanced_as_data)

    def _execute_ipv6_geolocation(self, force_rerun: bool) -> None:
        """执行IPv6地理定位步骤"""
        # 确保AS数据已加载
        if self.as_data is None:
            self.load_as_data()

        # 检查IPv4分析结果是否存在
        if not os.path.exists(self.AS_TERRITORY_FILE):
            print(f"IPv4 analysis results not found at {self.AS_TERRITORY_FILE}")
            print("Please run IPv4 geolocation first or use --start-from ipv4_geolocation")
            return

        enhanced_as_data = pd.read_csv(self.AS_TERRITORY_FILE)

        v6_geo_df = self.geolocate_ipv6_from_ipv4(
            enhanced_as_data, self.PFX2AS_V6_RAW_FILE, force_rerun=force_rerun
        )
        if v6_geo_df is not None:
            v6_geo_df.to_csv(self.GEOLOCATED_IPV6_FILE, index=False)
            print(f"IPv6 geolocation results saved to {self.GEOLOCATED_IPV6_FILE}")

    def _print_ipv4_summary(self, result_data: pd.DataFrame):
        """打印IPv4分析结果的摘要"""
        located_count = result_data['province_territory'].notna().sum()
        total_count = len(result_data)
        print("\n=== IPv4 Geolocation Summary ===")
        if total_count > 0:
            percentage = located_count / total_count * 100
            print(f"Successfully located {located_count}/{total_count} AS entities ({percentage:.1f}%)")

        # 统计AS级别分布
        if 'as_level' in result_data.columns:
            level_stats = result_data['as_level'].value_counts()
            print(f"\nAS级别分布:")
            for level, count in level_stats.items():
                print(f"  {level}: {count}")

        print("\nSample results (Top 10 located ASNs by province confidence):")
        cols = ['asn', 'as-name', 'province_territory', 'city_territory', 'as_level',
                'province_confidence', 'city_confidence', 'total_std_prefixes']
        # 筛选、排序并显示样本
        sample = result_data[result_data['province_territory'].notna()].sort_values(
            'province_confidence', ascending=False
        )
        available_cols = [col for col in cols if col in sample.columns]
        print(sample[available_cols].head(10).to_string(index=False))


def main():
    """主函数，处理命令行参数并启动分析"""
    parser = argparse.ArgumentParser(description="AS Territory Analysis Tool")
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force re-running the analysis and ignore cached files.'
    )
    parser.add_argument(
        '--start-from',
        choices=['data_loading', 'pfx2as_parsing', 'ipv4_geolocation', 'ipv6_geolocation'],
        help='Start analysis from specified step. Options: data_loading, pfx2as_parsing, ipv4_geolocation, ipv6_geolocation'
    )
    parser.add_argument(
        '--steps',
        nargs='*',
        choices=['data_loading', 'pfx2as_parsing', 'ipv4_geolocation', 'ipv6_geolocation'],
        help='Run only specified steps (space-separated). If not provided, runs all steps from start-from.'
    )
    args = parser.parse_args()

    try:
        analyzer = ASTerritoryAnalyzer()
        analyzer.analyze(
            force_rerun=args.force,
            start_from=args.start_from,
            steps=args.steps
        )
    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
