import logging
import os
from datetime import datetime


class ScamperLogger:
    """
    ScamperTrace项目的日志系统
    提供统一的日志配置和管理
    """
    
    def __init__(self, log_dir: str = "logs", log_level: int = logging.INFO):
        """
        初始化日志系统
        
        参数:
            log_dir (str): 日志文件存储目录
            log_level (int): 日志级别
        """
        self.log_dir = log_dir
        self.log_level = log_level
        
        # 确保日志目录存在
        os.makedirs(self.log_dir, exist_ok=True)
        
        # 配置日志系统
        self._setup_logger()
    
    def _setup_logger(self):
        """配置日志记录器"""
        # 生成日志文件名（基于当前时间）
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_filename = f"scampertrace_{timestamp}.log"
        log_filepath = os.path.join(self.log_dir, log_filename)
        
        # 创建日志格式器
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 配置根日志记录器
        root_logger = logging.getLogger()
        root_logger.setLevel(self.log_level)
        
        # 清除现有的处理器
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # 创建文件处理器
        file_handler = logging.FileHandler(log_filepath, encoding='utf-8')
        file_handler.setLevel(self.log_level)
        file_handler.setFormatter(formatter)
        
        # 创建控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(self.log_level)
        console_handler.setFormatter(formatter)
        
        # 添加处理器到根日志记录器
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
        
        logging.info(f"日志系统初始化完成，日志文件: {log_filepath}")
    
    @staticmethod
    def get_logger(name: str = None) -> logging.Logger:
        """
        获取日志记录器实例
        
        参数:
            name (str): 日志记录器名称，默认为调用模块名
            
        返回:
            logging.Logger: 日志记录器实例
        """
        if name is None:
            # 自动获取调用模块的名称
            import inspect
            frame = inspect.currentframe().f_back
            name = frame.f_globals.get('__name__', 'ScamperTrace')
        
        return logging.getLogger(name)


# 便捷函数，用于快速初始化日志系统
def init_logger(log_dir: str = "logs", log_level: int = logging.INFO) -> logging.Logger:
    """
    初始化日志系统的便捷函数
    
    参数:
        log_dir (str): 日志目录路径
        log_level (int): 日志级别
        
    返回:
        logging.Logger: 日志记录器实例
    """
    ScamperLogger(log_dir, log_level)
    return ScamperLogger.get_logger('ScamperTrace')