import json
import statistics
import os
import glob
from collections import defaultdict, Counter

def evaluate_localization_results(result_file_path, method_name):
    """
    评估定位结果并生成报告
    
    参数:
        result_file_path: 结果文件路径
        method_name: 方法名称
    """
    # 检查是否为t3文件
    is_t3_file = method_name.endswith('t3')
    
    # 加载数据
    with open(result_file_path, 'r') as f:
        data = json.load(f)
    
    # 初始化变量
    total_entries = 0
    correct_entries = 0
    distance_list = []
    
    # t3文件专用变量
    if is_t3_file:
        success_entries = 0
        success_correct_entries = 0
        success_distance_list = []
        success_state_accuracy = defaultdict(lambda: {"total": 0, "correct": 0})
    
    # 定义距离范围和计数
    distance_ranges = {
        "0-100": {"total": 0, "correct": 0, "locations": []},
        "100-200": {"total": 0, "correct": 0, "locations": []},
        "200-500": {"total": 0, "correct": 0, "locations": []},
        "500-2000": {"total": 0, "correct": 0, "locations": []},
        "2000+": {"total": 0, "correct": 0, "locations": []}
    }
    
    # 按州统计准确率
    state_accuracy = defaultdict(lambda: {"total": 0, "correct": 0})
    
    # 处理每个数据条目
    for entry in data:
        # 根据文件类型解析数据
        if is_t3_file and len(entry) == 8:
            ip, error_km, pre_coords, real_coords, delta, pre_address, real_address, status = entry
        elif len(entry) == 6:
            ip, error_km, pre_coords, real_coords, pre_address, real_address = entry
        elif len(entry) == 7:
            ip, error_km, pre_coords, real_coords, delta, pre_address, real_address = entry
        else:
            continue
        
        # 跳过缺少必要字段的条目
        if None in [error_km, pre_coords, real_coords, real_address]:
            continue
        
        if None in [pre_address]:
            pre_address = "Address not found"
        
        total_entries += 1
        
        # 提取州信息
        try:
            state = real_address.split('/')[0].strip()
            state_accuracy[state]["total"] += 1
        except IndexError:
            continue
        
        # 检查地址是否匹配
        is_address_correct = (pre_address == real_address)
        if is_address_correct:
            correct_entries += 1
            if state in state_accuracy:
                state_accuracy[state]["correct"] += 1
        
        # t3文件特殊处理：当status为"success"时的统计
        if is_t3_file and len(entry) == 8:
            if status == "success":
                success_entries += 1
                success_distance_list.append(error_km)
                success_state_accuracy[state]["total"] += 1
                if is_address_correct:
                    success_correct_entries += 1
                    success_state_accuracy[state]["correct"] += 1
        
        # 记录误差距离
        distance_list.append(error_km)
        
        # 确定该条目属于哪个距离范围
        if 0 <= error_km < 100:
            distance_ranges["0-100"]["total"] += 1
            if is_address_correct:
                distance_ranges["0-100"]["correct"] += 1
            distance_ranges["0-100"]["locations"].append((real_address, real_coords))
        elif 100 <= error_km < 200:
            distance_ranges["100-200"]["total"] += 1
            if is_address_correct:
                distance_ranges["100-200"]["correct"] += 1
            distance_ranges["100-200"]["locations"].append((real_address, real_coords))
        elif 200 <= error_km < 500:
            distance_ranges["200-500"]["total"] += 1
            if is_address_correct:
                distance_ranges["200-500"]["correct"] += 1
            distance_ranges["200-500"]["locations"].append((real_address, real_coords))
        elif 500 <= error_km < 2000:
            distance_ranges["500-2000"]["total"] += 1
            if is_address_correct:
                distance_ranges["500-2000"]["correct"] += 1
            distance_ranges["500-2000"]["locations"].append((real_address, real_coords))
        else:
            distance_ranges["2000+"]["total"] += 1
            if is_address_correct:
                distance_ranges["2000+"]["correct"] += 1
            distance_ranges["2000+"]["locations"].append((real_address, real_coords))
    
    # 计算准确率
    accuracy_rate = (correct_entries / total_entries) * 100 if total_entries > 0 else 0
    
    # 计算距离的平均值和中位数
    average_distance = statistics.mean(distance_list) if distance_list else 0
    median_distance = statistics.median(distance_list) if distance_list else 0
    
    # 输出结果
    result_summary = {
        "method": method_name,
        "accuracy_rate": accuracy_rate,
        "average_distance": average_distance,
        "median_distance": median_distance,
        "total_entries": total_entries,
        "correct_entries": correct_entries,
        "distance_ranges": distance_ranges,
        "state_accuracy": state_accuracy
    }
    
    # t3文件的success统计
    if is_t3_file:
        success_accuracy_rate = (success_correct_entries / success_entries) * 100 if success_entries > 0 else 0
        success_average_distance = statistics.mean(success_distance_list) if success_distance_list else 0
        success_median_distance = statistics.median(success_distance_list) if success_distance_list else 0
        
        result_summary["success_entries"] = success_entries
        result_summary["success_correct_entries"] = success_correct_entries
        result_summary["success_accuracy_rate"] = success_accuracy_rate
        result_summary["success_average_distance"] = success_average_distance
        result_summary["success_median_distance"] = success_median_distance
        result_summary["success_state_accuracy"] = success_state_accuracy
    
    print(f"\n{'='*50}")
    print(f"方法: {method_name}")
    print(f"{'='*50}")
    print(f"总体准确率: {accuracy_rate:.2f}%")
    print(f"平均距离误差: {average_distance:.2f} km")
    print(f"中位数距离误差: {median_distance:.2f} km")
    print(f"总条目数: {total_entries}")
    print(f"正确条目数: {correct_entries}")
    
    # t3文件特殊输出
    if is_t3_file:
        print(f"\n--- t3文件特殊统计 (status='success') ---")
        print(f"Success条目数: {success_entries}")
        print(f"Success正确条目数: {success_correct_entries}")
        print(f"Success准确率: {success_accuracy_rate:.2f}%")
        print(f"Success平均距离误差: {success_average_distance:.2f} km")
        print(f"Success中位数距离误差: {success_median_distance:.2f} km")
        
        # Success状态下的州准确率
        analyze_success_state_accuracy(success_state_accuracy)
    
    # 按州分析准确率
    analyze_state_accuracy(state_accuracy)
    
    # 分析城市特征
    analyze_city_features(distance_ranges)
    
    return result_summary

