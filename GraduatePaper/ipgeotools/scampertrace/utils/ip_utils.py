import ipaddress
from typing import List, Set, Tuple, Union
import logging


def generate_ips_from_prefix(prefix_str: str, ipv4_threshold: int = 24, ipv6_threshold: int = 48) -> List[str]:
    """
    根据前缀生成IP地址列表
    
    对于IPv4: /24及以下前缀选择最小地址，大于/24的拆分到/24前缀
    对于IPv6: /48及以下前缀选择最小地址，大于/48的拆分到/48前缀
    
    参数:
        prefix_str (str): 网络前缀字符串 (如 "192.168.1.0/24")
        ipv4_threshold (int): IPv4前缀分割阈值
        ipv6_threshold (int): IPv6前缀分割阈值
        
    返回:
        List[str]: 生成的IP地址列表
    """
    logger = logging.getLogger(__name__)
    
    try:
        network = ipaddress.ip_network(prefix_str, strict=False)
        
        if network.version == 4:
            return _handle_ipv4_prefix(network, ipv4_threshold, logger)
        else:  # IPv6
            return _handle_ipv6_prefix(network, ipv6_threshold, logger)
            
    except ValueError as e:
        logger.warning(f"无效的网络前缀: {prefix_str}, 错误: {e}")
        return []


def _handle_ipv4_prefix(network: ipaddress.IPv4Network, threshold: int, logger) -> List[str]:
    """
    处理IPv4前缀生成IP地址
    
    参数:
        network (ipaddress.IPv4Network): IPv4网络对象
        threshold (int): 分割阈值
        logger: 日志记录器
        
    返回:
        List[str]: IP地址列表
    """
    if network.prefixlen >= threshold:
        # /24及以上，选择最小地址（网络地址）
        ip = str(network.network_address)
        # logger.debug(f"IPv4前缀 {network} (/{network.prefixlen}) >= /{threshold}, 选择最小地址: {ip}")
        return [ip]
    else:
        # 小于/24，拆分到/24子网
        try:
            subnets = list(network.subnets(new_prefix=threshold))
            # 限制输出数量，避免生成过多IP
            if len(subnets) > 10000:
                logger.warning(f"IPv4前缀 {network} 会生成{len(subnets)}个子网，限制为前10000个")
                subnets = subnets[:10000]
            ips = [str(subnet.network_address) for subnet in subnets]
            logger.debug(f"IPv4前缀 {network} (/{network.prefixlen}) < /{threshold}, 拆分为{len(ips)}个/{threshold}子网")
            return ips
        except ValueError as e:
            # 如果无法拆分，返回网络地址
            logger.warning(f"IPv4前缀 {network} 无法拆分到/{threshold}: {e}, 使用网络地址")
            return [str(network.network_address)]


def _handle_ipv6_prefix(network: ipaddress.IPv6Network, threshold: int, logger) -> List[str]:
    """
    处理IPv6前缀生成IP地址
    
    参数:
        network (ipaddress.IPv6Network): IPv6网络对象  
        threshold (int): 分割阈值
        logger: 日志记录器
        
    返回:
        List[str]: IP地址列表
    """
    if network.prefixlen >= threshold:
        # /48及以上，选择最小地址（网络地址）
        ip = str(network.network_address)
        logger.debug(f"IPv6前缀 {network} (/{network.prefixlen}) >= /{threshold}, 选择最小地址: {ip}")
        return [ip]
    else:
        # 小于/48，拆分到/48子网
        try:
            subnets = list(network.subnets(new_prefix=threshold))
            # 限制输出数量，避免生成过多IP（IPv6可能数量极大）
            if len(subnets) > 50000:
                logger.warning(f"IPv6前缀 {network} 会生成{len(subnets)}个子网，限制为前50000个")
                subnets = subnets[:50000]
            ips = [str(subnet.network_address) for subnet in subnets]
            logger.debug(f"IPv6前缀 {network} (/{network.prefixlen}) < /{threshold}, 拆分为{len(ips)}个/{threshold}子网")
            return ips
        except ValueError as e:
            # 如果无法拆分（比如前缀长度差异过大），选择网络地址
            logger.warning(f"IPv6前缀 {network} 无法拆分到/{threshold}: {e}, 使用网络地址")
            return [str(network.network_address)]


