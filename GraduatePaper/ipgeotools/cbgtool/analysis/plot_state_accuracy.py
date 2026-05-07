import json
import statistics
import matplotlib.pyplot as plt
import numpy as np
import os
import glob
from collections import defaultdict
import seaborn as sns

# 州名中英文对照表
STATE_NAME_TRANSLATION = {
    "佐治亚州": "Georgia",
    "伊利诺伊州": "Illinois", 
    "犹他州": "Utah",
    "佛罗里达州": "Florida",
    "纽约州": "New York",
    "密苏里州": "Missouri",
    "威斯康星州": "Wisconsin",
    "密西西比州": "Mississippi",
    "爱达荷州": "Idaho",
    "加利福尼亚州": "California",
    "德克萨斯州": "Texas",
    "俄亥俄州": "Ohio",
    "宾夕法尼亚州": "Pennsylvania",
    "北卡罗来纳州": "North Carolina",
    "密歇根州": "Michigan",
    "新泽西州": "New Jersey",
    "弗吉尼亚州": "Virginia",
    "华盛顿州": "Washington",
    "马萨诸塞州": "Massachusetts",
    "亚利桑那州": "Arizona",
    "田纳西州": "Tennessee",
    "印第安纳州": "Indiana",
    "马里兰州": "Maryland",
    "科罗拉多州": "Colorado",
    "明尼苏达州": "Minnesota",
    "阿拉巴马州": "Alabama",
    "路易斯安那州": "Louisiana",
    "肯塔基州": "Kentucky",
    "俄勒冈州": "Oregon",
    "康涅狄格州": "Connecticut",
    "爱荷华州": "Iowa",
    "阿肯色州": "Arkansas",
    "堪萨斯州": "Kansas",
    "内华达州": "Nevada",
    "南卡罗来纳州": "South Carolina",
    "西弗吉尼亚州": "West Virginia",
    "内布拉斯加州": "Nebraska",
    "新墨西哥州": "New Mexico",
    "蒙大拿州": "Montana",
    "北达科他州": "North Dakota",
    "南达科他州": "South Dakota",
    "怀俄明州": "Wyoming",
    "特拉华州": "Delaware",
    "罗德岛州": "Rhode Island",
    "夏威夷州": "Hawaii",
    "阿拉斯加州": "Alaska",
    "佛蒙特州": "Vermont",
    "新罕布什尔州": "New Hampshire",
    "缅因州": "Maine"
}

def translate_state_name(chinese_name):
    """将中文州名翻译为英文"""
    return STATE_NAME_TRANSLATION.get(chinese_name, chinese_name)

def get_result_files(data_dir):
    """获取data/output目录下所有的结果文件"""
    output_dir = os.path.join(data_dir, "output")
    pattern = os.path.join(output_dir, "user_result_loc_*.json")
    
    result_files = {}
    for file_path in glob.glob(pattern):
        filename = os.path.basename(file_path)
        method_name = filename.replace("user_result_loc_", "").replace(".json", "")
        result_files[method_name] = file_path
    
    return result_files

def evaluate_method_state_accuracy(result_file_path, method_name):
    """评估单个方法的各州准确率"""
    # 检查是否为t3文件
    is_t3_file = method_name.endswith('t3')
    
    # 加载数据
    with open(result_file_path, 'r') as f:
        data = json.load(f)
    
    # 按州统计准确率
    state_accuracy = defaultdict(lambda: {"total": 0, "correct": 0})
    
    # t3文件的成功状态统计
    if is_t3_file:
        success_state_accuracy = defaultdict(lambda: {"total": 0, "correct": 0})
    
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
        
        # 提取州信息
        try:
            state = real_address.split('/')[0].strip()
            state_accuracy[state]["total"] += 1
        except IndexError:
            continue
        
        # 检查地址是否匹配
        is_address_correct = (pre_address == real_address)
        if is_address_correct:
            state_accuracy[state]["correct"] += 1
        
        # t3文件：单独统计成功状态的数据
        if is_t3_file and len(entry) == 8 and status == "success":
            success_state_accuracy[state]["total"] += 1
            if is_address_correct:
                success_state_accuracy[state]["correct"] += 1
    
    # 计算各州准确率
    state_rates = {}
    for state, counts in state_accuracy.items():
        if counts["total"] > 0:
            accuracy_rate = (counts["correct"] / counts["total"]) * 100
            state_rates[state] = {
                "accuracy_rate": accuracy_rate,
                "total": counts["total"],
                "correct": counts["correct"]
            }
    
    # 如果是t3文件，也返回成功状态的准确率
    result = {"all": state_rates}
    if is_t3_file:
        success_rates = {}
        for state, counts in success_state_accuracy.items():
            if counts["total"] > 0:
                accuracy_rate = (counts["correct"] / counts["total"]) * 100
                success_rates[state] = {
                    "accuracy_rate": accuracy_rate,
                    "total": counts["total"],
                    "correct": counts["correct"]
                }
        result["success"] = success_rates
    
    return result