def analyze_success_state_accuracy(success_state_accuracy):
    """分析t3文件中status='success'条目的各州准确率"""
    print("\n各州Success准确率排序（按准确率降序）:")
    sorted_success_accuracies = sorted(success_state_accuracy.items(), 
                                     key=lambda item: (item[1]["correct"] / item[1]["total"]) 
                                     if item[1]["total"] > 0 else 0, 
                                     reverse=True)
    
    for state, counts in sorted_success_accuracies:
        total = counts["total"]
        correct = counts["correct"]
        accuracy_rate = (correct / total) * 100 if total > 0 else 0
        print(f"  {state}: {accuracy_rate:.2f}% (总数: {total}, 正确: {correct})")

def extract_features(range_data):
    """提取特定距离范围内的城市特征"""
    locations = range_data["locations"]
    city_counter = Counter(address.split('/')[0].strip() for address, coords in locations)
    return city_counter

def analyze_city_features(distance_ranges):
    """分析不同距离范围内的城市特征"""
    range_0_100_cities = extract_features(distance_ranges["0-100"])
    range_100_200_cities = extract_features(distance_ranges["100-200"])
    
    print("\n0-100公里范围内的城市分布:")
    for city, count in range_0_100_cities.most_common(10):
        print(f"  {city}: {count}")
    
    print("\n100-200公里范围内的城市分布:")
    for city, count in range_100_200_cities.most_common(10):
        print(f"  {city}: {count}")

