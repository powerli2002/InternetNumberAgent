import os
import time
import logging
from datetime import datetime

'''
不要直接运行这个 .py 文件！
'''

'''
日志模块，用于记录程序运行过程中的信息，便于调试和问题排查。
不要直接运行这个 .py 文件！
'''


def init_logger(logger_name='CBGLocTool', log_file_head='cbgloc', console_level=logging.INFO, file_level=logging.DEBUG, default_level=logging.DEBUG):
    '''
    初始化日志模块

    Parameters:

        - logger_name: logger的名字，用于区分不同的 logger

        - log_file_head: 日志文件名的前缀

        - console_level: 控制台日志的级别，一般为 INFO

        - file_level: 日志文件的级别，一般为 DEBUG

        - default_level: 默认日志级别，一般为 DEBUG

    Returns:

        - logger: logger实例

    '''

    # 返回一个logger实例，如果没有指定name，返回root logger。
    # 只要name相同，返回的logger实例都是同一个而且只有一个，即name和logger实例是一一对应的。
    # 这意味着，无需把logger实例在各个模块中传递。只要知道name，就能得到同一个logger实例。
    logger = logging.getLogger(logger_name)
    # 设置总日志级别, 也可以给不同的handler设置不同的日志级别
    # 设置logger的level， level有以下几个级别：
    # 级别高低顺序：NOTSET < DEBUG < INFO < WARNING < ERROR < CRITICAL
    # 如果把looger的级别设置为INFO， 那么小于INFO级别的日志都不输出， 大于等于INFO级别的日志都输出　
    logger.setLevel(default_level)

    # 避免重复添加handler
    if logger.handlers:
        return logger

    # 控制台日志和日志文件使用同一个formatter,formatter用于描述日志的格式
    formatter = logging.Formatter(
        '%(asctime)s - %(filename)s[line:%(lineno)d] - <%(threadName)s %(thread)d>' +
        '- <Process %(process)d> - %(levelname)s: %(message)s'
    )
    # asctime:日志产生的时间；filename:产生日志的脚本文件名；lineno:该脚本文件哪一行代码产生了日志
    # threadName: 当前线程名；thread: 当前进程名；Process进程同thread线程
    # levelname: logger的级别；meesage: 具体的日志信息

    mouth_str = datetime.now().strftime('%Y-%m')
    day_str = datetime.now().strftime('%d')
    log_dir = os.path.join(os.getcwd(), f'logs/{mouth_str}/{day_str}')

    if not os.path.isdir(log_dir):
        os.makedirs(log_dir)
    cur_time = time.strftime('%Y-%m-%d', time.localtime(time.time()))
    filename = f'{log_file_head}-{cur_time}-{os.getpid()}.log'  # 日志文件名，以当前时间命名

    # 创建 Handler, 输出日志到控制台和文件
    # 日志文件 FileHandler
    file_handler = logging.FileHandler(os.path.join(log_dir, filename), encoding='utf-8')  # 创建日志文件 handler
    file_handler.setFormatter(formatter)  # 设置 Formatter
    file_handler.setLevel(file_level)  # 单独设置日志文件的日志级别

    # 控制台日志 StreamHandler
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(console_level)  # 单独设置控制台日志的日志级别，注释掉则使用总日志级别

    # 将 handler 添加到 logger 中
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger


# 创建默认日志实例
logger = init_logger()
