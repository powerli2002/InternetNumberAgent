"""
数据预处理器，将原始数据转化为项目可处理数据
源文件为：
tmp_ip_anl_geo_ping_{date}.csv

被探测ip、探测点ip、时延 （ms） 、ttl、探测点region、序号 （按时延排序） 无意义，需要自己生成
anchor_id, probe_id, rtt, ttl, region, label

被探测ip、探测点ip 所在的 城市&经纬度: 通过ipinfo api获得

每个被探测ip ，都分别在 美国的10个不同的州的某个城市 进行了探测
"""

import pandas as pd
import requests
import json
from collections import defaultdict
from pathlib import Path
import ipinfo
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.utils.logging_manager import logger

class Preprocesser:
    def __init__(self, date, access_token='d4eee514558608'):

        self.ROOT_PATH = Path(__file__).resolve().parent.parent

            
        self.DATA_DIR = self.ROOT_PATH / "data"
        self.date = date
        self.access_token = access_token
        self.dataset_raw = None
        self.anchors_ids_dict = None
        self.probes_ids_dict = None
        
    def load_raw_data(self):
        """加载原始数据文件"""
        raw_file = self.DATA_DIR / "raw" / f"tmp_ip_anl_geo_ping_{self.date}.csv"
        logger.info(f"加载原始数据文件: {raw_file}")
        self.dataset_raw = pd.read_csv(raw_file, header=None)
        self.dataset_raw.columns = ['anchor_ad', 'probe_ad', 'rtt', 'ttl', 'region', 'label']
        return self.dataset_raw
        
    def gen_id(self):
        """生成探测点和被探测点的ID映射"""
        logger.info("生成探测点和被探测点的ID映射")
        # 被探测点id
        anchors_ids = self.dataset_raw['anchor_ad'].unique().tolist()
        self.anchors_ids_dict = {anchors_ids[i]: i for i in range(len(anchors_ids))}
        
        probes_ids = self.dataset_raw['probe_ad'].unique().tolist()
        self.probes_ids_dict = {probes_ids[i]: i for i in range(len(probes_ids))}
        
        logger.debug(f"生成的被探测点ID数量: {len(self.anchors_ids_dict)}")
        logger.debug(f"生成的探测点ID数量: {len(self.probes_ids_dict)}")
        
        return self.anchors_ids_dict, self.probes_ids_dict

    def ipinfo_api(self, ipv4_address):
        """通过ipinfo API获取IP地址的地理位置信息"""
        try:
            handler = ipinfo.getHandler(self.access_token)
            details = handler.getDetails(ipv4_address)
            loc = details.loc
            longtitude = loc.split(',')[0]
            longtitude = float(longtitude)
            longtitude = round(longtitude, 4)

            langtitude = loc.split(',')[1]
            langtitude = float(langtitude)
            langtitude = round(langtitude, 4)

            country_code = details.country
            
            # 直接检查all字典中是否有asn字段
            if 'asn' in details.all:
                if isinstance(details.all['asn'], dict) and 'asn' in details.all['asn']:
                    asn_v4 = details.all['asn']['asn'].replace('AS', '')
                else:
                    asn_v4 = 'unknown'
            else:
                asn_v4 = 'unknown'
            
            return longtitude, langtitude, details.city, country_code, asn_v4
        except Exception as e:
            logger.error(f"获取IP {ipv4_address} 的地理位置信息失败: {e}")
            raise ValueError(e)
            
    def gen_probes_anchors_json(self):
        """生成probes.json和anchors.json文件"""
        if self.anchors_ids_dict is None or self.probes_ids_dict is None:
            self.gen_id()
        
        # id添加到 dataset_raw 中
        self.dataset_raw['anchor_id'] = self.dataset_raw['anchor_ad'].map(self.anchors_ids_dict)
        self.dataset_raw['probe_id'] = self.dataset_raw['probe_ad'].map(self.probes_ids_dict)

        # 获取地理位置信息
        anchor_geos = {}
        probe_geos = {}

        logger.info("开始获取探测点地理位置信息...")
        for ip in self.probes_ids_dict.keys():
            lon, lat, city, country_code, asn_v4 = self.ipinfo_api(ip)
            probe_geos[ip] = {
                "address_v4": ip,
                "city": city, 
                "geometry": {"type": "Point", "coordinates": [lon, lat]}, 
                "id": self.probes_ids_dict[ip], 
                "is_anchor": False, 
                "country_code": country_code,
                "asn_v4": asn_v4
            }
        logger.info("探测点地理位置信息获取完成")

        logger.info("开始获取被探测点地理位置信息...")
        for ip in self.anchors_ids_dict.keys():
            lon, lat, city, country_code, asn_v4 = self.ipinfo_api(ip)
            anchor_geos[ip] = {
                "address_v4": ip,
                "city": city, 
                "geometry": {"type": "Point", "coordinates": [lon, lat]}, 
                "id": self.anchors_ids_dict[ip], 
                "is_anchor": True, 
                "country_code": country_code,
                "asn_v4": asn_v4
            }
        logger.info("被探测点地理位置信息获取完成")

        # 创建输出目录
        output_dir = self.DATA_DIR / "format"
        output_dir.mkdir(exist_ok=True, parents=True)
        
        # 写入文件
        with open(output_dir / "user_probes.json", "w") as f:
            json.dump(list(probe_geos.values()), f, indent=4)

        with open(output_dir / "user_anchors.json", "w") as f:
            json.dump(list(anchor_geos.values()), f, indent=4)

        logger.info("成功生成 user_anchors.json 和 user_probes.json 文件")

    def gen_ping_to_anchors_csv(self):
        """生成ping_to_anchors.csv文件"""
        if self.anchors_ids_dict is None or self.probes_ids_dict is None:
            self.gen_id()
        
        # id添加到 dataset_raw 中
        self.dataset_raw['anchor_id'] = self.dataset_raw['anchor_ad'].map(self.anchors_ids_dict)
        self.dataset_raw['probe_id'] = self.dataset_raw['probe_ad'].map(self.probes_ids_dict)

        logger.info("开始生成 ping_to_anchors.csv 文件...")
        # 生成 ping_to_anchors.csv
        ping_data = defaultdict(lambda: defaultdict(list))
        
        for _, row in self.dataset_raw.iterrows():
            dst = row['anchor_ad']
            src = row['probe_ad']
            prb_id = row['probe_id']
            min_rtt = row['rtt']
            ping_data[src][dst].append((prb_id, min_rtt))
        
        # 转换为DataFrame
        rows = []
        for src, dsts in ping_data.items():
            for dst, prb_rtts in dsts.items():
                for prb_id, min_rtt in prb_rtts:
                    rows.append({"src": src, "dst": dst, "prb_id": prb_id, "min_rtt": min_rtt})
        
        # 创建输出目录
        output_dir = self.DATA_DIR / "format"
        output_dir.mkdir(exist_ok=True, parents=True)
        
        ping_df = pd.DataFrame(rows)
        ping_df.to_csv(output_dir / "ping_to_anchors.csv", index=False)
        logger.info("成功生成 ping_to_anchors.csv 文件")
        
    def run(self):
        """运行完整的数据预处理流程"""
        logger.info("开始运行数据预处理流程...")
        self.load_raw_data()
        self.gen_probes_anchors_json()
        self.gen_ping_to_anchors_csv()
        logger.info("数据预处理流程完成")
        return {
            "anchors_ids_dict": self.anchors_ids_dict,
            "probes_ids_dict": self.probes_ids_dict,
            "dataset_raw": self.dataset_raw
        }


if __name__ == "__main__":
    preprocesser = Preprocesser(date="20241213")
    preprocesser.run()