def analyze_state_accuracy(state_accuracy):
    """分析各州的准确率"""
    print("\n各州准确率排序（按准确率降序）:")
    sorted_state_accuracies = sorted(state_accuracy.items(), 
                                    key=lambda item: (item[1]["correct"] / item[1]["total"]) 
                                    if item[1]["total"] > 0 else 0, 
                                    reverse=True)
    
    for state, counts in sorted_state_accuracies:
        total = counts["total"]
        correct = counts["correct"]
        accuracy_rate = (correct / total) * 100 if total > 0 else 0
        print(f"  {state}: {accuracy_rate:.2f}% (总数: {total}, 正确: {correct})")

def get_result_files(data_dir):
    """
    获取data/output目录下所有的结果文件
    
    参数:
        data_dir: 数据目录路径
    
    返回:
        包含文件路径和方法名的字典
    """
    output_dir = os.path.join(data_dir, "output")
    pattern = os.path.join(output_dir, "user_result_loc_*.json")
    
    result_files = {}
    for file_path in glob.glob(pattern):
        filename = os.path.basename(file_path)
        # 从文件名中提取方法名，去掉前缀和后缀
        method_name = filename.replace("user_result_loc_", "").replace(".json", "")
        result_files[method_name] = file_path
    
    return result_files

def main():
    # 使用绝对路径
    data_dir = "/home/lzj/Ali_employ/CBGLocTool/data"
    
    # 自动获取所有结果文件
    result_files = get_result_files(data_dir)
    
    if not result_files:
        print("在 data/output 目录下未找到任何结果文件")
        return
    
    print(f"找到 {len(result_files)} 个结果文件:")
    for method in result_files.keys():
        print(f"  - {method}")
    
    # 存储所有方法的结果汇总
    all_results = []
    
    # 评估每个结果文件
    for method, file_path in result_files.items():
        if os.path.exists(file_path):
            result_summary = evaluate_localization_results(file_path, method)
            all_results.append(result_summary)
        else:
            print(f"文件不存在: {file_path}")
    
    # 生成汇总报告
    print(f"\n{'='*80}")
    print("所有方法准确率汇总")
    print(f"{'='*80}")
    print(f"{'方法名':<25} {'准确率':<10} {'平均误差(km)':<12} {'中位数误差(km)':<15} {'总数':<8}")
    print(f"{'-'*80}")
    
    # 按准确率排序
    all_results.sort(key=lambda x: x["accuracy_rate"], reverse=True)
    
    for result in all_results:
        print(f"{result['method']:<25} {result['accuracy_rate']:<10.2f} {result['average_distance']:<12.2f} {result['median_distance']:<15.2f} {result['total_entries']:<8}")
    
    # t3文件的Success准确率汇总
    t3_results = [r for r in all_results if r['method'].endswith('t3')]
    if t3_results:
        print(f"\n{'='*95}")
        print("t3文件Success状态准确率汇总")
        print(f"{'='*95}")
        print(f"{'方法名':<25} {'Success准确率':<15} {'Success平均误差':<15} {'Success中位数误差':<18} {'Success总数':<12}")
        print(f"{'-'*95}")
        
        t3_results.sort(key=lambda x: x.get("success_accuracy_rate", 0), reverse=True)
        
        for result in t3_results:
            success_rate = result.get("success_accuracy_rate", 0)
            success_avg_distance = result.get("success_average_distance", 0)
            success_median_distance = result.get("success_median_distance", 0)
            success_total = result.get("success_entries", 0)
            print(f"{result['method']:<25} {success_rate:<15.2f} {success_avg_distance:<15.2f} {success_median_distance:<18.2f} {success_total:<12}")

if __name__ == "__main__":
    main()
