import os
# import datx
import time
from pyipip import IPIPDatabase as ipip


# 如何查看 self._database 中的数据？
class IPIPDatabase():
    def __init__(self,file_path,file_name):
        self._dir = os.path.join(file_path,file_name)
        self._database = ipip(self._dir)

    def get_info(self,ip):
        try:
            info = self._database.lookup(ip)
            # 数据用/t分割,读取数据到数组
            info = info.split('\t')
            return {'country':info[0],'province':info[1],'city':info[2],'latitude':info[5],'longitude':info[6]}

        except Exception as e:
            print(e)
            return None
    
    def view_database(self):
        # 这里假设 ipip 对象有某种迭代或遍历的方法
        for item in self._database:
            print(item)



if __name__=='__main__':
    ip_db = IPIPDatabase('/home/lzj/MyPaper/Miniproject/FusionPosition/data/database','ipip.datx')
    ip = '192.168.127.10'
    info = ip_db.get_info(ip)
    print(info)
    print("done")
    ip_db.view_database()