def collect_all_state_accuracies():
    """收集所有方法的各州准确率数据"""
    data_dir = "/home/lzj/Ali_employ/CBGLocTool/data"
    result_files = get_result_files(data_dir)
    
    all_method_accuracies = {}
    
    # 评估每个方法
    for method, file_path in result_files.items():
        if os.path.exists(file_path):
            print(f"Processing method: {method}")
            state_rates_data = evaluate_method_state_accuracy(file_path, method)
            
            # 存储所有数据的准确率
            all_method_accuracies[method] = state_rates_data["all"]
            
            # 如果是t3文件且有成功数据，添加成功版本
            if "success" in state_rates_data and state_rates_data["success"]:
                success_method_name = f"{method}_success"
                all_method_accuracies[success_method_name] = state_rates_data["success"]
                print(f"  Added success version: {success_method_name}")
    
    return all_method_accuracies

def calculate_average_state_accuracy(all_method_accuracies):
    """计算各州的平均准确率"""
    # 收集所有出现的州
    all_states = set()
    for method_data in all_method_accuracies.values():
        all_states.update(method_data.keys())
    
    # 计算每个州的平均准确率
    state_avg_accuracy = {}
    for state in all_states:
        accuracies = []
        total_samples = 0
        
        for method_data in all_method_accuracies.values():
            if state in method_data:
                accuracies.append(method_data[state]["accuracy_rate"])
                total_samples += method_data[state]["total"]
        
        if accuracies:
            avg_accuracy = statistics.mean(accuracies)
            state_avg_accuracy[state] = {
                "avg_accuracy": avg_accuracy,
                "total_samples": total_samples,
                "method_count": len(accuracies)
            }
    
    return state_avg_accuracy

def get_method_accuracy_ranking(all_method_accuracies):
    """计算各方法的平均准确率并按准确率排序"""
    method_accuracies = {}
    
    for method, state_data in all_method_accuracies.items():
        total_correct = 0
        total_samples = 0
        
        for state, data in state_data.items():
            total_correct += data["correct"]
            total_samples += data["total"]
        
        if total_samples > 0:
            overall_accuracy = (total_correct / total_samples) * 100
            method_accuracies[method] = overall_accuracy
        else:
            method_accuracies[method] = 0
    
    # 按准确率降序排序
    sorted_methods = sorted(method_accuracies.items(), key=lambda x: x[1], reverse=True)
    return [method for method, accuracy in sorted_methods], method_accuracies

