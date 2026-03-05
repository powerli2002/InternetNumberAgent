import requests
import time
import sys
import json
import pandas as pd

url = 'https://api.asrank.caida.org/v2/graphql'
user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Edg/114.0.1823.67'
output_file = 'data/org_data.jsonl'

decoder = json.JSONDecoder()
encoder = json.JSONEncoder()

headers = {
    'User-Agent': user_agent,
    'Connection': 'close'
}

FIRST = 1000
OFFSET = 0
DEBUG_LIMIT = 0
DATA_TYPE = "organizations"


def org_data_query(first, offset):
    qury_org_data = """{
            organizations(first:%s, offset:%s) {
                totalCount
                pageInfo {
                    first
                    hasNextPage
                }
                edges {
                    node {
                        orgId
                        orgName
                        rank
                        seen
                        country {
                            iso
                            name
                        }
                        members{
                            numberAsns
                            numberAsnsSeen
                            asns{
                                totalCount
                                edges{
                                    node{
                                        asn
                                        asnName
                                    }
                                }
                            }
                        }
                        asnDegree {
                            provider
                            peer
                            customer
                            total
                            transit
                            sibling
                        }
                        orgDegree {
                            total
                            transit
                        }
                        cone {
                            numberAsns
                            numberPrefixes
                            numberAddresses
                        }
                    }
                }
            }
        }""" % (first, offset)
    return qury_org_data


def jsonl_to_csv(dir: str):
    # jsonl_data = []
    # with open(dir, 'r') as f:
    #     for line in f:
    #         jsonl_data.append(decoder.decode(line))
    df_json = pd.read_json(dir, lines=True)
    jsonl_data = df_json.to_dict('records')
    df = pd.json_normalize(jsonl_data, max_level=2)
    df.to_csv(dir.replace('.jsonl', '.csv'), index=False)
    # df.to_excel


def main():
    first = FIRST
    offset = OFFSET
    debug_limit = DEBUG_LIMIT
    data_type = DATA_TYPE
    hasNextPage = True
    start = time.time()
    print("writting: ", output_file)

    with open(output_file, 'w') as f:
        while hasNextPage:
            r = requests.post(url, headers=headers, json={"query": org_data_query(first, offset)}, timeout=60)
            json_data = r.json()
            if not ("data" in json_data and data_type in json_data["data"]):
                print("Failed to parse:", json_data, file=sys.stderr)
                sys.exit()
            data = json_data["data"][data_type]
            for node in data["edges"]:
                f.write(encoder.encode(node["node"]))
                f.write("\n")

            hasNextPage = data["pageInfo"]["hasNextPage"]
            offset += data["pageInfo"]["first"]

            print("    ", offset, "of", data["totalCount"], " ", time.time()-start, "(sec)", file=sys.stderr)
            start = time.time()

            if debug_limit and debug_limit < offset:
                hasNextPage = False


if __name__ == '__main__':
    # main()
    jsonl_to_csv(output_file)
