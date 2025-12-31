import os
import pandas as pd
import socket
import struct
from netaddr import *

class AiwenDatabase:
    def __init__(self,file_path,file_name):
        self._file_path = file_path
        self._file_name = file_name
        self._dir = os.path.join(self._file_path,self._file_name)
        columns = ['id','minip','maxip','continent','areacode','adcode','country','province','city','district','lngwgs','latwgs','radius','accuracy','owner','isp','asnumber','source','zipcode','timezone']
        self._database = pd.read_csv(self._dir,sep='\t',names=columns,header=0,dtype = str)

    def export(self):
        # 导出指定的列
        # "id"	"minip"	"maxip"	"continent"	"areacode"	"adcode"	"country"	"province"	"city"	"district"	"lngwgs"	"latwgs"	"radius"	"accuracy"	"owner"	"isp"	"asnumber"	"source"	"zipcode"	"timezone"
        export_cols = ['minip','maxip','country','province','city','district','lngwgs','latwgs','accuracy']
        self._database.to_csv('aiwen.csv',columns=export_cols,index=False)

    def query(self,ip):
        # 转化为整数
        ip = self._ip2long(ip)
        return self._search_city(ip)

    def get_info(self,ip):
        data = self.query(ip)
        return {'country':data['country'],'province':data['province'],'city':data['city'],'latitude':data['latwgs'],'longitude':data['lngwgs']}

    def _search_city(self,ip):
        start = 0
        end = self._database.shape[0] - 1
        #     print(end)
        mid = int((end + start) / 2)

        while (mid >= start and mid <= end):
            data = self._database.loc[mid]
            minip = int(data['minip'])
            maxip = int(data['maxip'])
            if ip >= minip and ip <= maxip:
                return self._database.loc[mid,['country','province','city','latwgs', 'lngwgs']]
            elif ip < minip:
                end = mid - 1
            elif ip > maxip:
                start = mid + 1
            mid = int((end + start) / 2)
        return {'country':'','province':'','city':'','latwgs':'','lngwgs':''}
    
    def _ip2long(self, ip):
        _ip = socket.inet_aton(ip)
        return struct.unpack("!L", _ip)[0]
    


        
        
    
