#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动实验脚本

自动排列组合所有参数，并读取对应delta(距离延迟转换系数)相同的cache文件，运行CBGTool。
跳过output中已有的实验设置。

使用delta参数：0.398, 1/3, 1/6, 1/9, 2/9
使用探针策略：all, l3, d3, t3
使用方法：cbg, octant
"""

import sys
import os
import json
import time
import itertools
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import requests

# 添加项目根目录到路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.CBGTool import CBGTool
from scripts.utils.logging_manager import logger


class AutoExperiment:
    """自动实验类"""
    
    def __init__(self, limit: int = 1000, dry_run: bool = False, offline_mode: bool = False):
        """
        初始化自动实验
        
        Args:
            limit: 处理目标数量限制
            dry_run: 是否只模拟运行（不实际执行）
            offline_mode: 是否使用离线模式（不获取地址信息）
        """
        self.limit = limit
        self.dry_run = dry_run
        self.offline_mode = offline_mode
        self.output_dir = Path(__file__).parent.parent / "data" / "output"
        
        # 实验参数配置
        self.delta_values = [
            0.189
            # 0.398,
            # 1/3,    # 0.333...
            # 1/6    # 0.166...
            # 1/9,    # 0.111...
            # 2/9     # 0.222...
        ]
        
        self.probe_strategies = ['all', 'l3', 'd3', 't3']
        self.methods = ['cbg', 'octant','octant_poly']
        
        logger.info(f"自动实验初始化完成")
        logger.info(f"目标数量限制: {self.limit}")
        logger.info(f"Delta值: {self.delta_values}")
        logger.info(f"探针策略: {self.probe_strategies}")
        logger.info(f"方法: {self.methods}")
        logger.info(f"模拟运行: {self.dry_run}")
        if self.offline_mode:
            logger.info(f"离线模式: 启用（不获取地址信息）")
    
    def format_delta_for_filename(self, delta_value: float) -> str:
        """
        将delta值格式化为文件名格式
        例如: 1/3 -> 1_3, 0.398 -> 0.398, 0.3333333333333333 -> 0.333
        """
        if delta_value is None:
            return "default"
        
        # 检查是否接近特定分数值
        fraction_mappings = {
            1/3: "1_3",
            1/6: "1_6", 
            1/9: "1_9",
            2/9: "2_9"
        }
        
        for fraction, filename in fraction_mappings.items():
            if abs(delta_value - fraction) < 1e-10:
                return filename
        
        # 处理其他小数值
        if delta_value == int(delta_value):
            return str(int(delta_value))
        else:
            # 保留3位小数并去除末尾的0
            formatted = f"{delta_value:.3f}".rstrip('0').rstrip('.')
            return formatted
    
    def get_result_filename(self, method: str, delta: float, strategy: str) -> str:
        """
        根据方法、delta和探针策略生成结果文件名
        
        Args:
            method: 定位方法 ('cbg', 'octant')
            delta: delta值
            strategy: 探针策略
            
        Returns:
            str: 结果文件名
        """
        delta_str = self.format_delta_for_filename(delta)
        return f"user_result_loc_{method}_{delta_str}_{strategy}.json"
    
    def check_experiment_exists(self, method: str, delta: float, strategy: str) -> bool:
        """
        检查实验结果是否已存在
        
        Args:
            method: 定位方法
            delta: delta值  
            strategy: 探针策略
            
        Returns:
            bool: True如果实验已存在，False否则
        """
        result_filename = self.get_result_filename(method, delta, strategy)
        result_path = self.output_dir / result_filename
        
        exists = result_path.exists()
        if exists:
            logger.debug(f"实验已存在: {result_filename}")
        
        return exists
    
    def get_cache_files_for_delta(self, delta: float) -> List[Path]:
        """
        获取与指定delta对应的缓存文件列表
        
        Args:
            delta: delta值
            
        Returns:
            List[Path]: 对应的缓存文件路径列表
        """
        delta_str = self.format_delta_for_filename(delta)
        cache_files = []
        
        # 查找所有包含该delta的结果文件作为缓存
        pattern_prefixes = [
            f"user_result_loc_cbg_{delta_str}_",
            f"user_result_loc_octant_{delta_str}_"
        ]
        
        for file_path in self.output_dir.glob("*.json"):
            for prefix in pattern_prefixes:
                if file_path.name.startswith(prefix):
                    cache_files.append(file_path)
                    break
        
        logger.debug(f"Delta {delta} ({delta_str}) 对应的缓存文件: {[f.name for f in cache_files]}")
        return cache_files
    
    def generate_experiment_combinations(self) -> List[Tuple[str, float, str]]:
        """
        生成所有实验参数组合
        
        Returns:
            List[Tuple[str, float, str]]: (method, delta, strategy) 组合列表
        """
        combinations = list(itertools.product(self.methods, self.delta_values, self.probe_strategies))
        
        logger.info(f"生成了 {len(combinations)} 个实验组合")
        return combinations
    
    def filter_existing_experiments(self, combinations: List[Tuple[str, float, str]]) -> List[Tuple[str, float, str]]:
        """
        过滤掉已存在的实验
        
        Args:
            combinations: 所有实验组合
            
        Returns:
            List[Tuple[str, float, str]]: 需要执行的实验组合
        """
        remaining_combinations = []
        
        for method, delta, strategy in combinations:
            if not self.check_experiment_exists(method, delta, strategy):
                remaining_combinations.append((method, delta, strategy))
            else:
                logger.info(f"跳过已存在的实验: {method} delta={delta} strategy={strategy}")
        
        logger.info(f"需要执行的实验数量: {len(remaining_combinations)}")
        return remaining_combinations
    
    def run_single_experiment(self, method: str, delta: float, strategy: str, max_retries: int = 2) -> bool:
        """
        运行单个实验
        
        Args:
            method: 定位方法
            delta: delta值
            strategy: 探针策略
            max_retries: 最大重试次数
            
        Returns:
            bool: 实验是否成功
        """
        retries = 0
        while retries <= max_retries:
            try:
                if retries > 0:
                    logger.warning(f"第 {retries} 次重试实验: method={method}, delta={delta}, strategy={strategy}")
                else:
                    logger.info(f"开始实验: method={method}, delta={delta}, strategy={strategy}")
                
                if self.dry_run:
                    logger.info(f"模拟运行: 跳过实际执行")
                    time.sleep(0.1)  # 模拟一点处理时间
                    return True
                
                # 设置CBGTool参数
                use_cbg = True
                use_octant = (method == 'octant')
                
                # 创建CBGTool实例
                tool = CBGTool(
                    limit=self.limit,
                    use_cbg=use_cbg,
                    use_ncr=False,  # 不使用NCR方法
                    use_octant=use_octant,
                    probe_strategy=strategy,
                    delta=delta,
                    offline_mode=self.offline_mode
                )
                
                # 运行实验
                results = tool.run()
                
                # 检查结果是否有效
                result_count = 0
                if use_cbg:
                    result_count += len(results.get('result_ori', []))
                if use_octant:
                    result_count += len(results.get('result_octant', []))
                
                if result_count == 0:
                    raise ValueError("实验未生成有效结果")
                
                logger.info(f"实验完成: method={method}, delta={delta}, strategy={strategy}")
                logger.info(f"结果统计: CBG={len(results.get('result_ori', []))}, Octant={len(results.get('result_octant', []))}")
                
                return True
                
            except KeyboardInterrupt:
                logger.warning("用户中断实验")
                raise  # 重新抛出键盘中断异常，允许用户终止程序
                
            except requests.exceptions.RequestException as e:
                logger.error(f"网络请求错误: {e}")
                if "Connection refused" in str(e):
                    logger.error("代理连接被拒绝，请检查代理设置")
                    
                # 对于网络错误，如果已达到最大重试次数，则放弃
                if retries >= max_retries:
                    logger.error(f"已达到最大重试次数 {max_retries}，放弃实验")
                    return False
                    
                # 否则等待一段时间后重试
                wait_time = (retries + 1) * 5  # 递增等待时间
                logger.warning(f"等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
                retries += 1
                continue
                
            except Exception as e:
                logger.error(f"实验失败: method={method}, delta={delta}, strategy={strategy}, 错误: {str(e)}")
                
                # 如果是致命错误，不再重试
                if "NoneType" in str(e) and "not iterable" in str(e):
                    logger.error("遇到数据格式错误，可能是缓存文件问题")
                    # 对于特定错误，如果已重试过，则放弃
                    if retries > 0:
                        return False
                
                # 如果已达到最大重试次数，则放弃
                if retries >= max_retries:
                    logger.error(f"已达到最大重试次数 {max_retries}，放弃实验")
                    return False
                
                # 否则等待一段时间后重试
                wait_time = (retries + 1) * 5  # 递增等待时间
                logger.warning(f"等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
                retries += 1
                
        return False
    
    def run_all_experiments(self) -> Dict[str, int]:
        """
        运行所有实验
        
        Returns:
            Dict[str, int]: 实验统计结果
        """
        logger.info("="*80)
        logger.info("开始自动实验")
        logger.info("="*80)
        
        # 生成所有实验组合
        all_combinations = self.generate_experiment_combinations()
        
        # 过滤已存在的实验
        remaining_combinations = self.filter_existing_experiments(all_combinations)
        
        if not remaining_combinations:
            logger.info("所有实验已完成，无需执行新实验")
            return {
                'total': len(all_combinations),
                'existing': len(all_combinations),
                'executed': 0,
                'successful': 0,
                'failed': 0
            }
        
        # 执行实验
        successful_count = 0
        failed_count = 0
        
        for i, (method, delta, strategy) in enumerate(remaining_combinations, 1):
            logger.info(f"\n进度: {i}/{len(remaining_combinations)}")
            logger.info("-" * 60)
            
            success = self.run_single_experiment(method, delta, strategy)
            
            if success:
                successful_count += 1
            else:
                failed_count += 1
                
            # 简短暂停，避免系统负载过高
            if not self.dry_run:
                time.sleep(1)
        
        # 统计结果
        stats = {
            'total': len(all_combinations),
            'existing': len(all_combinations) - len(remaining_combinations),
            'executed': len(remaining_combinations),
            'successful': successful_count,
            'failed': failed_count
        }
        
        logger.info("="*80)
        logger.info("自动实验完成")
        logger.info("="*80)
        logger.info(f"总实验数量: {stats['total']}")
        logger.info(f"已存在实验: {stats['existing']}")
        logger.info(f"执行实验数量: {stats['executed']}")
        logger.info(f"成功实验数量: {stats['successful']}")
        logger.info(f"失败实验数量: {stats['failed']}")
        
        if stats['failed'] > 0:
            logger.warning(f"有 {stats['failed']} 个实验失败，请检查日志")
        
        return stats
    
    def list_experiments(self) -> None:
        """列出所有实验组合和状态"""
        logger.info("实验状态列表:")
        logger.info("="*80)
        
        all_combinations = self.generate_experiment_combinations()
        
        existing_count = 0
        missing_count = 0
        
        for method, delta, strategy in all_combinations:
            exists = self.check_experiment_exists(method, delta, strategy)
            status = "✓ 已完成" if exists else "✗ 待执行"
            
            if exists:
                existing_count += 1
            else:
                missing_count += 1
                
            delta_str = self.format_delta_for_filename(delta)
            logger.info(f"{status} | method={method:7} | delta={delta_str:4} | strategy={strategy}")
        
        logger.info("="*80)
        logger.info(f"统计: 已完成 {existing_count}, 待执行 {missing_count}, 总计 {len(all_combinations)}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='CBG自动实验脚本')
    parser.add_argument('--limit', type=int, default=1000,
                       help='处理目标数量限制 (默认: 1000)')
    parser.add_argument('--dry-run', action='store_true',
                       help='模拟运行，不实际执行实验')
    parser.add_argument('--list', action='store_true',
                       help='仅列出实验状态，不执行实验')
    parser.add_argument('--offline', action='store_true',
                       help='离线模式，不获取地址信息')
    
    args = parser.parse_args()
    
    # 创建自动实验实例
    auto_exp = AutoExperiment(
        limit=args.limit, 
        dry_run=args.dry_run,
        offline_mode=args.offline
    )
    
    if args.list:
        # 仅列出实验状态
        auto_exp.list_experiments()
    else:
        # 运行实验
        stats = auto_exp.run_all_experiments()
        
        # 如果有失败的实验，返回非零退出码
        if stats['failed'] > 0:
            sys.exit(1)


if __name__ == "__main__":
    main() 