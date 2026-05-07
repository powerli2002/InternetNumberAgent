
import os
import subprocess
import time
from datetime import datetime
import ipaddress
import pandas as pd
import argparse
import glob
import re
from typing import List, Dict, Set, Tuple

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.warts2csv import Warts2Csv
from utils import init_logger, get_config, generate_ips_from_prefix, separate_ipv4_ipv6, log_prefix_strategy, get_network_address_from_prefix

class ScamperController:
    """
    ScamperTrace探测控制器
    管理网络前缀的读取、IP地址生成、探测执行和结果解析
    支持IPv4/IPv6、ICMP/TCP多种探测方式、断点续传等功能
    """
    
    def __init__(self, input_dir: str = 'data/input', output_dir: str = 'data/output', config_file: str = 'config.json'):
        """
        初始化ScamperController
        
        参数:
            input_dir (str): 输入文件目录
            output_dir (str): 输出文件目录
            config_file (str): 配置文件路径
        """
        # 初始化日志系统
        self.logger = init_logger()
        self.logger.info("正在初始化ScamperTrace控制器...")
        
        # 加载配置
        self.config = get_config(config_file)
        
        # 设置目录路径
        self.root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_dirs = self.config.get_directories()
        self.input_dir = os.path.join(self.root_dir, config_dirs.get('input_dir', input_dir))
        self.output_dir = os.path.join(self.root_dir, config_dirs.get('output_dir', output_dir))
        self.logs_dir = os.path.join(self.root_dir, config_dirs.get('logs_dir', 'logs'))
        
        # 探测日志文件路径
        self.probed_log_file_v4 = os.path.join(self.output_dir, 'probed_log_v4.txt')
        self.probed_log_file_v6 = os.path.join(self.output_dir, 'probed_log_v6.txt')
        
        # 确保必要目录存在
        for directory in [self.input_dir, self.output_dir, self.logs_dir]:
            os.makedirs(directory, exist_ok=True)
        
        # 前缀处理策略记录标志
        self._prefix_strategy_logged = set()

        # Source/Device模式追踪
        self.sd_mode = False
        self.sd_role_map = {
            'source': set(),
            'device': set()
        }

        # ping结果缓存，避免重复执行
        self._ping_cache: Dict[str, str] = {}
        
        self.logger.info(f"控制器初始化完成 - 输入目录: {self.input_dir}, 输出目录: {self.output_dir}")

    def _get_probed_ips_from_csv(self, ip_version: str) -> Set[str]:
        """
        从解析的CSV文件中读取已探测IP地址
        
        参数:
            ip_version (str): IP版本 ('ipv4' 或 'ipv6')
            
        返回:
            Set[str]: 已探测的IP地址集合
        """
        existing_ips = set()
        
        # 扫描输出目录中的所有CSV文件
        csv_pattern = os.path.join(self.output_dir, '*.csv')
        csv_files = glob.glob(csv_pattern)
        
        for csv_file in csv_files:
            try:
                # 从文件名判断IP版本
                filename = os.path.basename(csv_file).lower()
                if ip_version == 'ipv4' and 'ipv4' in filename:
                    ips = self._extract_ips_from_csv(csv_file)
                    existing_ips.update(ips)
                elif ip_version == 'ipv6' and 'ipv6' in filename:
                    ips = self._extract_ips_from_csv(csv_file)
                    existing_ips.update(ips)
                    
            except Exception as e:
                self.logger.warning(f"解析CSV文件{csv_file}失败: {e}")
        
        self.logger.debug(f"从CSV文件中读取到{len(existing_ips)}个已探测的{ip_version}地址")
        return existing_ips

    def _get_probed_ips(self, ip_version: str) -> Set[str]:
        """
        读取已探测IP地址（从CSV文件读取）
        
        参数:
            ip_version (str): IP版本 ('ipv4' 或 'ipv6')
            
        返回:
            Set[str]: 已探测的IP地址集合
        """
        # 从CSV文件中读取已探测的IP
        csv_ips = self._get_probed_ips_from_csv(ip_version)
        if csv_ips:
            return csv_ips
        

    def _classify_files_by_ip_version(self, source_basename: str, file_patterns: List[str], include_result_csv: bool = True) -> Dict[str, List[str]]:
        """
        根据IP版本分类文件

        参数:
            source_basename (str): 源文件basename
            file_patterns (List[str]): 文件pattern列表，例如 ['*.csv', '*.warts']
            include_result_csv (bool): 是否将result.csv文件归类到ipv6

        返回:
            Dict[str, List[str]]: {'ipv4': [...], 'ipv6': [...]}
        """
        results = {'ipv4': [], 'ipv6': []}

        for pattern in file_patterns:
            full_pattern = os.path.join(self.output_dir, f'{source_basename}{pattern}')
            files = glob.glob(full_pattern)

            for file_path in files:
                filename = os.path.basename(file_path)
                if filename.startswith(f'{source_basename}_ipv4'):
                    results['ipv4'].append(file_path)
                elif filename.startswith(f'{source_basename}_ipv6'):
                    results['ipv6'].append(file_path)
                elif include_result_csv and filename.endswith('result.csv'):
                    results['ipv6'].append(file_path)

        return results

    def _get_existing_results(self, source_filename: str) -> Dict[str, Set[str]]:
        """
        扫描输出目录，获取已有结果文件中的IP地址

        返回:
            Dict[str, Set[str]]: {'ipv4': set(), 'ipv6': set()}
        """
        source_basename = source_filename.split('.')[0]
        existing_ips = {'ipv4': set(), 'ipv6': set()}

        # 使用统一方法获取文件列表
        file_results = self._classify_files_by_ip_version(source_basename, ['*.csv', '*.warts'])

        # 提取文件列表用于一致性检查
        temp_csv_files = file_results['ipv4'] + file_results['ipv6']
        temp_warts_files = [f.replace('.csv', '.warts') for f in temp_csv_files]

        # 检查文件数量一致性，如果不一致则重新解析
        if len(temp_csv_files) != len(temp_warts_files):
            self.logger.info(f"检测到文件数量不一致 - CSV: {len(temp_csv_files)}个, WARTS: {len(temp_warts_files)}个，正在重新解析...")
            self._reparse_inconsistent_files(temp_warts_files, temp_csv_files)
            # 重新获取CSV文件列表
            file_results = self._classify_files_by_ip_version(source_basename, ['*.csv'])
            temp_csv_files = file_results['ipv4'] + file_results['ipv6']

        for file_path in temp_csv_files:
            try:
                ips = self._extract_ips_from_csv(file_path)

                # 根据文件路径判断IP版本
                if '_ipv4' in os.path.basename(file_path):
                    existing_ips['ipv4'].update(ips)
                elif '_ipv6' in os.path.basename(file_path) or file_path.endswith('result.csv'):
                    existing_ips['ipv6'].update(ips)

            except Exception as e:
                self.logger.warning(f"解析结果文件{file_path}失败: {e}")

        self.logger.info(f"从结果文件中发现已探测IP - IPv4: {len(existing_ips['ipv4'])}个, IPv6: {len(existing_ips['ipv6'])}个")
        return existing_ips

    def _reparse_inconsistent_files(self, warts_files: List[str], csv_files: List[str]):
        """
        重新解析不一致的文件，确保warts和csv文件数量一致
        
        参数:
            warts_files: 现有的warts文件列表
            csv_files: 现有的csv文件列表
        """
        self.logger.info("开始重新解析不一致的文件...")
        
        # 从warts文件名推断应该存在的csv文件
        expected_csv_files = set()
        for warts_file in warts_files:
            base_name = os.path.splitext(os.path.basename(warts_file))[0]
            expected_csv = os.path.join(self.output_dir, f"{base_name}.csv")
            expected_csv_files.add(expected_csv)
        
        # 检查哪些warts文件缺少对应的csv文件
        missing_csvs = expected_csv_files - set(csv_files)
        
        if missing_csvs:
            self.logger.info(f"发现{len(missing_csvs)}个缺少对应CSV文件的WARTS文件，正在重新解析...")
            for warts_file in warts_files:
                base_name = os.path.splitext(os.path.basename(warts_file))[0]
                expected_csv = os.path.join(self.output_dir, f"{base_name}.csv")
                
                if expected_csv in missing_csvs:
                    try:
                        self.logger.debug(f"重新解析: {warts_file} -> {expected_csv}")
                        warts2csv = Warts2Csv()
                        tracetype = self._infer_tracetype_from_filename(warts_file)
                        warts2csv.main(warts_file, expected_csv, tracetype)
                        
                        if os.path.exists(expected_csv) and os.path.getsize(expected_csv) > 0:
                            self.logger.debug(f"重新解析成功: {expected_csv}")
                        else:
                            self.logger.warning(f"重新解析失败，未生成有效文件: {expected_csv}")
                    except Exception as e:
                        self.logger.error(f"重新解析文件失败: {warts_file}, 错误: {e}")

    def _calculate_probe_difference(self, input_ips: Dict[str, List[str]], existing_ips: Dict[str, Set[str]]) -> Dict[str, List[str]]:
        """
        计算需要探测的IP地址差集
        
        参数:
            input_ips: 输入的IP地址 {'ipv4': [...], 'ipv6': [...]}
            existing_ips: 已存在的IP地址 {'ipv4': set(...), 'ipv6': set(...)}
            
        返回:
            Dict[str, List[str]]: 需要探测的IP地址差集
        """
        new_ips = {}
        
        for ip_version in ['ipv4', 'ipv6']:
            input_set = set(input_ips.get(ip_version, []))
            existing_set = existing_ips.get(ip_version, set())
            
            # 计算差集：输入IP - 已存在IP
            difference = input_set - existing_set
            new_ips[ip_version] = list(difference)
            
            skipped = len(input_set) - len(difference)
            if skipped > 0:
                self.logger.info(f"断点续传过滤 - 跳过已探测{ip_version}: {skipped}个")
        
        return new_ips

    def _validate_final_results(self, source_filename: str, final_csv_file: str) -> Dict[str, List[str]]:
        """
        验证最终结果文件与输入文件的IP一致性，如果不一致则返回需要补充探测的IP
        
        参数:
            source_filename: 输入文件名
            final_csv_file: 最终结果CSV文件路径
            
        返回:
            Dict[str, List[str]]: 需要补充探测的IP地址 {'ipv4': [...], 'ipv6': [...]}
        """
        if not os.path.exists(final_csv_file):
            self.logger.warning("最终结果文件不存在，无法验证一致性")
            return {'ipv4': [], 'ipv6': []}
        
        # 获取输入文件中的所有IP
        input_ips = self._get_all_input_ips(source_filename)
        
        # 获取最终结果文件中的所有IP
        result_ips = self._extract_ips_from_csv(final_csv_file)
        
        # 按IP版本分类
        result_ipv4 = set()
        result_ipv6 = set()
        
        for ip in result_ips:
            try:
                # 判断IP版本
                ip_obj = ipaddress.ip_address(ip)
                if ip_obj.version == 4:
                    result_ipv4.add(ip)
                else:
                    result_ipv6.add(ip)
            except ValueError:
                self.logger.warning(f"跳过无效IP地址: {ip}")
        
        # 计算差集：输入IP - 结果IP
        missing_ipv4 = set(input_ips.get('ipv4', [])) - result_ipv4
        missing_ipv6 = set(input_ips.get('ipv6', [])) - result_ipv6
        
        missing_ips = {
            'ipv4': list(missing_ipv4),
            'ipv6': list(missing_ipv6)
        }
        
        total_missing = len(missing_ipv4) + len(missing_ipv6)
        if total_missing > 0:
            self.logger.warning(f"检测到结果不一致 - 缺少{total_missing}个IP地址")
            self.logger.info(f"缺少IPv4: {len(missing_ipv4)}个, IPv6: {len(missing_ipv6)}个")
        else:
            self.logger.info("结果验证通过 - 所有输入IP地址都有对应的探测结果")
        
        return missing_ips

    def _get_all_input_ips(self, source_filename: str) -> Dict[str, List[str]]:
        """
        获取输入文件中的所有IP地址（不进行断点续传过滤）
        
        参数:
            source_filename: 输入文件名
            
        返回:
            Dict[str, List[str]]: 所有输入IP地址 {'ipv4': [...], 'ipv6': [...]}
        """
        source_path = os.path.join(self.input_dir, source_filename)
        if not os.path.exists(source_path):
            self.logger.error(f"输入文件不存在: {source_path}")
            return {'ipv4': [], 'ipv6': []}

        try:
            # 读取前缀文件
            df = pd.read_csv(source_path)
            
            # 提取IPv4和IPv6前缀
            prefixes_v4 = []
            prefixes_v6 = []
            
            if 'ipv4' in df.columns:
                ipv4_data = df['ipv4'].dropna().tolist()
                prefixes_v4 = [prefix.strip() for row in ipv4_data 
                              for prefix in str(row).split(';') if prefix.strip()]
            
            if 'ipv6' in df.columns:
                ipv6_data = df['ipv6'].dropna().tolist()
                prefixes_v6 = [prefix.strip() for row in ipv6_data 
                              for prefix in str(row).split(';') if prefix.strip()]
            
            # 如果没有分别的IPv4/IPv6列，尝试从统一的prefix列中分离
            if 'prefix' in df.columns and not prefixes_v4 and not prefixes_v6:
                prefix_data = df['prefix'].dropna().tolist()
                all_prefixes = [prefix.strip() for row in prefix_data 
                               for prefix in str(row).split(';') if prefix.strip()]
                
                for prefix in all_prefixes:
                    try:
                        network = ipaddress.ip_network(prefix, strict=False)
                        if network.version == 4:
                            prefixes_v4.append(prefix)
                        else:
                            prefixes_v6.append(prefix)
                    except ValueError:
                        self.logger.warning(f"跳过无效前缀: {prefix}")
            
            # 将前缀转换为IP地址
            ips_v4 = self._process_prefixes_to_ips(prefixes_v4)
            ips_v6 = self._process_prefixes_to_ips(prefixes_v6)
            
            return {'ipv4': ips_v4, 'ipv6': ips_v6}
            
        except Exception as e:
            self.logger.error(f"读取输入文件失败: {e}")
            return {'ipv4': [], 'ipv6': []}

    def _get_source_device_ips(self, source_filename: str) -> Tuple[Dict[str, List[str]], Dict[str, Set[str]]]:
        """
        读取包含source/device IPv6列的输入文件

        返回:
            Tuple[Dict[str, List[str]], Dict[str, Set[str]]]
        """
        source_path = os.path.join(self.input_dir, source_filename)
        if not os.path.exists(source_path):
            self.logger.error(f"输入文件不存在: {source_path}")
            return {'ipv4': [], 'ipv6': []}, {'source': set(), 'device': set()}

        df = pd.read_csv(source_path)
        required_columns = {'source_ipv6', 'device_ipv6'}
        if not required_columns.issubset(set(df.columns)):
            self.logger.error(f"缺少必要列: {required_columns - set(df.columns)}")
            return {'ipv4': [], 'ipv6': []}, {'source': set(), 'device': set()}

        ordered_ipv6 = []
        seen = set()
        role_map = {'source': set(), 'device': set()}

        def add_ip(value: str, role: str):
            candidate = value.strip()
            if not candidate:
                return
            try:
                ip_obj = ipaddress.ip_address(candidate)
            except ValueError:
                self.logger.warning(f"跳过无效IPv6地址({role}): {candidate}")
                return

            if ip_obj.version != 6:
                self.logger.warning(f"跳过非IPv6地址({role}): {candidate}")
                return

            normalized = str(ip_obj)
            role_map[role].add(normalized)
            if normalized not in seen:
                seen.add(normalized)
                ordered_ipv6.append(normalized)

        for _, row in df.iterrows():
            for column, role in [('source_ipv6', 'source'), ('device_ipv6', 'device')]:
                value = row[column]
                if pd.isna(value):
                    continue
                for part in str(value).split(';'):
                    add_ip(part, role)

        self.logger.info(f"Source/Device模式 - Source IPv6: {len(role_map['source'])}个, Device IPv6: {len(role_map['device'])}个, 去重后总数: {len(ordered_ipv6)}个")
        return {'ipv4': [], 'ipv6': ordered_ipv6}, role_map

    def _ping_target(self, ip: str) -> str:
        """
        对目标IP执行一次ping，超时时间0.5秒
        返回值以ms为单位的字符串，失败时返回状态描述
        """
        if ip in self._ping_cache:
            return self._ping_cache[ip]

        try:
            ip_obj = ipaddress.ip_address(ip)
        except ValueError:
            self.logger.warning(f"ping目标无效IP: {ip}")
            self._ping_cache[ip] = 'invalid_ip'
            return self._ping_cache[ip]

        ping_command = ['ping', '-c', '1', '-n']
        if ip_obj.version == 6:
            ping_command.insert(1, '-6')
        ping_command.append(ip)

        try:
            result = subprocess.run(
                ping_command,
                capture_output=True,
                text=True,
                timeout=0.5,
                check=True
            )
            match = re.search(r'time[=<]?([\d\.]+)\s*ms', result.stdout)
            if match:
                ping_value = f"{match.group(1)}ms"
            else:
                ping_value = 'unavailable'
        except subprocess.TimeoutExpired:
            self.logger.debug(f"ping超时(0.5s): {ip}")
            ping_value = 'timeout'
        except FileNotFoundError:
            self.logger.error("未找到ping命令，无法记录ping_rtt")
            ping_value = 'ping_missing'
        except subprocess.CalledProcessError as e:
            self.logger.debug(f"ping失败: {ip}, 错误: {e.stderr.strip() if e.stderr else e}")
            ping_value = 'failed'

        self._ping_cache[ip] = ping_value
        return ping_value

    def _attach_ping_results(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        为结果DataFrame补充每个dst的ping_rtt信息
        """
        if df.empty or 'dst' not in df.columns:
            return df

        if 'ping_rtt' not in df.columns:
            df['ping_rtt'] = None

        # 找出缺少ping_rtt的目标
        ping_needed_mask = df['ping_rtt'].isna() | (df['ping_rtt'].astype(str).str.strip() == "")
        targets = df.loc[ping_needed_mask, 'dst'].dropna().unique()

        for target in targets:
            ping_value = self._ping_target(target)
            df.loc[df['dst'] == target, 'ping_rtt'] = ping_value

        return df

    def prepare_input_files(self, source_filename: str = 'prefix.csv', enable_resume: bool = True, sd_mode: bool = False) -> Dict[str, List[str]]:
        """
        读取源CSV文件，处理前缀，生成IP地址，支持断点续传
        
        参数:
            source_filename (str): 输入文件名
            enable_resume (bool): 是否启用断点续传
            
        返回:
            Dict[str, List[str]]: {'ipv4': [...], 'ipv6': [...]}
        """
        self.sd_mode = sd_mode
        if sd_mode:
            all_input_ips, role_map = self._get_source_device_ips(source_filename)
            self.sd_role_map = role_map
        else:
            self.sd_role_map = {'source': set(), 'device': set()}
            all_input_ips = self._get_all_input_ips(source_filename)
        
        if not all_input_ips['ipv4'] and not all_input_ips['ipv6']:
            self.logger.error("没有从输入文件中读取到有效的IP地址")
            return {'ipv4': [], 'ipv6': []}

        self.logger.info(f"从前缀生成IP地址 - IPv4: {len(all_input_ips['ipv4'])}个, IPv6: {len(all_input_ips['ipv6'])}个")

        # 断点续传逻辑
        if enable_resume and self.config.is_resume_enabled():
            self.logger.info("启用断点续传，正在检查已探测的IP地址...")
            
            # 获取现有结果文件中的IP地址
            # 获取IP时，如果有空csv需要删去
            existing_results = self._get_existing_results(source_filename)
            
            # 计算需要探测的IP地址差集
            ips_to_probe = self._calculate_probe_difference(all_input_ips, existing_results)
            
        else:
            # 不使用断点续传，探测所有IP
            ips_to_probe = all_input_ips

        self.logger.info(f"最终待探测IP地址 - IPv4: {len(ips_to_probe['ipv4'])}个, IPv6: {len(ips_to_probe['ipv6'])}个")
        
        return ips_to_probe

    def _execute_scamper_batch_probe(self, ips: List[str], probe_type: str, ip_version: str, batch_size: int = 10, output_prefix: str = "") -> List[str]:
        """
        执行批量IP地址的scamper探测（使用CSV文件输入方式）
        支持超时重试机制，失败批次翻倍超时时间重试
        
        参数:
            ips (List[str]): 待探测的IP地址列表
            probe_type (str): 探测类型 (icmp, tcp_80, tcp_443)
            ip_version (str): IP版本 ('ipv4' 或 'ipv6')
            batch_size (int): 每批处理的IP数量
            output_prefix (str): 输出文件前缀
            
        返回:
            List[str]: 成功的探测结果文件路径列表
        """
        command = self.config.get_scamper_command(probe_type)
        output_format = self.config.get('probe_settings.output_format', 'warts')
        if not command:
            self.logger.error(f"未找到探测类型 {probe_type} 的命令配置")
            return []
        
        successful_results = []
        
        # 将IP列表分批处理，每个批次包含重试信息
        batches = []
        for i in range(0, len(ips), batch_size):
            batch_ips = ips[i:i + batch_size]
            batch_num = i // batch_size + 1
            batches.append({
                'ips': batch_ips,
                'batch_num': batch_num,
                'retry_count': 0,
                'timeout_multiplier': 1
            })
        
        total_batches = len(batches)
        
        # 处理所有批次（包括重试）
        current_batch_index = 0
        while current_batch_index < len(batches):
            batch_info = batches[current_batch_index]
            batch_ips = batch_info['ips']
            batch_num = batch_info['batch_num']
            retry_count = batch_info['retry_count']
            timeout_multiplier = batch_info['timeout_multiplier']
            
            if retry_count > 0:
                self.logger.info(f"重试第{batch_num}批IP地址，包含{len(batch_ips)}个IP (第{retry_count}次重试，超时时间翻{timeout_multiplier}倍)")
            else:
                self.logger.info(f"开始处理第{batch_num}/{total_batches}批IP地址，包含{len(batch_ips)}个IP")
            
            # 创建临时CSV输入文件（无列名）
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
            retry_suffix = f"_retry{retry_count}" if retry_count > 0 else ""
            temp_prefix = f"{output_prefix}_" if output_prefix else ""
            temp_input_file = os.path.join(self.output_dir, f"temp_input_{temp_prefix}{ip_version}_{probe_type}_batch{batch_num}{retry_suffix}_{timestamp}.csv")
            
            batch_success = False
            
            try:
                # 写入批次IP到CSV文件（无列名）
                with open(temp_input_file, 'w', encoding='utf-8') as f:
                    for ip in batch_ips:
                        f.write(f"{ip}\n")
                
                # 生成输出文件名（带IP版本和输入前缀）
                prefix_part = f"{output_prefix}_" if output_prefix else ""
                warts_filename = f"{prefix_part}{ip_version}_{probe_type}_batch{batch_num}{retry_suffix}_{timestamp}.warts"
                warts_filepath = os.path.join(self.output_dir, warts_filename)
                
                # 构建scamper命令（严格按照指定格式）
                scamper_path = self.config.get('system_settings.scamper_path', 'scamper')
                use_sudo = self.config.get('system_settings.use_sudo', True)
                global_pps = self.config.get('probe_settings.global_pps', 100)
                
                if use_sudo:
                    scamper_command = [
                        'sudo', scamper_path,
                        '-c', command,
                        '-p', str(global_pps),
                        '-o', warts_filepath,
                        '-O', output_format,
                        '-f', temp_input_file
                    ]
                else:
                    scamper_command = [
                        scamper_path,
                        '-c', command,
                        '-p', str(global_pps),
                        '-o', warts_filepath,
                        '-O', output_format,
                        '-f', temp_input_file
                    ]
                
                # 构建显示用的命令字符串（带引号）
                if use_sudo:
                    display_command = f'sudo {scamper_path} -c "{command}" -p {global_pps} -o "{warts_filepath}" -O "{output_format}" -f "{temp_input_file}"'
                else:
                    display_command = f'{scamper_path} -c "{command}" -p {global_pps} -o "{warts_filepath}" -O "{output_format}" -f "{temp_input_file}"'
                
                self.logger.info(f"执行批量探测命令: {display_command}")
                
                # 记录开始时间
                start_time = datetime.now()
                
                # 计算超时时间（基础超时时间 * 翻倍因子）
                base_timeout = self.config.get('probe_settings.timeout_per_ip', 180) * len(batch_ips)
                actual_timeout = base_timeout * timeout_multiplier
                
                if retry_count > 0:
                    self.logger.info(f"重试超时设置: {actual_timeout}秒 (基础{base_timeout}秒 × {timeout_multiplier})")
                
                result = subprocess.run(
                    scamper_command, 
                    check=True, 
                    capture_output=True, 
                    text=True,
                    timeout=actual_timeout
                )
                
                # 记录结束时间并计算耗时
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                # 检查输出文件是否创建成功
                if os.path.exists(warts_filepath) and os.path.getsize(warts_filepath) > 0:
                    retry_info = f" (重试成功)" if retry_count > 0 else ""
                    self.logger.info(f"批量探测成功: 第{batch_num}批 {len(batch_ips)}个IP，耗时 {duration:.2f}秒{retry_info} -> {warts_filepath}")
                    successful_results.append(warts_filepath)
                    batch_success = True

                    # 记录探测速度统计
                    rate = len(batch_ips) / duration if duration > 0 else 0
                    self.logger.info(f"探测速度统计: {rate:.2f} IP/秒，预计每10个IP需要 {10/rate:.1f}秒" if rate > 0 else "探测速度统计: 无法计算")
                    
                else:
                    self.logger.warning(f"批量探测无结果: 第{batch_num}批")
                
                    
            except subprocess.TimeoutExpired:
                timeout_info = f"超时 {actual_timeout}秒" if timeout_multiplier > 1 else f"超时"
                self.logger.warning(f"批量探测{timeout_info}: 第{batch_num}批")
                    
            except subprocess.CalledProcessError as e:
                self.logger.warning(f"批量探测失败: 第{batch_num}批, 错误: {e.stderr}")
                    
            except FileNotFoundError:
                self.logger.error("未找到scamper命令，请确保scamper已安装并在PATH中")
                break
                
            except Exception as e:
                self.logger.error(f"批量探测出现异常: 第{batch_num}批, 错误: {e}")
            finally:
                if os.path.exists(temp_input_file):
                    try:
                        os.remove(temp_input_file)
                    except OSError as e:
                        self.logger.warning(f"删除临时输入文件失败: {temp_input_file}, 错误: {e}")
            
            # 处理失败的批次
            if not batch_success and retry_count < 2:  # 最多重试2次
                # 创建重试批次，翻倍超时时间
                retry_batch = {
                    'ips': batch_ips,
                    'batch_num': batch_num,
                    'retry_count': retry_count + 1,
                    'timeout_multiplier': timeout_multiplier * 2
                }
                
                self.logger.info(f"第{batch_num}批探测失败，将在当前批次后重试 (超时时间: {base_timeout * retry_batch['timeout_multiplier']}秒)")
                
                # 将重试批次插入到下一个位置，保证优先级
                batches.insert(current_batch_index + 1, retry_batch)
            
            current_batch_index += 1
        
        return successful_results

    def _probe_batch_with_fallback(self, ips: List[str], ip_version: str, batch_size: int = 10, output_prefix: str = "") -> List[str]:
        """
        对IP地址列表进行批量探测，优先使用TCP端口探测，失败时回退到ICMP

        参数:
            ips (List[str]): IP地址列表
            ip_version (str): IP版本 ('ipv4' 或 'ipv6')
            batch_size (int): 每批处理的IP数量
            output_prefix (str): 输出文件前缀

        返回:
            List[str]: 成功的探测结果文件路径列表
        """
        if not ips:
            return []

        successful_results = []
        probe_sequence = [
            ('icmp', 'ICMP'),
            ('tcp_80', 'TCP端口80'),
            ('tcp_443', 'TCP端口443')
        ]

        for probe_type, description in probe_sequence:
            self.logger.info(f"开始{ip_version.upper()} {description}批量探测: {len(ips)}个IP地址，批量大小: {batch_size}")
            probe_results = self._execute_scamper_batch_probe(ips, probe_type, ip_version, batch_size, output_prefix)
            successful_results.extend(probe_results)

            if probe_results:
                self.logger.info(f"{ip_version.upper()} {description}批量探测完成，生成{len(probe_results)}个结果文件")
            else:
                self.logger.warning(f"{ip_version.upper()} {description}批量探测未产生结果文件")

        return successful_results





    
    def _supplement_probes(self, missing_ips: Dict[str, List[str]], output_prefix: str, existing_results: Dict[str, List[str]]):
        """
        对缺失的IP地址进行补充探测
        
        参数:
            missing_ips: 缺失的IP地址 {'ipv4': [...], 'ipv6': [...]}
            output_prefix: 输出文件前缀
            existing_results: 现有的结果文件
        """
        if not missing_ips['ipv4'] and not missing_ips['ipv6']:
            return
        
        self.logger.info("开始补充探测缺失的IP地址...")
        
        # 执行补充探测
        supplement_results = self.run_probes(missing_ips, output_prefix=f"{output_prefix}_supplement")
        
        # 解析补充探测结果
        supplement_warts = supplement_results['ipv4'] + supplement_results['ipv6']
        if supplement_warts:
            supplement_parsed = self.parse_results(supplement_warts)
            
            # 将补充结果添加到现有结果中
            for parsed_file in supplement_parsed:
                filename = os.path.basename(parsed_file)
                if filename.startswith(f'{output_prefix}_supplement_ipv4'):
                    existing_results['ipv4'].append(parsed_file)
                elif filename.startswith(f'{output_prefix}_supplement_ipv6'):
                    existing_results['ipv6'].append(parsed_file)
            
            self.logger.info(f"补充探测完成，新增{len(supplement_parsed)}个结果文件")
            
            # 重新合并所有CSV文件
            all_csv_files = existing_results['ipv4'] + existing_results['ipv6']
            if all_csv_files:
                final_result_file = self._merge_csv_files(all_csv_files, f"{output_prefix}")
                if final_result_file:
                    if self.sd_mode:
                        sd_outputs = self._export_sd_results(final_result_file, output_prefix)
                        if sd_outputs:
                            existing_results['final'] = list(sd_outputs.values())
                            existing_results['sd_outputs'] = sd_outputs
                        else:
                            existing_results['final'] = [final_result_file]
                    else:
                        existing_results['final'] = [final_result_file]
                    self.logger.info(f"更新后的最终结果文件: {final_result_file}")
        else:
            self.logger.warning("补充探测未生成任何结果文件")

    def _extract_ips_from_csv(self, file_path: str) -> Set[str]:
        """从CSV文件中提取目标IP地址"""
        ips = set()
        try:
            df = pd.read_csv(file_path)
            
            # 检查是否有dst列
            if 'dst' in df.columns:
                ips.update(df['dst'].dropna().astype(str).tolist())

        except Exception as e:
            self.logger.debug(f"解析CSV文件{file_path}失败: {e}")
        return ips

    def _merge_csv_files(self, csv_files: List[str], source_filename: str) -> str:
        """
        合并多个CSV文件到一个最终结果文件
        
        参数:
            csv_files (List[str]): 要合并的CSV文件路径列表
            source_filename (str): 输入文件名（用于生成输出文件名）
            
        返回:
            str: 合并后的CSV文件路径
        """
        if not csv_files:
            self.logger.warning("没有CSV文件需要合并")
            return ""
        
        # 生成最终结果文件名
        base_name = os.path.splitext(source_filename)[0]
        final_csv_name = f"{base_name}_result.csv"
        final_csv_path = os.path.join(self.output_dir, final_csv_name)
        
        self.logger.info(f"开始合并{len(csv_files)}个CSV文件到: {final_csv_path}")
        
        try:
            # 读取并合并所有CSV文件
            all_dataframes = []
            for csv_file in csv_files:
                if os.path.exists(csv_file) and os.path.getsize(csv_file) > 0:
                    try:
                        df = pd.read_csv(csv_file)
                        if not df.empty:
                            all_dataframes.append(df)
                            self.logger.debug(f"成功读取CSV文件: {csv_file} ({len(df)}行)")
                        else:
                            self.logger.warning(f"CSV文件为空: {csv_file}")
                    except Exception as e:
                        self.logger.warning(f"读取CSV文件失败: {csv_file}, 错误: {e}")
            
            if not all_dataframes:
                self.logger.warning("没有有效的CSV数据可以合并")
                return ""
            
            # 合并所有数据框
            merged_df = pd.concat(all_dataframes, ignore_index=True)
            
            # 去重（基于dst列，保留第一条；若无dst列则基于所有列）
            original_count = len(merged_df)
            dedup_subset = ['dst', 'tracetype'] if 'tracetype' in merged_df.columns else ['dst']
            merged_df = merged_df.drop_duplicates(subset=dedup_subset, keep='first')
            final_count = len(merged_df)
            if original_count != final_count:
                self.logger.info(f"基于{'+'.join(dedup_subset)}去重后: {original_count} -> {final_count} (移除{original_count - final_count}行重复记录)")

            # 追加ping_rtt
            merged_df = self._attach_ping_results(merged_df)

            # 调整列顺序，将 ping_rtt 放在 dst 后
            if 'ping_rtt' in merged_df.columns and 'dst' in merged_df.columns:
                columns = [col for col in merged_df.columns if col != 'ping_rtt']
                dst_index = columns.index('dst')
                columns.insert(dst_index + 1, 'ping_rtt')
                merged_df = merged_df[columns]

            # 保存合并后的文件
            merged_df.to_csv(final_csv_path, index=False)
            
            self.logger.info(f"CSV文件合并完成: {final_csv_path} ({len(merged_df)}行数据)")
            return final_csv_path
            
        except Exception as e:
            self.logger.error(f"合并CSV文件失败: {e}")
            return ""

    def _export_sd_results(self, combined_csv: str, source_basename: str) -> Dict[str, str]:
        """
        根据Source/Device角色拆分结果文件
        """
        outputs: Dict[str, str] = {}
        if not self.sd_mode or not combined_csv or not os.path.exists(combined_csv):
            return outputs

        df = pd.read_csv(combined_csv)
        base_name = source_basename

        for role in ['source', 'device']:
            ips = self.sd_role_map.get(role, set())
            if not ips:
                continue

            role_df = df[df['dst'].isin(ips)]
            output_path = os.path.join(self.output_dir, f"{base_name}_{role}_result.csv")
            if role_df.empty:
                self.logger.warning(f"{role}角色没有匹配的探测结果，输出空文件: {output_path}")
                role_df.to_csv(output_path, index=False)
            else:
                role_df.to_csv(output_path, index=False)
                self.logger.info(f"{role.capitalize()}结果文件: {output_path} ({len(role_df)}行)")

            outputs[role] = output_path

        return outputs

    def _process_prefixes_to_ips(self, prefixes: List[str]) -> List[str]:
        """
        将前缀列表转换为IP地址列表
        根据配置的前缀处理策略生成IP地址
        
        参数:
            prefixes (List[str]): 网络前缀列表
            
        返回:
            List[str]: 生成的IP地址列表
        """
        thresholds = self.config.get_prefix_thresholds()
        all_ips = []
        
        for prefix in prefixes:
            generated_ips = generate_ips_from_prefix(
                prefix, 
                thresholds['ipv4'], 
                thresholds['ipv6']
            )
            
            # 记录前缀处理策略（每个前缀只记录一次）
            if prefix not in self._prefix_strategy_logged:
                log_prefix_strategy(prefix, generated_ips, self.logger)
                self._prefix_strategy_logged.add(prefix)
            
            all_ips.extend(generated_ips)
        
        return all_ips

    def run_probes(self, ips_to_probe: Dict[str, List[str]], output_prefix: str = "") -> Dict[str, List[str]]:
        """
        执行探测任务
        
        参数:
            ips_to_probe (Dict[str, List[str]]): 待探测的IP地址字典
            
        返回:
            Dict[str, List[str]]: 成功探测的结果文件路径字典
        """
        results = {'ipv4': [], 'ipv6': []}
        batch_size = self.config.get('probe_settings.batch_size', 10)
        
        # 探测IPv4地址（使用批量探测方式）
        if ips_to_probe['ipv4']:
            self.logger.info(f"开始批量探测{len(ips_to_probe['ipv4'])}个IPv4地址，批量大小: {batch_size}...")
            
            warts_files = self._probe_batch_with_fallback(ips_to_probe['ipv4'], 'ipv4', batch_size, output_prefix)
            if warts_files:
                results['ipv4'].extend(warts_files)
        
        # 探测IPv6地址（使用批量探测方式）
        if ips_to_probe['ipv6']:
            self.logger.info(f"开始批量探测{len(ips_to_probe['ipv6'])}个IPv6地址，批量大小: {batch_size}...")
            
            warts_files = self._probe_batch_with_fallback(ips_to_probe['ipv6'], 'ipv6', batch_size, output_prefix)
            if warts_files:
                results['ipv6'].extend(warts_files)
        
        return results

    def _infer_tracetype_from_filename(self, filepath: str) -> str:
        """根据文件名推测探测类型"""
        filename = os.path.basename(filepath).lower()
        if '_icmp_' in filename:
            return 'icmp'
        if '_tcp_80_' in filename or '_tcp80_' in filename:
            return 'tcp_80'
        if '_tcp_443_' in filename or '_tcp443_' in filename:
            return 'tcp_443'
        return 'unknown'

    def parse_results(self, warts_files: List[str], cleanup_warts: bool = True) -> List[str]:
        """
        解析探测结果文件
        
        参数:
            warts_files (List[str]): .warts文件路径列表
            
        返回:
            List[str]: 解析后的结果文件路径列表
        """
        parsed_files = []
        
        for warts_file in warts_files:
            if not os.path.exists(warts_file):
                self.logger.warning(f"结果文件不存在: {warts_file}")
                continue
            
            # 生成解析后的文件名
            base_name = os.path.splitext(os.path.basename(warts_file))[0]
            # 保持与.warts同名的.csv，已包含输入前缀
            csv_filename = f"{base_name}.csv"
            csv_filepath = os.path.join(self.output_dir, csv_filename)
            
            try:
                self.logger.debug(f"正在解析: {warts_file} -> {csv_filepath}")
                warts2csv = Warts2Csv()
                tracetype = self._infer_tracetype_from_filename(warts_file)
                warts2csv.main(warts_file, csv_filepath, tracetype)
                
                if os.path.exists(csv_filepath):
                    parsed_files.append(csv_filepath)
                    self.logger.debug(f"解析成功: {csv_filepath}")
                    if cleanup_warts and os.path.exists(warts_file):
                        try:
                            os.remove(warts_file)
                            self.logger.debug(f"已清理WARTS文件: {warts_file}")
                        except OSError as e:
                            self.logger.warning(f"删除WARTS文件失败: {warts_file}, 错误: {e}")
                else:
                    self.logger.warning(f"解析失败，未生成结果文件: {csv_filepath}")
                    
            except Exception as e:
                self.logger.error(f"解析文件失败: {warts_file}, 错误: {e}")
        
        return parsed_files
    
    def search_output_file(self, source_filename: str) -> Dict[str, List[str]]:
        """
        搜索输出目录中与源文件相关的所有结果文件

        参数:
            source_filename: 源文件名

        返回:
            Dict[str, List[str]]: {'ipv4': [...], 'ipv6': [...]}
        """
        source_basename = source_filename.split('.')[0]

        # 使用统一方法获取文件列表
        result = self._classify_files_by_ip_version(source_basename, ['*.warts', '*.csv'], include_result_csv=False)

        self.logger.debug(f"搜索到相关文件 - IPv4: {len(result['ipv4'])}个, IPv6: {len(result['ipv6'])}个")
        return result

    def run_probe_and_parse(self, source_filename: str = 'prefix.csv', enable_resume: bool = True, cleanup_warts: bool = False, sd_mode: bool = False) -> Dict[str, List[str]]:
        """
        执行完整的探测和解析流程
        
        参数:
            source_filename (str): 输入文件名
            enable_resume (bool): 是否启用断点续传
            cleanup_warts (bool): 是否清理.warts文件
            
        返回:
            Dict[str, List[str]]: 解析结果文件路径字典
        """
        self.logger.info("=" * 60)
        self.logger.info("开始执行ScamperTrace探测流程")
        self.logger.info("=" * 60)
        
        # 1. 准备输入数据
        ips_to_probe = self.prepare_input_files(source_filename, enable_resume, sd_mode)
        all_warts_files = {'ipv4': [], 'ipv6': []}
        
        total_ips = len(ips_to_probe['ipv4']) + len(ips_to_probe['ipv6'])
        if total_ips == 0:
            self.logger.info("没有需要探测的IP地址,跳过探测")
            parsed_files = []
        else:
            # 2. 执行探测
            self.logger.info("执行探测")
            input_prefix = os.path.splitext(os.path.basename(source_filename))[0]
            warts_results = self.run_probes(ips_to_probe, output_prefix=input_prefix)
        
            # 3. 收集所有结果文件（包括已有的和刚生成的）
            if enable_resume:
                # 从output文件夹收集所有相关文件
                all_warts_files = self.search_output_file(source_filename)
                # 合并新生成的warts文件
                all_warts_files['ipv4'].extend(warts_results['ipv4'])
                all_warts_files['ipv6'].extend(warts_results['ipv6'])
                # 去重
                all_warts_files['ipv4'] = list(set(all_warts_files['ipv4']))
                all_warts_files['ipv6'] = list(set(all_warts_files['ipv6']))
            else:
                all_warts_files = warts_results
        
            # 4. 解析结果
            self.logger.info("开始解析探测结果...")
            parsed_files = self.parse_results(all_warts_files['ipv4'] + all_warts_files['ipv6'])
        
        # # 5. 分类解析结果
        source_basename = os.path.splitext(os.path.basename(source_filename))[0]
        results = self._classify_files_by_ip_version(source_basename, ['*.csv'])
            
        # 6. 合并所有CSV文件到最终结果文件
        all_csv_files = results['ipv4'] + results['ipv6']
        final_result_file = self._merge_csv_files(all_csv_files, source_filename)
        if final_result_file:
            self.logger.info(f"最终结果文件: {final_result_file}")

            if self.sd_mode:
                sd_outputs = self._export_sd_results(final_result_file, source_basename)
                if sd_outputs:
                    results['final'] = list(sd_outputs.values())
                    results['sd_outputs'] = sd_outputs
                else:
                    results['final'] = [final_result_file]
            else:
                results['final'] = [final_result_file]
            
            # 7. 验证最终结果与输入的一致性
            missing_ips = self._validate_final_results(source_filename, final_result_file)
            
            # 8. 如果有缺失的IP，进行补充探测
            if missing_ips['ipv4'] or missing_ips['ipv6']:
                self.logger.info("检测到结果不完整，开始补充探测...")
                self._supplement_probes(missing_ips, input_prefix, results)
    
        # 9. 清理中间文件
        if cleanup_warts:
            self.logger.info("清理中间文件...")
            all_warts_list = all_warts_files['ipv4'] + all_warts_files['ipv6']
            for warts_file in all_warts_list:
                try:
                    if os.path.exists(warts_file):
                        os.remove(warts_file)
                        self.logger.debug(f"已删除: {warts_file}")
                except Exception as e:
                    self.logger.warning(f"删除文件失败: {warts_file}, 错误: {e}")
        
        self.logger.info("=" * 60)
        self.logger.info(f"探测流程完成 - 成功解析{len(parsed_files)}个结果文件")
        self.logger.info(f"IPv4结果文件: {len(results['ipv4'])}个")
        self.logger.info(f"IPv6结果文件: {len(results['ipv6'])}个")
        if 'final' in results:
            self.logger.info(f"最终合并文件: {len(results['final'])}个")
        self.logger.info("=" * 60)
        
        return results



if __name__ == '__main__':
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="ScamperTrace网络探测控制器")
    parser.add_argument('--source-file', '-f', type=str, default='ipv4_test.csv', 
                       help='输入前缀文件名 (默认: prefix.csv)')
    parser.add_argument('--nocontinues', action='store_true', default=False,
                       help='禁用断点续传功能')
    parser.add_argument('--cleanup-warts', action='store_true', default=False,
                       help='探测完成后删除.warts文件')
    parser.add_argument('--config', '-c', type=str, default='config.json',
                       help='配置文件路径 (默认: config.json)')
    parser.add_argument('--source-device', '-sd', action='store_true',
                       help='启用Source/Device IPv6探测模式')
    
    args = parser.parse_args()
    
    try:
        # 初始化控制器
        controller = ScamperController(config_file=args.config)
        
        # 检查输入文件是否存在
        input_file_path = os.path.join(controller.input_dir, args.source_file)
        if not os.path.exists(input_file_path):
            controller.logger.error(f"输入文件不存在: {input_file_path}")
            controller.logger.info("请将包含网络前缀的CSV文件放在输入目录中")
            sys.exit(1)
        
        # 执行探测流程
        enable_resume = not args.nocontinues
        if args.nocontinues:
            controller.logger.info("已禁用断点续传功能")
        
        results = controller.run_probe_and_parse(
            source_filename=args.source_file,
            enable_resume=enable_resume,
            cleanup_warts=args.cleanup_warts,
            sd_mode=args.source_device
        )
        
        # 输出结果摘要
        total_results = len(results.get('ipv4', [])) + len(results.get('ipv6', []))
        if total_results > 0:
            controller.logger.info("探测结果摘要:")
            for version in ['ipv4', 'ipv6']:
                if results.get(version):
                    controller.logger.info(f"  {version.upper()}结果文件 ({len(results[version])}个):")
                    for result_file in results[version]:
                        controller.logger.info(f"    - {os.path.basename(result_file)}")
            
            # 输出最终合并文件信息
            if 'final' in results and results['final']:
                if args.source_device and results.get('sd_outputs'):
                    controller.logger.info("Source/Device结果文件:")
                    for role, path in results['sd_outputs'].items():
                        controller.logger.info(f"    - {role}: {os.path.basename(path)}")
                else:
                    controller.logger.info("最终合并结果文件:")
                    for final_file in results['final']:
                        controller.logger.info(f"    - {os.path.basename(final_file)}")
        else:
            controller.logger.warning("未生成任何结果文件")
        
        controller.logger.info("ScamperTrace探测流程完成")
        
    except KeyboardInterrupt:
        print("\n用户中断，程序退出")
        sys.exit(1)
    except Exception as e:
        print(f"程序执行失败: {e}")
        sys.exit(1)
