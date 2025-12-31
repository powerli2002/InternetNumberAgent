import sys
sys.path.append('..')

from .xdbSearcher import XdbSearcher

import os
class BlueDatabase:
    def __init__(self, file_path, file_name):
        self._file_path = file_path
        self._file_name = file_name
        self._dir = os.path.join(self._file_path,self._file_name)
        cb = XdbSearcher.loadContentFromFile(dbfile=self._dir)
        self._database = XdbSearcher(contentBuff=cb)
    
    def get_all(self,ip):
        info = self._database.searchByIPStr(ip)
        info = info.split('|')
        return info

    def get_country(self,ip):
        info = self._database.searchByIPStr(ip)
        info = info.split('|')
        country = info[1] if info[1]!='' else 'NULL'
        return country

    def get_region(self,ip):
        info = self._database.searchByIPStr(ip)
        info = info.split('|')
        region = info[2] if info[2]!='' else 'NULL'
        return region

    def get_city(self,ip):
        info = self._database.searchByIPStr(ip)
        info = info.split('|')
        city = info[3] if info[3]!='' else 'NULL'
        return city
    
    def get_info(self,ip):
        info = self._database.searchByIPStr(ip)
        info = info.split('|')
        return {
            'country':info[9] if info[9]!='' else 'NULL',
            
            'province':info[2].replace('省','') if info[2]!='' else 'NULL',
            'city':info[3].replace('市','') if info[3]!='' else 'NULL',
            'latitude':info[12] if info[12]!='' else 'NULL',
            'longitude':info[13] if info[13]!='' else 'NULL',
            'country_CN':info[1] if info[1]!='' else 'NULL',
            
        }
    # def get()
if __name__=='__main__':
    # Blue = BlueDatabase('/home/wh/ali/rawdata/database_quick/','ip.xdb')
    # info = Blue.get_info('101.84.166.99')
    # # data = info.split('|')
    # print(info)

    Blue = BlueDatabase('data/new_database_raw/','blue.xdb')
    info = Blue.get_info('101.84.166.99')
    # data = info.split('|')
    print(info)