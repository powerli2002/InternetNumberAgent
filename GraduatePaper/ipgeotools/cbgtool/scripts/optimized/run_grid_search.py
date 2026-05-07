"""
CBG和Octant方法的网格搜索主运行脚本

该脚本提供统一的入口来运行CBG delta参数和Octant alpha/beta参数的网格搜索，
支持灵活的参数配置和执行选项。
"""

import argparse
import sys
import os

# 添加项目根目录到路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from scripts.optimized.grid_search_delta import grid_search_delta
from scripts.optimized.grid_search_octant import grid_search_octant


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='CBG和Octant方法的网格搜索工具')
    
    # 基本参数
    parser.add_argument('--data-dir', default='../../data', 
                       help='数据文件目录路径 (默认: ../../data)')
    parser.add_argument('--method', choices=['cbg', 'octant', 'both'], default='both',
                       help='要运行的方法: cbg, octant, 或 both (默认: both)')
    
    # CBG相关参数
    cbg_group = parser.add_argument_group('CBG参数')
    cbg_group.add_argument('--delta-min', type=float, default=0.001,
                          help='CBG delta最小值 (默认: 0.001)')
    cbg_group.add_argument('--delta-max', type=float, default=0.1,
                          help='CBG delta最大值 (默认: 0.1)')
    cbg_group.add_argument('--delta-points', type=int, default=50,
                          help='CBG delta搜索点数 (默认: 50)')
    
    # Octant相关参数
    octant_group = parser.add_argument_group('Octant参数')
    octant_group.add_argument('--alpha-min', type=float, default=1.1,
                             help='Octant alpha最小值 (默认: 1.1)')
    octant_group.add_argument('--alpha-max', type=float, default=2.0,
                             help='Octant alpha最大值 (默认: 2.0)')
    octant_group.add_argument('--beta-min', type=float, default=0.1,
                             help='Octant beta最小值 (默认: 0.1)')
    octant_group.add_argument('--beta-max', type=float, default=0.9,
                             help='Octant beta最大值 (默认: 0.9)')
    octant_group.add_argument('--alpha-points', type=int, default=20,
                             help='Octant alpha搜索点数 (默认: 20)')
    octant_group.add_argument('--beta-points', type=int, default=20,
                             help='Octant beta搜索点数 (默认: 20)')
    octant_group.add_argument('--delta-fixed', type=float, default=0.389474,
                             help='Octant中固定的delta值 (默认: 0.389474)')
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("CBG和Octant方法网格搜索工具")
    print("=" * 80)
    
    # 验证数据目录
    if not os.path.exists(args.data_dir):
        print(f"错误：数据目录 '{args.data_dir}' 不存在！")
        return
    
    # 运行CBG网格搜索
    if args.method in ['cbg', 'both']:
        print(f"\n{'='*60}")
        print("开始CBG Delta参数网格搜索")
        print(f"{'='*60}")
        print(f"搜索范围: [{args.delta_min}, {args.delta_max}]")
        print(f"搜索点数: {args.delta_points}")
        print(f"数据目录: {args.data_dir}")
        
        try:
            grid_search_delta(
                data_dir=args.data_dir,
                delta_min=args.delta_min,
                delta_max=args.delta_max,
                num_points=args.delta_points
            )
            print("✓ CBG网格搜索完成")
        except Exception as e:
            print(f"✗ CBG网格搜索失败: {e}")
            return
    
    # 运行Octant网格搜索
    if args.method in ['octant', 'both']:
        print(f"\n{'='*60}")
        print("开始Octant Alpha-Beta参数网格搜索")
        print(f"{'='*60}")
        print(f"Alpha搜索范围: [{args.alpha_min}, {args.alpha_max}], 点数: {args.alpha_points}")
        print(f"Beta搜索范围: [{args.beta_min}, {args.beta_max}], 点数: {args.beta_points}")
        print(f"固定Delta值: {args.delta_fixed}")
        print(f"总搜索点数: {args.alpha_points * args.beta_points}")
        print(f"数据目录: {args.data_dir}")
        
        try:
            grid_search_octant(
                data_dir=args.data_dir,
                alpha_min=args.alpha_min,
                alpha_max=args.alpha_max,
                beta_min=args.beta_min,
                beta_max=args.beta_max,
                num_points_alpha=args.alpha_points,
                num_points_beta=args.beta_points,
                delta=args.delta_fixed
            )
            print("✓ Octant网格搜索完成")
        except Exception as e:
            print(f"✗ Octant网格搜索失败: {e}")
            return
    
    print(f"\n{'='*80}")
    print("所有网格搜索任务完成！")
    print("结果文件和可视化图表已保存到当前目录。")
    print("详细的实验记录已上传到Weights & Biases。")
    print(f"{'='*80}")


if __name__ == "__main__":
    main() 