def validate_ip_address(ip_str: str) -> Tuple[bool, Union[ipaddress.IPv4Address, ipaddress.IPv6Address, None]]:
    """
    验证IP地址格式
    
    参数:
        ip_str (str): IP地址字符串
        
    返回:
        Tuple[bool, Union[IPv4Address, IPv6Address, None]]: (是否有效, IP地址对象)
    """
    try:
        ip_obj = ipaddress.ip_address(ip_str)
        return True, ip_obj
    except ValueError:
        return False, None


def validate_network_prefix(prefix_str: str) -> Tuple[bool, Union[ipaddress.IPv4Network, ipaddress.IPv6Network, None]]:
    """
    验证网络前缀格式
    
    参数:
        prefix_str (str): 网络前缀字符串
        
    返回:
        Tuple[bool, Union[IPv4Network, IPv6Network, None]]: (是否有效, 网络对象)
    """
    try:
        network_obj = ipaddress.ip_network(prefix_str, strict=False)
        return True, network_obj
    except ValueError:
        return False, None


def deduplicate_ips(ip_list: List[str]) -> List[str]:
    """
    对IP地址列表去重，保持原始顺序
    
    参数:
        ip_list (List[str]): IP地址列表
        
    返回:
        List[str]: 去重后的IP地址列表
    """
    seen = set()
    result = []
    
    for ip in ip_list:
        if ip not in seen:
            seen.add(ip)
            result.append(ip)
    
    return result


def separate_ipv4_ipv6(ip_list: List[str]) -> Tuple[List[str], List[str]]:
    """
    将IP地址列表分离为IPv4和IPv6两个列表
    
    参数:
        ip_list (List[str]): 混合的IP地址列表
        
    返回:
        Tuple[List[str], List[str]]: (IPv4列表, IPv6列表)
    """
    ipv4_list = []
    ipv6_list = []
    logger = logging.getLogger(__name__)
    
    for ip_str in ip_list:
        is_valid, ip_obj = validate_ip_address(ip_str)
        if is_valid:
            if ip_obj.version == 4:
                ipv4_list.append(ip_str)
            else:  # IPv6
                ipv6_list.append(ip_str)
        else:
            logger.warning(f"跳过无效的IP地址: {ip_str}")
    
    return ipv4_list, ipv6_list


def log_prefix_strategy(prefix_str: str, generated_ips: List[str], logger):
    """
    记录前缀处理策略的日志信息
    
    参数:
        prefix_str (str): 原始前缀字符串
        generated_ips (List[str]): 生成的IP地址列表  
        logger: 日志记录器
    """
    is_valid, network = validate_network_prefix(prefix_str)
    if not is_valid:
        logger.warning(f"前缀 {prefix_str} 格式无效")
        return
    
    ip_version = "IPv4" if network.version == 4 else "IPv6"
    threshold = 24 if network.version == 4 else 48
    
    if len(generated_ips) == 1:
        strategy = f"选择最小地址"
    else:
        strategy = f"拆分为{len(generated_ips)}个/{threshold}子网"
    
    if network.prefixlen < threshold:
        logger.info(f"前缀处理策略 - {ip_version}前缀: {prefix_str} (/{network.prefixlen}) -> {strategy} -> 生成{len(generated_ips)}个IP地址")
    
    if len(generated_ips) <= 5:
        logger.debug(f"生成的IP地址: {', '.join(generated_ips)}")
    else:
        logger.debug(f"生成的IP地址示例: {', '.join(generated_ips[:5])} ... (共{len(generated_ips)}个)")


def get_network_address_from_prefix(prefix_str: str) -> str:
    """
    从前缀字符串中获取网络地址
    
    参数:
        prefix_str (str): 网络前缀字符串
        
    返回:
        str: 网络地址字符串，如果无效则返回原字符串
    """
    try:
        network = ipaddress.ip_network(prefix_str, strict=False)
        return str(network.network_address)
    except ValueError:
        return prefix_str