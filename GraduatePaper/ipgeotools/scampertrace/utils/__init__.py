"""
ScamperTrace 工具函数包

包含日志管理、配置管理、IP地址处理等工具函数
"""

from .logger import ScamperLogger, init_logger
from .config import ScamperConfig, get_config
from .ip_utils import (
    generate_ips_from_prefix,
    validate_ip_address,
    validate_network_prefix,
    deduplicate_ips,
    separate_ipv4_ipv6,
    log_prefix_strategy,
    get_network_address_from_prefix
)

__all__ = [
    'ScamperLogger',
    'init_logger', 
    'ScamperConfig',
    'get_config',
    'generate_ips_from_prefix',
    'validate_ip_address',
    'validate_network_prefix',
    'deduplicate_ips',
    'separate_ipv4_ipv6',
    'log_prefix_strategy',
    'get_network_address_from_prefix'
]