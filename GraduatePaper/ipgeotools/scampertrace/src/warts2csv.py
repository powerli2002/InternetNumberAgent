import pandas as pd
import os
import time
import sys


"""
sc_warts2csv  ... .warts > ... .csv

csv:
version;userID;timestamp;src;dst;method;stop;ttl;hopaddr;rtt
scamper.20240920;0;1730945680;172.16.182.102;1.24.200.215;icmp-echo-paris;COMPLETED;1;10.12.172.38;0.498
scamper.20240920;0;1730945680;172.16.182.102;1.24.200.215;icmp-echo-paris;COMPLETED;2;10.12.172.73;2.482
scamper.20240920;0;1730945680;172.16.182.102;1.24.200.215;icmp-echo-paris;COMPLETED;3;11.223.161.137;0.558
scamper.20240920;0;1730945680;172.16.182.102;1.24.200.215;icmp-echo-paris;COMPLETED;4;11.94.128.122;2.086



result:
timestamp,src,public_as,private_as,dst,stop,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,number_*
1730945680,172.16.182.102,4837,64650,1.24.200.215,COMPLETED,10.12.172.38  0.498ms,10.12.172.73  2.482ms,11.223.161.137  0.558ms,11.94.128.122  2.086ms,10.102.41.105  2.213ms,124.160.190.149  2.233ms,124.160.83.5  9.758ms,219.158.96.5  31.941ms,*,*,1.24.200.215  31.812ms,,,,,,,,,,,,,,,,,,,2
1730945679,172.16.182.102,4837,64651,1.24.186.113,COMPLETED,10.12.168.46  0.581ms,*,11.223.161.185  0.388ms,11.94.128.126  1.476ms,10.102.42.33  2.213ms,124.160.190.221  3.382ms,*,219.158.98.213  37.099ms,110.19.3.138  41.536ms,219.159.56.2  41.173ms,1.24.186.113  42.402ms,,,,,,,,,,,,,,,,,,,2
1730945677,172.16.182.102,4837,64659,1.24.121.87,HOPLIMIT,10.12.172.38  0.421ms,10.12.172.73  2.888ms,10.255.101.93  0.347ms,11.94.128.138  1.544ms,10.102.42.53  2.274ms,124.160.190.221  3.456ms,*,*,219.158.123.142  39.163ms,*,1.31.94.42  51.986ms,*,*,*,*,*,*,*,*,*,*,*,*,*,*,*,*,*,*,21

"""

class Warts2Csv:
    def __init__(self):
        pass

    def deal_trace_data(self, trace_result_warts, trace_result_csv, tracetype: str = "unknown"):
        """
        return:
            result:   dict
                {
                    "dst1":{"timestamp":"", "srt":"", "dst":"", "stop":"", "1":"",..., "30":""},
                    ...
                }

            test:    csv dataframe
            timestamp,src,dst,stop,1,2,...30

        """
        trace_data = None
        result = None

        cmd = f"sc_warts2csv {trace_result_warts} > {trace_result_csv}"
        try:
            os.system(cmd)
        except Exception:
            print(f"{cmd} failed...")

        time.sleep(1)

        trace_data = {}
        data = pd.read_csv(trace_result_csv, sep=";", header=None)

        if data.empty:
            print(f"{trace_result_csv} is empty...")
            return
        
        data.columns = ["version", "userID", "timestamp", "src", "dst", "method", "stop", "ttl", "hopaddr", "rtt"]
        data = data[data['version']!= 'version'] 
        for dst, path in data.groupby("dst"):
            record = {}
            tracelog = []
            keep = 1
            maxttl = 0
            ttl_hop = {}
            for index, row in path.iterrows():
                if keep == 1:
                    record["timestamp"] = row["timestamp"]
                    record["src"] = row["src"]
                    record["dst"] = row["dst"]
                    record["stop"] = row["stop"]
                ttl = int(row["ttl"])
                ttl_hop[ttl] = str(row["hopaddr"]) + "  " + str(row["rtt"]) + "ms"
                if row["stop"] == "COMPLETED":
                    maxttl = max(maxttl, ttl)
                keep = keep + 1
            if maxttl == 0:
                maxttl = max(ttl_hop.keys())
            for i in range(1, maxttl+1):
                tracelog.append(ttl_hop.get(i, "*"))
            record["tracelog"] = tracelog
            record["tracetype"] = tracetype
            record["ping_rtt"] = ""
            trace_data[dst] = record
        os.remove(trace_result_csv)
        result = pd.DataFrame(trace_data).T[["timestamp", "src", "dst", "ping_rtt", "stop", "tracetype", "tracelog"]]
        result.to_csv(trace_result_csv, index=False)

    def main(self, trace_result_warts, trace_result_csv, tracetype: str = "unknown"):
        self.deal_trace_data(trace_result_warts, trace_result_csv, tracetype)

if __name__ == "__main__":


    trace_result_warts = "/Users/lizijian/code/BUPT/scampertrace/test_output2.warts"
    trace_result_csv = "/Users/lizijian/code/BUPT/scampertrace/test_output2.csv"
    # merge_csv_path = "/home/traceroute/result/all/middle/Intervals_non_overlapping_result_with_active_ip_random_ip.csv"

    warts2csv = Warts2Csv()
    warts2csv.main(trace_result_warts, trace_result_csv)
