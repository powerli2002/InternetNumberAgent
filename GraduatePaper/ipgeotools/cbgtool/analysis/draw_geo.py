"""
绘制 
结果中 预测位置和真实位置，两者之间连线
探针probe
的位置

在美国地图上

结果集：
./data/output/user_result_loc_ori.json

探针集：
./data/format/user_probes.json

图片放置在：
./analysis/results/
"""

import json
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import os
import numpy as np

# 创建结果目录
os.makedirs('./analysis/results/', exist_ok=True)

# 加载数据
def load_data():
    # 加载结果数据
    with open('./data/output/user_result_loc_ori_1_3_3.json', 'r', encoding='utf-8') as f:
        results = json.load(f)
    
    # 加载探针数据
    with open('./data/format/user_probes.json', 'r', encoding='utf-8') as f:
        probes = json.load(f)
    
    return results, probes

# 处理结果数据，提取预测位置和实际位置
def process_results(results):
    predicted_locations = []
    actual_locations = []
    
    for item in results:
        if item[2] and len(item[2]) == 2 and item[3] and len(item[3]) == 2:
            # 注意：经纬度在数据中的顺序是[纬度, 经度]，但绘图时需要[经度, 纬度]
            predicted_lon, predicted_lat = item[2]
            actual_lon, actual_lat = item[3]
            
            # 过滤掉无效坐标（有些坐标可能不在美国范围内）
            if -130 < predicted_lon < -60 and 20 < predicted_lat < 50 and -130 < actual_lon < -60 and 20 < actual_lat < 50:
                predicted_locations.append((predicted_lon, predicted_lat))
                actual_locations.append((actual_lon, actual_lat))
    
    return predicted_locations, actual_locations

# 处理探针数据
def process_probes(probes):
    probe_locations = []
    
    for probe in probes:
        if probe['geometry'] and probe['geometry']['coordinates']:
            # 注意：经纬度在数据中的顺序是[纬度, 经度]，但绘图时需要[经度, 纬度]
            lat, lon = probe['geometry']['coordinates']
            probe_locations.append((lon, lat))
    
    return probe_locations

# 绘制地图
def draw_map(predicted_locations, actual_locations, probe_locations):
    # 创建图形和坐标系
    fig = plt.figure(figsize=(15, 10))
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.AlbersEqualArea(central_longitude=-96, central_latitude=37.5))
    
    # 设置地图范围（美国大陆范围）
    ax.set_extent([-125, -66.5, 24, 50], ccrs.PlateCarree())
    
    # 添加地图特征
    ax.add_feature(cfeature.LAND, facecolor='lightgray')
    ax.add_feature(cfeature.OCEAN, facecolor='lightblue')
    ax.add_feature(cfeature.COASTLINE, linewidth=0.5)
    
    # 添加州边界，使用更明显的样式
    states_provinces = cfeature.NaturalEarthFeature(
        category='cultural',
        name='admin_1_states_provinces_lines',
        scale='50m',
        facecolor='none')
    ax.add_feature(states_provinces, edgecolor='gray', linewidth=0.7)
    
    # 添加国家边界
    ax.add_feature(cfeature.BORDERS, linewidth=1.0)
    
    # 绘制预测位置
    if predicted_locations:
        pred_lons, pred_lats = zip(*predicted_locations)
        ax.scatter(pred_lons, pred_lats, c='blue', marker='^', s=50, 
                  label='Predicted Locations', transform=ccrs.PlateCarree(), alpha=0.7)
    
    # 绘制实际位置
    if actual_locations:
        actual_lons, actual_lats = zip(*actual_locations)
        ax.scatter(actual_lons, actual_lats, c='red', marker='o', s=30, 
                  label='Actual Locations', transform=ccrs.PlateCarree(), alpha=0.7)
    
    # 绘制探针，增大显示大小
    if probe_locations:
        probe_lons, probe_lats = zip(*probe_locations)
        ax.scatter(probe_lons, probe_lats, c='green', marker='s', s=100, 
                  label='Probes', transform=ccrs.PlateCarree(), alpha=0.8, 
                  edgecolor='black', linewidth=1)
    
    # 绘制预测位置到实际位置的连线
    for i in range(min(len(predicted_locations), len(actual_locations))):
        ax.plot([predicted_locations[i][0], actual_locations[i][0]], 
                [predicted_locations[i][1], actual_locations[i][1]], 
                color='gray', linewidth=0.5, alpha=0.3, transform=ccrs.PlateCarree())
    
    # 添加图例
    ax.legend(loc='lower left')
    
    # 添加标题
    plt.title('Geographic Distribution of Predicted vs Actual Locations and Probes in the US')
    
    # 保存图片，只保存PNG格式
    plt.savefig('./analysis/results/geo_distribution.png', dpi=300, bbox_inches='tight')
    
    print(f"图片已保存至 './analysis/results/geo_distribution.png'")

# 主函数
def main():
    # 加载数据
    results, probes = load_data()
    
    # 处理数据
    predicted_locations, actual_locations = process_results(results)
    probe_locations = process_probes(probes)
    
    # 打印数据统计
    print(f"有效预测位置数量: {len(predicted_locations)}")
    print(f"有效实际位置数量: {len(actual_locations)}")
    print(f"探针数量: {len(probe_locations)}")
    
    # 绘制地图
    draw_map(predicted_locations, actual_locations, probe_locations)

if __name__ == "__main__":
    main()



