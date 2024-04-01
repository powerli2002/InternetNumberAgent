from IPy import IP


def convert_set_to_list(target_dict: dict) -> dict:
    '''
    把 as_dict 中的 set 转换为 list

    Parameters:

        None

    Returns:

        dict: 转换后的 as_dict
    '''
    for key, value in target_dict.items():
        for k, v in value.items():
            if isinstance(v, set):
                target_dict[key][k] = list(v)
    return target_dict


as_dict = {4134: {'descr': '111'}}

# s = 'TABLE_DUMP2|1687392000|B|80.77.16.114|34549|14.16.0.0/12|34549 3257 4134|IGP|80.77.16.114|0|0|3257:6520 3257:8052 3257:30097 3257:50001 3257:54900 3257:54901 34549:100 34549:3257|NAG|'
with open('data/rib.data', 'r') as f:
    for s in f:
        print(s)
        route = s.split('|')
        print(f'route length: {len(route)}')

        path = route[6].split(' ')  # ASPath

        if len(path) > 1:
            prefix = route[5]   # 路由IP前缀
            prefix_version = IP(prefix).version()  # 路由IP版本
            path_pairs = zip(path, path[1:])  # 前一个asn与后一个asn组成pair
            print(prefix_version)

            # 确认上下游关系和 peer 关系
            for pair in path_pairs:
                if pair[0] == pair[1]:
                    continue

                try:
                    pre, after = int(pair[0].strip()), int(pair[1].strip())
                except:
                    continue

                if prefix_version == 4:
                    # (IPv4)在 AS 字典中找到 AS pair 中的两个 AS，确认其上下游关系和 peer 关系
                    if as_dict.get(after) is not None:
                        as_dict[after].setdefault("v4Upstream", set()).add(pre)
                        as_dict[after].setdefault("v4Peer", set()).add(pre)
                    if as_dict.get(pre) is not None:
                        as_dict[pre].setdefault("v4Downstream", set()).add(after)
                        as_dict[pre].setdefault("v4Peer", set()).add(after)
                if prefix_version == 6:
                    # (IPv6)在 AS 字典中找到 AS pair 中的两个 AS，确认其上下游关系和peer关系
                    if as_dict.get(after) is not None:
                        as_dict[after].setdefault("v6Upstream", set()).add(pre)
                        as_dict[after].setdefault("v6Peer", set()).add(pre)
                    if as_dict.get(pre) is not None:
                        as_dict[pre].setdefault("v6Downstream", set()).add(after)
                        as_dict[pre].setdefault("v6Peer", set()).add(after)

        # 在字典中，为该路由源 AS 添加这整条 ASPath 和 前缀，表明源 AS 有这么条路由并拥有这么个前缀
        try:
            source = int(path[-1].strip())
        except Exception as e:
            print(e)
            continue

        print(f'source: {source}')
        if prefix_version == 4:
            if as_dict.get(source) is not None:
                as_dict[source].setdefault("v4Propagation", set()).add(route[6])
                as_dict[source].setdefault("v4Prefixes", set()).add(prefix)
        if prefix_version == 6:
            if as_dict.get(source) is not None:
                as_dict[source].setdefault("v6Propagation", set()).add(route[6])
                as_dict[source].setdefault("v6Prefixes", set()).add(prefix)

# as_dict = convert_set_to_list(as_dict)
print(as_dict)