def plot_heatmap(all_method_accuracies, top_n=8):
    """绘制热力图显示各州各方法的准确率"""
    
    # 计算各州平均准确率并选择前N个
    state_avg_accuracy = calculate_average_state_accuracy(all_method_accuracies)
    filtered_states = {state: data for state, data in state_avg_accuracy.items() 
                      if data["method_count"] >= 5 and data["total_samples"] >= 10}
    top_states = sorted(filtered_states.items(), 
                       key=lambda x: x[1]["avg_accuracy"], 
                       reverse=True)[:top_n]
    
    print(f"\nSelected top {top_n} states for heatmap:")
    for state, data in top_states:
        english_name = translate_state_name(state)
        print(f"  {english_name}: Average Accuracy {data['avg_accuracy']:.2f}%, Total Samples {data['total_samples']}")
    
    # 使用英文州名
    state_names = [translate_state_name(state) for state, _ in top_states]
    
    # 获取按准确率排序的方法列表
    sorted_methods, method_accuracies = get_method_accuracy_ranking(all_method_accuracies)
    
    print(f"\nMethod ranking by overall accuracy (including t3 success methods):")
    for i, method in enumerate(sorted_methods, 1):
        print(f"  {i}. {method}: {method_accuracies[method]:.2f}%")
    
    # 创建数据矩阵，按排序后的方法顺序
    accuracy_matrix = []
    annotations_matrix = []
    
    for method in sorted_methods:
        method_accuracies_by_state = []
        method_annotations = []
        for state, _ in top_states:
            if state in all_method_accuracies[method]:
                accuracy = all_method_accuracies[method][state]["accuracy_rate"]
                total_samples = all_method_accuracies[method][state]["total"]
                method_accuracies_by_state.append(accuracy)
                method_annotations.append(f"{accuracy:.1f}%\n({total_samples})")
            else:
                # 对于success方法，如果没有数据则显示0而不是NaN
                if method.endswith('_success'):
                    method_accuracies_by_state.append(0.0)
                    method_annotations.append("0.0%\n(0)")
                else:
                    method_accuracies_by_state.append(np.nan)
                    method_annotations.append("")
        accuracy_matrix.append(method_accuracies_by_state)
        annotations_matrix.append(method_annotations)
    
    # 创建热力图
    plt.figure(figsize=(12, 10))  # 增加高度以适应更多方法
    
    # 使用seaborn绘制热力图
    heatmap_data = np.array(accuracy_matrix)
    
    # 创建自定义的注释矩阵
    annotations = np.array(annotations_matrix)
    
    ax = sns.heatmap(heatmap_data, 
                     xticklabels=state_names, 
                     yticklabels=sorted_methods,
                     annot=annotations, 
                     fmt='', 
                     cmap='RdYlBu_r',
                     cbar_kws={'label': 'Accuracy (%)'},
                     annot_kws={'size': 6})  # 减小字体以适应样本数量显示
    
    plt.title(f'State Accuracy Heatmap (Top {top_n} States, Including T3 Success Methods)', fontsize=14, fontweight='bold')
    plt.xlabel('States', fontsize=12)
    plt.ylabel('Methods', fontsize=12)
    plt.xticks(rotation=45, ha='right')
    plt.yticks(rotation=0, fontsize=9)  # 减小Y轴字体
    plt.tight_layout()
    
    # 保存热力图
    heatmap_path = "analysis/results/state_accuracy_heatmap.png"
    plt.savefig(heatmap_path, dpi=300, bbox_inches='tight')
    print(f"\nHeatmap saved to: {heatmap_path}")
    
    plt.show()

def main():
    print("Collecting state accuracy data...")
    
    # 收集所有方法的各州准确率数据
    all_method_accuracies = collect_all_state_accuracies()
    
    print(f"\nProcessed {len(all_method_accuracies)} methods (including t3 success versions)")
    
    # 只绘制热力图
    print("\nGenerating heatmap...")
    plot_heatmap(all_method_accuracies, top_n=8)
    
    # 输出详细统计信息
    print("\nDetailed Statistics:")
    print("="*60)
    
    # 获取按准确率排序的方法和州
    state_avg_accuracy = calculate_average_state_accuracy(all_method_accuracies)
    filtered_states = {state: data for state, data in state_avg_accuracy.items() 
                      if data["method_count"] >= 5 and data["total_samples"] >= 10}
    top_states = sorted(filtered_states.items(), 
                       key=lambda x: x[1]["avg_accuracy"], 
                       reverse=True)[:8]
    
    sorted_methods, _ = get_method_accuracy_ranking(all_method_accuracies)
    
    for i, (state, state_data) in enumerate(top_states):
        english_name = translate_state_name(state)
        print(f"\n{i+1}. {english_name}")
        print(f"   Average Accuracy: {state_data['avg_accuracy']:.2f}%")
        print(f"   Total Samples: {state_data['total_samples']}")
        print(f"   Method Coverage: {state_data['method_count']}")
        
        print("   Method Accuracies:")
        for method in sorted_methods:
            if state in all_method_accuracies[method]:
                acc_data = all_method_accuracies[method][state]
                print(f"     {method}: {acc_data['accuracy_rate']:.2f}% ({acc_data['correct']}/{acc_data['total']})")

if __name__ == "__main__":
    main() 