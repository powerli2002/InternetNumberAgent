#!/usr/bin/env python3
"""
ScamperTrace主程序入口
支持网络前缀探测、IPv4/IPv6路径追踪、断点续传等功能
"""

import argparse
import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.scamper_controller import ScamperController
from utils import init_logger


def main():
    """主程序入口"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(
        description="ScamperTrace - 网络路径探测工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python main.py                          # 使用默认配置运行
  python main.py -f custom.csv            # 指定输入文件
  python main.py --nocontinues            # 禁用断点续传
  python main.py --cleanup-warts          # 探测后清理中间文件
  python main.py -c custom_config.json    # 使用自定义配置文件

输入文件格式:
  CSV文件应包含以下列之一：
  - ipv4: IPv4网络前缀 (如: 192.168.1.0/24)
  - ipv6: IPv6网络前缀 (如: 2001:db8::/48)  
  - prefix: 混合网络前缀
  
  多个前缀可用分号分隔: 192.168.1.0/24;10.0.0.0/24
        """
    )
    
    parser.add_argument('--source-file', '-f', type=str, default='prefix.csv', 
                       help='输入前缀文件名 (默认: prefix.csv)')
    parser.add_argument('--nocontinues', action='store_true', 
                       help='禁用断点续传功能')
    parser.add_argument('--cleanup-warts', action='store_true', 
                       help='探测完成后删除.warts中间文件')
    parser.add_argument('--config', '-c', type=str, default='config.json',
                       help='配置文件路径 (默认: config.json)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='启用详细输出模式')
    parser.add_argument('--source-device', '-sd', action='store_true',
                       help='启用Source/Device IPv6探测模式')
    
    args = parser.parse_args()
    
    try:
        # 初始化日志系统
        if args.verbose:
            import logging
            logger = init_logger(log_level=logging.DEBUG)
        else:
            logger = init_logger()
        
        logger.info("=" * 80)
        logger.info("ScamperTrace - 网络路径探测工具")
        logger.info("=" * 80)
        
        # 初始化控制器
        controller = ScamperController(config_file=args.config)
        
        # 检查输入文件是否存在
        input_file_path = os.path.join(controller.input_dir, args.source_file)
        if not os.path.exists(input_file_path):
            logger.error(f"输入文件不存在: {input_file_path}")
            logger.info("请创建包含网络前缀的CSV文件并放在输入目录中")
            logger.info("文件格式示例:")
            logger.info("  ipv4,ipv6")
            logger.info("  192.168.1.0/24,2001:db8::/48")
            logger.info("  10.0.0.0/24;172.16.0.0/24,")
            sys.exit(1)
        
        # 执行探测流程
        enable_resume = not args.nocontinues
        if args.nocontinues:
            logger.info("已禁用断点续传功能")
        
        logger.info(f"配置文件: {args.config}")
        logger.info(f"输入文件: {args.source_file}")
        logger.info(f"断点续传: {'启用' if enable_resume else '禁用'}")
        logger.info(f"清理中间文件: {'是' if args.cleanup_warts else '否'}")
        if args.source_device:
            logger.info("已启用Source/Device IPv6探测模式")
        
        results = controller.run_probe_and_parse(
            source_filename=args.source_file,
            enable_resume=enable_resume,
            cleanup_warts=args.cleanup_warts,
            sd_mode=args.source_device
        )
        
        # 输出结果摘要
        total_results = len(results.get('ipv4', [])) + len(results.get('ipv6', []))
        if total_results > 0:
            logger.info("探测结果摘要:")
            for version in ['ipv4', 'ipv6']:
                if results.get(version):
                    logger.info(f"  {version.upper()}结果文件 ({len(results[version])}个):")
                    for result_file in results[version]:
                        logger.info(f"    - {os.path.basename(result_file)}")
            
            # 输出最终合并文件信息
            if 'final' in results and results['final']:
                if args.source_device and results.get('sd_outputs'):
                    logger.info("Source/Device结果文件:")
                    for role, path in results['sd_outputs'].items():
                        logger.info(f"    - {role}: {os.path.basename(path)}")
                else:
                    logger.info("最终合并结果文件:")
                    for final_file in results['final']:
                        logger.info(f"    - {os.path.basename(final_file)}")
        else:
            logger.warning("未生成任何结果文件")
        
        logger.info("=" * 80)
        logger.info("ScamperTrace探测流程完成")
        logger.info("=" * 80)
        
    except KeyboardInterrupt:
        print("\n用户中断，程序退出")
        sys.exit(1)
    except Exception as e:
        print(f"程序执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
