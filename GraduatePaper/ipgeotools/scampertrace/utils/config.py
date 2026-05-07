import json
import os
from typing import Dict, Any, List


class ScamperConfig:
    """
    ScamperTrace配置管理系统
    负责加载和管理所有配置参数
    """
    
    def __init__(self, config_file: str = "config.json"):
        """
        初始化配置系统
        
        参数:
            config_file (str): 配置文件路径
        """
        self.config_file = config_file
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """
        加载配置文件，如果不存在则创建默认配置
        
        返回:
            Dict[str, Any]: 配置字典
        """
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError) as e:
                print(f"配置文件加载失败: {e}")
                return self._create_default_config()
        else:
            return self._create_default_config()
    
    def _create_default_config(self) -> Dict[str, Any]:
        """
        创建默认配置并保存到文件
        
        返回:
            Dict[str, Any]: 默认配置字典
        """
        default_config = {
            "scamper_commands": {
                "ipv6_icmp": {
                    "command": "trace -p 100 -P icmp-paris -g 30",
                    "description": "IPv6 ICMP巴黎追踪，30跳无响应后停止，100pps"
                },
                "ipv6_tcp_80": {
                    "command": "trace -p 100 -P tcp -d 80 -g 30",
                    "description": "IPv6 TCP追踪，目标端口80，30跳无响应后停止，100pps"
                },
                "ipv6_tcp_443": {
                    "command": "trace -p 100 -P tcp -d 443 -g 30",
                    "description": "IPv6 TCP追踪，目标端口443，30跳无响应后停止，100pps"
                },
                "ipv4_icmp": {
                    "command": "trace -p 100 -P icmp-paris -m 30 -g 30",
                    "description": "IPv4 ICMP巴黎追踪，最大30跳，30跳无响应后停止，100pps"
                }
            },
            "probe_settings": {
                "rate_limit": 100,
                "description_rate": "探测频率限制 (每小时IP地址数)",
                "max_ttl": 30,
                "description_ttl": "最大跳数限制",
                "gap_limit": 30,
                "description_gap": "连续无响应跳数限制",
                "timeout": 300,
                "description_timeout": "单次探测超时时间(秒)",
                "batch_size": 10,
                "description_batch": "批量探测时每批处理的IP数量"
            },
            "directories": {
                "input_dir": "data/input",
                "output_dir": "data/output", 
                "logs_dir": "logs",
                "description": "各类文件存储目录配置"
            },
            "prefix_handling": {
                "ipv4_split_threshold": 24,
                "description_ipv4": "IPv4前缀分割阈值，/24及以下选择最小地址，大于/24的拆分到/24",
                "ipv6_split_threshold": 48,
                "description_ipv6": "IPv6前缀分割阈值，/48及以下选择最小地址，大于/48的拆分到/48",
                "log_strategy_once": True,
                "description_log": "是否只在首次读取前缀时记录IP生成策略"
            },
            "resume_settings": {
                "enable_resume": True,
                "description_resume": "是否启用断点续传功能",
                "check_existing_results": True,
                "description_check": "是否检查已有结果文件",
                "result_file_patterns": ["*.jsonl", "*.csv", "*.warts"],
                "description_patterns": "结果文件匹配模式列表"
            }
        }
        
        # 保存默认配置到文件
        self.save_config(default_config)
        print(f"已创建默认配置文件: {self.config_file}")
        
        return default_config
    
    def save_config(self, config: Dict[str, Any] = None):
        """
        保存配置到文件
        
        参数:
            config (Dict[str, Any]): 要保存的配置，默认为当前配置
        """
        if config is None:
            config = self.config
            
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"配置文件保存失败: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值，支持点记法访问嵌套配置
        
        参数:
            key (str): 配置键，支持"parent.child"格式
            default (Any): 默认值
            
        返回:
            Any: 配置值
        """
        keys = key.split('.')
        value = self.config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key: str, value: Any):
        """
        设置配置值，支持点记法设置嵌套配置
        
        参数:
            key (str): 配置键，支持"parent.child"格式
            value (Any): 配置值
        """
        keys = key.split('.')
        config = self.config
        
        # 导航到最后一层的父级
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        # 设置值
        config[keys[-1]] = value
    
    def get_scamper_command(self, probe_type: str) -> str:
        """
        获取指定类型的scamper命令
        
        参数:
            probe_type (str): 探测类型 (ipv6_icmp, ipv6_tcp_80, ipv6_tcp_443, ipv4_icmp)
            
        返回:
            str: scamper命令字符串
        """
        return self.get(f"scamper_commands.{probe_type}.command", "")
    
    def get_probe_rate_limit(self) -> int:
        """获取探测频率限制 (每小时IP地址数)"""
        return self.get("probe_settings.rate_limit", 100)
    
    def get_directories(self) -> Dict[str, str]:
        """获取目录配置"""
        return self.get("directories", {})
    
    def get_prefix_thresholds(self) -> Dict[str, int]:
        """获取前缀分割阈值配置"""
        return {
            "ipv4": self.get("prefix_handling.ipv4_split_threshold", 24),
            "ipv6": self.get("prefix_handling.ipv6_split_threshold", 48)
        }
    
    def is_resume_enabled(self) -> bool:
        """检查是否启用断点续传"""
        return self.get("resume_settings.enable_resume", True)


# 全局配置实例
_config_instance = None


def get_config(config_file: str = "config.json") -> ScamperConfig:
    """
    获取全局配置实例
    
    参数:
        config_file (str): 配置文件路径
        
    返回:
        ScamperConfig: 配置实例
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = ScamperConfig(config_file)
    return _config_instance