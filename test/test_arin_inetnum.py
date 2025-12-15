# 用来对arin的inetnum的rdap数据来处理
# CIDR,inetnum,netname,descr,country,org,admin-c,tech-c,abuse-c,status,remarks,last-modified,source,hidden

# 处理每一行信息
def json_to_csv_row(entry):
    # 提取cidr
    # 解析 CIDR
    CIDR = None
    for c in entry.get('cidr0_cidrs', []):
        if 'v6prefix' in c.keys():
            cidr = c['v6prefix'] + '/' + str(c['length'])
        elif 'v4prefix' in c.keys():
            cidr = c['v4prefix'] + '/' + str(c['length'])
        else:
            cidr = None

        if CIDR == None:
            CIDR = cidr
        else:
            CIDR += ('|' + cidr)
    # 提取inetnum（IP范围）
    start_ip = entry.get('startAddress', None)
    end_ip = entry.get('endAddress', start_ip)
    if start_ip and end_ip:
        inetnum = f"{start_ip}-{end_ip}"
    else:
        inetnum = None
    # 提取组织信息
    
    org = None
    for entity in entry.get('entities', []):
        if 'registrant' in entity.get('roles', []):
            org = entity.get('handle', None)
            break
    
    # 提取联系人（admin-c/tech-c/abuse-c）
    contacts = {'admin-c': None, 'tech-c': None, 'abuse-c': None}
    # entities = entry.get('entities', [])
    for entities in entry.get('entities', []):
        for entity in entities.get('entities', []):
            if 'administrative' in entity.get('roles', []):
                contacts['admin-c'] = entity.get('handle', None)
            if 'technical' in entity.get('roles', []):
                contacts['tech-c'] = entity.get('handle', None)
            if 'abuse' in entity.get('roles', []):
                contacts['abuse-c'] = entity.get('handle', None)

    if contacts['admin-c'] is None:
        for entity in entry.get('entities', []):
            if 'administrative' in entity.get('roles', []):
                contacts['admin-c'] = entity.get('handle', None)
                break
    if contacts['tech-c'] is None:
        for entity in entry.get('entities', []):
            if 'technical' in entity.get('roles', []):
                contacts['tech-c'] = entity.get('handle', None)
                break
    if contacts['abuse-c'] is None:
        for entity in entry.get('entities', []):
            if 'abuse' in entity.get('roles', []):
                contacts['abuse-c'] = entity.get('handle', None)
                break

    # 提取source
    source = None
    port43 = entry.get('port43', None)
    if port43:
        source = port43.split('.')[1]
    
    # 提取remarks
    remarks = None
    if entry.get('remarks', None):
        for remark in entity.get('remarks', []):
            remarks = remark.get('description', [None])[0]
            break
    else:
        for entities in entry.get('entities', []):
            if 'remarks' in entities:
                for remark in entity.get('remarks', []):
                    remarks = remark.get('description', [None])[0]
                    break
    if remarks is None:    
        for entities in entry.get('entities', []):
            for entity in entities.get('entities', []):
                for remark in entity.get('remarks', []):
                    remarks = remark.get('description', [None])[0]
                    break
    if remarks:
        remarks = remarks.replace("\n", "")
    desrc = remarks

    # 最后修改时间
    last_modified = None
    for event in entry.get('events', []):
        if event.get('eventAction') == 'last changed':
            last_modified = event.get('eventDate', None)
            break
    
    result = {}
    result["CIDR"] = CIDR
    result["inetnum"] = inetnum
    result["netname"] = entry.get('name', None)
    result["descr"] = desrc
    result["country"] = entry.get('country', None)
    result["org"] = org
    result["admin-c"] = contacts["admin-c"]
    result["tech-c"] = contacts["tech-c"]
    result["abuse-c"] = contacts["abuse-c"]
    result["status"] = entry.get('status', [None])[0]
    result["remarks"] = remarks
    result["last-modified"] = last_modified
    result["source"] = source
    result["hidden"] = entry.get('hidden', 'False')

    return result


# 读取文件
import json
import pandas as pd
import os

if __name__ == "__main__":
    data_dir = "/home/lzj/ip_property/data/oss_us_rdap/0225"
    results = []
    count = 0
    for file in os.listdir(data_dir):
        print(f"开始解析{os.path.join(data_dir, file)}")
        with open(os.path.join(data_dir, file), 'r') as f:
            for line in f:
                count +=1
                if count % 10000 == 0:
                    print(f"已经解析了：{count}")
                if line.strip():
                    entry = json.loads(line)
                    record = json_to_csv_row(entry)
                    results.append(record)
        print(f"解析完成{os.path.join(data_dir, file)}")

    data = pd.DataFrame(results)
    # 取出重复行以及cidr为空值的行
    data = data.dropna(subset=['CIDR'])
    data = data.drop_duplicates(subset=["CIDR"], keep="first")
    data.to_csv("/home/back_data/arin_inetnum_whois_info.csv", index=False)
    # data = pd.read_csv("/home/back_data/arin_inetnum_whois_info.csv")