"""
测试优化设置脚本

验证数据加载和优化环境是否正确配置
"""

import sys
import os

# 添加项目根目录到路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from scripts.optimized.utils import (
    load_dataset_from_files,
    get_target_anchors_with_sufficient_probes,
    prepare_cbg_circles_for_target,
    prepare_octant_circles_for_target
)


def test_optimization_setup():
    """测试优化环境设置"""
    
    print("🧪 测试优化环境设置")
    print("=" * 50)
    
    # 数据目录
    data_dir = "/home/lzj/Ali_employ/CBGLocTool/data/format/"
    
    try:
        # 1. 测试数据加载
        print("📂 测试数据加载...")
        probe_data, anchor_data, ping_data = load_dataset_from_files(data_dir)
        
        print(f"✅ 数据加载成功:")
        print(f"   - Probe点(观测点): {len(probe_data)} 个")
        print(f"   - Anchor点(待定位目标): {len(anchor_data)} 个")
        print(f"   - RTT测量数据: {len(ping_data)} 条")
        
        # 2. 测试目标anchor筛选
        print("\n🎯 测试目标anchor筛选...")
        target_anchors = get_target_anchors_with_sufficient_probes(anchor_data, ping_data, min_measurements=3)
        
        print(f"✅ 有足够测量数据的anchor: {len(target_anchors)} 个")
        
        if len(target_anchors) == 0:
            print("❌ 警告：没有符合条件的anchor用于优化！")
            return False
        
        # 3. 测试CBG数据准备
        print("\n🔄 测试CBG数据准备...")
        test_anchor = target_anchors[0]
        test_delta = 0.1
        
        cbg_circles = prepare_cbg_circles_for_target(test_anchor, probe_data, ping_data, test_delta)
        print(f"✅ 为anchor {test_anchor} 准备了 {len(cbg_circles)} 个CBG圆")
        
        # 4. 测试Octant数据准备
        print("\n🌀 测试Octant数据准备...")
        test_alpha, test_beta = 1.3, 0.7
        
        octant_circles = prepare_octant_circles_for_target(
            test_anchor, probe_data, ping_data, test_delta, test_alpha, test_beta
        )
        print(f"✅ 为anchor {test_anchor} 准备了 {len(octant_circles)} 个Octant环")
        
        # 5. 显示样本数据
        print(f"\n📊 样本数据:")
        print(f"   - 测试anchor IP: {test_anchor}")
        print(f"   - 该anchor的坐标: {anchor_data[test_anchor]['lat']:.4f}, {anchor_data[test_anchor]['lon']:.4f}")
        print(f"   - 测试参数: δ={test_delta}, α={test_alpha}, β={test_beta}")
        
        if cbg_circles:
            print(f"   - 第一个CBG圆: probe坐标({cbg_circles[0][0]:.4f}, {cbg_circles[0][1]:.4f}), RTT={cbg_circles[0][2]:.2f}ms")
        
        print(f"\n🎉 优化环境设置测试通过！可以开始运行优化脚本。")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


if __name__ == "__main__":
    success = test_optimization_setup()
    if success:
        print(f"\n✨ 建议运行顺序:")
        print(f"   1. python scripts/optimized/optimize_cbg_delta.py")
        print(f"   2. python scripts/optimized/optimize_octant_ratios.py")
        print(f"   或者直接运行: python scripts/optimized/run_optimization.py")
    else:
        print(f"\n⚠️  请检查数据文件和环境配置") 