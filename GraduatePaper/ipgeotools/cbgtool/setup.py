import os
import argparse
from pathlib import Path

from src.Preprocesser import Preprocesser
from src.DatasetCreator import DatasetCreator
from src.CBGTool import CBGTool


class CBGLocToolSetup:
    """
    CBG定位工具完整流程调用类
    """
    
    def __init__(self, date=None, limit=1000):
        """
        初始化CBG定位工具设置
        
        :param date: 数据日期，格式为YYYYMMDD
        :param limit: 探针数量限制
        """
        self.date = date
        self.limit = limit
        self.root_path = Path(__file__).resolve().parent
        
    def check_environment(self):
        """
        检查运行环境和必要文件
        """
        print("\n===== 检查运行环境 =====")
        
        # 检查数据目录
        data_dir = self.root_path / "data"
        raw_dir = data_dir / "raw"
        format_dir = data_dir / "format"
        
        for directory in [data_dir, raw_dir, format_dir]:
            if not directory.exists():
                print(f"创建目录: {directory}")
                directory.mkdir(parents=True, exist_ok=True)
        
        # 检查原始数据文件
        if self.date:
            raw_file = raw_dir / f"tmp_ip_anl_geo_ping_{self.date}.csv"
            if not raw_file.exists():
                print(f"警告: 原始数据文件不存在: {raw_file}")
                print("请确保原始数据文件已放置在正确位置")
                return False
        
        return True
        
    def run_preprocesser(self):
        """
        运行数据预处理步骤
        """
        print("\n===== 运行数据预处理 =====")
        if not self.date:
            print("错误: 未指定数据日期，无法生成数据集")
            return False
            
        try:
            preprocesser = Preprocesser(date=self.date)
            preprocesser.run()
            print("数据预处理完成")
            return True
        except Exception as e:
            print(f"数据预处理失败: {e}")
            return False
            
    def run_dataset_creator(self):
        """
        运行数据集创建步骤
        """
        print("\n===== 运行数据集创建 =====")
        try:
            creator = DatasetCreator(limit=self.limit)
            creator.run()
            print("数据集创建完成")
            return True
        except Exception as e:
            print(f"数据集创建失败: {e}")
            return False
            
    def run_cbg_tool(self):
        """
        运行CBG定位工具
        """
        print("\n===== 运行CBG定位工具 =====")
        # try:
        tool = CBGTool(limit=self.limit)
        results = tool.run()
        print("CBG定位工具运行完成")
        
        # 输出结果统计
        print("\n结果统计:")
        print(f"原始GeoPing结果数量: {len(results['result_ori'])}")
        print(f"NCR结果数量: {len(results['result_ncr'])}")
        print(f"NCR-GeoPing结果数量: {len(results['result_ncr_ori'])}")
        
            # return True
        # except Exception as e:
        #     print(f"CBG定位工具运行失败: {e}")
        #     return False
            
    def run_all(self):
        """
        运行完整流程
        """
        
        # 检查环境
        self.check_environment()
        
        # 运行数据预处理
        if self.date:
            self.run_preprocesser()
        else:
            print("未指定数据日期，无法运行数据预处理")
        
        # 运行数据集创建
        self.run_dataset_creator()
        
        # 运行CBG定位工具
        self.run_cbg_tool()


def main():
    """
    主函数，解析命令行参数并运行完整流程
    """
    parser = argparse.ArgumentParser(description="CBG定位工具完整流程")
    
    # 基本参数
    parser.add_argument("--date", "-d", type=str, help="数据日期，格式为YYYYMMDD")
    parser.add_argument("--limit", "-l", type=int, default=1000, help="探针数量限制")
    
    # 命令组，互斥命令
    command_group = parser.add_mutually_exclusive_group(required=True)
    command_group.add_argument("--preprocess", "-p", action="store_true", help="仅运行数据预处理")
    command_group.add_argument("--create", "-c", action="store_true", help="仅运行数据集创建")
    command_group.add_argument("--locate", "-loc", action="store_true", help="仅运行CBG定位工具")
    command_group.add_argument("--auto", "-a", action="store_true", help="自动运行完整流程")
    

    args = parser.parse_args()
    
    setup = CBGLocToolSetup(date=args.date, limit=args.limit)
    
    # 检查环境
    setup.check_environment()
    
    # 根据命令选择运行模式
    if args.preprocess:
        # 仅运行数据预处理
        setup.run_preprocesser()
    elif args.create:
        # 仅运行数据集创建
        setup.run_dataset_creator()
    elif args.locate:
        # 仅运行CBG定位工具
        setup.run_cbg_tool()
    elif args.auto:
        # 自动运行完整流程
        setup.run_all()
    



if __name__ == "__main__":
    main() 