# 分析不同日期之间的probes和anchors经纬度差异
# 注意：日期前后的经纬度坐标顺序是相反的

import json
import os

def load_json_file(file_path):
    """加载JSON文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        print(f"错误：文件 {file_path} 未找到。")
        return None
    except json.JSONDecodeError:
        print(f"错误：文件 {file_path} 不是有效的JSON格式。")
        return None

def compare_coords(coord1, coord2):
    """比较两个坐标是否一致，考虑坐标可能是反序的情况"""
    # 如果两者都是None或空列表，认为相等
    if (coord1 is None or len(coord1) == 0) and (coord2 is None or len(coord2) == 0):
        return True
    
    # 如果只有一个是None，认为不等
    if coord1 is None or coord2 is None or len(coord1) != 2 or len(coord2) != 2:
        return False
    
    # 检查正序是否一致
    if coord1[0] == coord2[0] and coord1[1] == coord2[1]:
        return True
    
    # 检查反序是否一致
    if coord1[0] == coord2[1] and coord1[1] == coord2[0]:
        return True
    
    return False

def analyze_probes_differences(old_probes_file, new_probes_file):
    """分析不同日期probes文件的差异，计算经纬度不一致的数量和比例"""
    old_probes = load_json_file(old_probes_file)
    new_probes = load_json_file(new_probes_file)
    
    if old_probes is None or new_probes is None:
        return {"error": "无法加载probes文件"}
    
    # 提取probes的IP和位置信息，使用address_v4作为主键
    # 仅考虑is_anchor为false的节点(真正的probes)
    old_probes_map = {}
    new_probes_map = {}
    
    for item in old_probes:
        # 只选择is_anchor为false的节点
        if item.get("is_anchor") == False:
            ip = item.get("address_v4")
            if ip:
                # 正确访问geometry.coordinates
                geometry = item.get("geometry", {})
                coords = geometry.get("coordinates") if geometry else None
                old_probes_map[ip] = {
                    "ip": ip,
                    "coords": coords
                }
    
    for item in new_probes:
        # 只选择is_anchor为false的节点
        if item.get("is_anchor") == False:
            ip = item.get("address_v4")
            if ip:
                # 正确访问geometry.coordinates
                geometry = item.get("geometry", {})
                coords = geometry.get("coordinates") if geometry else None
                new_probes_map[ip] = {
                    "ip": ip,
                    "coords": coords
                }
    
    print(f"有效的旧probes数量(is_anchor=false): {len(old_probes_map)}")
    print(f"有效的新probes数量(is_anchor=false): {len(new_probes_map)}")
    
    # 计算共同存在的probes和经纬度不一致的probes
    common_ips = set(old_probes_map.keys()) & set(new_probes_map.keys())
    print(f"共同存在的probes数量(is_anchor=false): {len(common_ips)}")
    
    coords_different_count = 0
    
    for ip in common_ips:
        old_coords = old_probes_map[ip].get("coords")
        new_coords = new_probes_map[ip].get("coords")
        
        # 检查并打印坐标样本，便于调试
        if ip in list(common_ips)[:3]:
            print(f"Debug - IP={ip}: 旧坐标={old_coords}, 新坐标={new_coords}")
        
        if not compare_coords(old_coords, new_coords):
            coords_different_count += 1
            if coords_different_count <= 3:  # 只打印前3个不一致的例子
                print(f"探测点坐标不一致: IP={ip}, 旧坐标={old_coords}, 新坐标={new_coords}")
    
    # 计算差异比例
    total_common = len(common_ips)
    coords_different_ratio = coords_different_count / total_common if total_common > 0 else 0
    
    return {
        "total_probes_old": len(old_probes_map),
        "total_probes_new": len(new_probes_map),
        "common_probes": total_common,
        "coords_different": coords_different_count,
        "coords_different_ratio": coords_different_ratio
    }

def main():
    # 结果文件路径
    result_file1 = './data/old_data/user_result_loc_ori_0425.json'
    result_file2 = './data/output/user_result_loc_ori.json'
    
    # probes文件路径
    probes_file1 = './data/old_data/user_probes_and_anchors_0425.json'
    probes_file2 = './data/format/user_probes_and_anchors.json'

    # 加载结果数据
    data1 = load_json_file(result_file1)
    data2 = load_json_file(result_file2)

    if data1 is None or data2 is None:
        print("无法加载结果数据文件")
        return

    # 检查数据格式
    print(f"旧数据包含 {len(data1)} 条记录")
    print(f"新数据包含 {len(data2)} 条记录")

    # 将数据转换为以IP为键的字典
    # 原始列表格式：[IP地址, 分数值, [预测经度,纬度], [真实经度,纬度], null, 预测位置名称, 真实位置名称]
    data1_map = {}
    for item in data1:
        if isinstance(item, list) and len(item) >= 7:
            ip = item[0]  # IP地址作为主键
            data1_map[ip] = {
                "target_ip": ip,
                "pred_coords": item[2] if len(item) > 2 else None,
                "real_coords": item[3] if len(item) > 3 else None
            }
    
    data2_map = {}
    for item in data2:
        if isinstance(item, list) and len(item) >= 7:
            ip = item[0]  # IP地址作为主键
            data2_map[ip] = {
                "target_ip": ip,
                "pred_coords": item[2] if len(item) > 2 else None,
                "real_coords": item[3] if len(item) > 3 else None
            }

    # 获取共同存在的IP
    common_ips = set(data1_map.keys()) & set(data2_map.keys())
    print(f"两个结果文件共同存在的IP数量: {len(common_ips)}")
    
    if len(common_ips) == 0:
        print("错误: 两个结果文件没有共同的IP地址!")
        return
    
    # 统计真实值和预测值经纬度差异
    real_coords_diff_count = 0
    pred_coords_diff_count = 0
    
    for ip in common_ips:
        item1 = data1_map.get(ip)
        item2 = data2_map.get(ip)
        
        # 比较真实坐标，考虑可能是反序的情况
        if not compare_coords(item1.get('real_coords'), item2.get('real_coords')):
            real_coords_diff_count += 1
            if real_coords_diff_count <= 3:  # 只打印前3个不一致的例子
                print(f"真实坐标不一致: IP={ip}, 旧坐标={item1.get('real_coords')}, 新坐标={item2.get('real_coords')}")
        
        # 比较预测坐标，考虑可能是反序的情况
        if not compare_coords(item1.get('pred_coords'), item2.get('pred_coords')):
            pred_coords_diff_count += 1
            if pred_coords_diff_count <= 3:  # 只打印前3个不一致的例子
                print(f"预测坐标不一致: IP={ip}, 旧坐标={item1.get('pred_coords')}, 新坐标={item2.get('pred_coords')}")
    
    # 计算比例
    total_common_anchors = len(common_ips)
    real_coords_diff_ratio = real_coords_diff_count / total_common_anchors if total_common_anchors > 0 else 0
    pred_coords_diff_ratio = pred_coords_diff_count / total_common_anchors if total_common_anchors > 0 else 0
    
    # 分析probes差异
    print("\n开始分析探测点(Probes)差异...")
    probe_differences = analyze_probes_differences(probes_file1, probes_file2)
    
    # 打印详细的统计结果
    print("\n--- Probes经纬度差异统计 ---")
    print(f"旧数据中probe总数: {probe_differences.get('total_probes_old', 0)}")
    print(f"新数据中probe总数: {probe_differences.get('total_probes_new', 0)}")
    print(f"两个日期共同存在的probes数量: {probe_differences.get('common_probes', 0)}")
    print(f"经纬度不一致的probes数量: {probe_differences.get('coords_different', 0)}")
    print(f"经纬度不一致的probes比例: {probe_differences.get('coords_different_ratio', 0):.2%}")
    
    print("\n--- Anchors真实值经纬度差异统计 ---")
    print(f"两个日期共同存在的anchors数量: {total_common_anchors}")
    print(f"真实经纬度不一致的anchors数量: {real_coords_diff_count}")
    print(f"真实经纬度不一致的anchors比例: {real_coords_diff_ratio:.2%}")
    
    print("\n--- Anchors预测值经纬度差异统计 ---")
    print(f"预测经纬度不一致的anchors数量: {pred_coords_diff_count}")
    print(f"预测经纬度不一致的anchors比例: {pred_coords_diff_ratio:.2%}")
    
    # 保存简洁的分析结果
    output_file = 'data/output/eva_ori_two_date_simple_analysis.json'
    simple_results = {
        "probes_difference": probe_differences,
        "anchors_real_coords_different": {
            "count": real_coords_diff_count,
            "ratio": real_coords_diff_ratio
        },
        "anchors_pred_coords_different": {
            "count": pred_coords_diff_count,
            "ratio": pred_coords_diff_ratio
        }
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(simple_results, f, ensure_ascii=False, indent=4)
    
    print(f"\n简化分析结果已保存到 {output_file}")

if __name__ == '__main__':
    main()


