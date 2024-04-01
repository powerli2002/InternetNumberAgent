import os
import sys
import time
import datetime
import traceback
import subprocess

sys.path.insert(0, '..')
from src.utils.logging_manager import logger
from src.as_entity.rib_parser import RIBParser

BGP_DATA_PATH = '../../bgpdata/data'
DATA_TIME_MONTH = ['2023.08']
CURRENT_PATH = os.path.dirname(os.path.abspath(__file__))
BGPDUMP_PATH = os.path.join(CURRENT_PATH, 'bgpdump')
TARGET_PATH = os.path.join(CURRENT_PATH, 'data/')


def parseData(source_bgp_file: str, target_dir: str, target_file_name: str = None) -> "tuple[str, subprocess.Popen]":
    '''
    将原始的 bgp 数据解析成 bgpdump 的数据格式

    Parameters:

        source_bgp_file: 原始的 bgp 数据文件，注意必须带路径

        target_dir: 解析后的 bgp 数据文件存放的目录

        target_file_name: 解析后的 bgp 数据文件名，如果不指定则默认为原始文件名，即将 .gz 或 .bz2 改为 .data

    Returns:

        target_file: 解析后的 bgp 数据文件路径

        p: 解析 bgp 数据的子进程

    '''
    # 将文件名从 .gz 或 .bz2 改为 .data
    bgp_file_name = target_file_name
    if target_file_name:
        file_name_list = target_file_name.split('.')
        if file_name_list[-1] in ['gz', 'bz2']:
            file_name_list[-1] = 'data'
        else:
            file_name_list.append('data')
        bgp_file_name = '.'.join(file_name_list)
    else:
        bgp_file_name = os.path.basename(source_bgp_file)
        file_name_list = bgp_file_name.split('.')
        file_name_list[-1] = 'data'
        bgp_file_name = '.'.join(file_name_list)

    target_file = os.path.join(target_dir, bgp_file_name)   # 解析后的 bgp 数据文件

    logger.info(f'解析后的文件为 {target_file}')
    logger.info(f'正在解析 {source_bgp_file} ...')
    p = subprocess.Popen([BGPDUMP_PATH, '-m', '-O', target_file, source_bgp_file])
    return target_file, p


def get_ripe_bgp_data():

    ripe_dir = os.path.join(BGP_DATA_PATH, 'ripe')
    subprocess_dict = {}

    l = []
    for dirpath, dirnames, filenames in os.walk(ripe_dir):
        for filename in [f for f in filenames if f.startswith('bview') and f.endswith('gz')]:
            l.append(filename.split('.')[1])
    l = sorted(list(set(l)))
    if len(l) < 2:
        return ''

    date = l[-2]
    logger.info(f'最新 BGP 数据日期 {date}')
    for dirpath, dirnames, filenames in os.walk(ripe_dir):
        for filename in [f for f in filenames if f.startswith('bview') and f.endswith('gz')]:
            if date in filename:
                src = os.path.join(dirpath, filename)
                dest = '-'.join([dirpath[dirpath.find('rrc'):dirpath.find('rrc')+5], filename])
                target, p = parseData(src, TARGET_PATH, dest)
                subprocess_dict[target] = p
    '''
    for rrc_name in os.listdir(ripe_dir):
        rrc_dir = os.path.join(ripe_dir, rrc_name)
        for date_month in os.listdir(rrc_dir):
            if date_month in DATA_TIME_MONTH:
                date_dir = os.path.join(rrc_dir, date_month)
                for gz_file in os.listdir(date_dir):
                    if gz_file.startswith('bview'):
                        bgp_dir = os.path.join(date_dir, gz_file)
                        target, p = parseData(bgp_dir, 'data/', f'{rrc_name}-{gz_file}')
                        subprocess_dict[target] = p
                        break
    '''
    for target, p in subprocess_dict.items():
        logger.info(f'正在解析 {target} ...')
        p.wait()
        logger.info(f'{target} 解析完成')

    return date


if __name__ == '__main__':
    while True:
        try:
            os.chdir(CURRENT_PATH)
            for file in os.listdir(TARGET_PATH):
                if file.endswith('.data'):
                    old = os.path.join(TARGET_PATH, file)
                    logger.info(f'删除 {old}')
                    os.remove(old)
            date = get_ripe_bgp_data()
            if date:
                os.chdir('..')
                logger.info('开始执行 RIBParser')
                obj = RIBParser(datetime.datetime.strptime(date, '%Y%m%d').strftime('%Y-%m-%d'), 'config.yaml', False)
                obj.run()
        except KeyboardInterrupt:
            logger.info('KeyboardInterrupt, Exiting...')
            exit()
        except Exception as e:
            logger.info(e)
            logger.info(traceback.format_exc())
        logger.info('即将休眠 1 天...')
        time.sleep(3600 * 24)
