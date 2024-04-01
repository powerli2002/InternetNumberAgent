import os
import sys
import re
import yaml
import pandas as pd
from src.utils.logging_manager import logger
import psycopg2
from psycopg2 import DatabaseError
from psycopg2.extras import execute_values
from psycopg2.extensions import connection
from typing import Union

sys.path.append(os.getcwd())


class DB_Tool():
    def __init__(self, config_path: str, date: str):
        '''
        DB_Tool 类，用于操作 PostgreSQL 数据库。

        Parameters:

            config_path - 配置文件路径

            date - 日期，格式为 YYYY-MM-DD

        Returns:

            None
        '''
        self.date = date
        self.__load_config(config_path)

    def __load_config(self, config_path):
        with open(config_path, 'r') as cf:
            config = yaml.load(cf.read(), Loader=yaml.loader.SafeLoader)
            self.postgresql_database = config["postgresql_database"]
            self.postgresql_user = config["postgresql_user"]
            self.postgresql_password = config["postgresql_password"]
            self.postgresql_host = config["postgresql_host"]
            self.postgresql_port = config["postgresql_port"]

    def __creat_table(self, conn: connection, table_name: str = None, col_list: list = None, primary: list = None, ctype: dict = None):
        '''
        创建表格，如果表格已存在则不创建

        Parameters:

            conn - PostgreSQL 连接，请注意，本函数不负责关闭连接

            table_name - 表格名称

            col_list - 表格字段名列表

            primary - 主键列表

            ctype - 表格字段名类型

        Returns:

            None
        '''
        if col_list is not None and table_name is not None:
            # 表格字段名类型默认设为 TEXT
            ctype = ctype or {}
            for col in col_list:
                if col not in ctype:
                    ctype[col] = 'TEXT'
            # 构造创建数据库表语句
            table_creat_sql = 'CREATE TABLE IF NOT EXISTS {0}('.format(table_name)
            for col in col_list[0:]:
                table_creat_sql += '\"{0}\" {1},'.format(col, ctype[col])
            # 指定主键，若参数为空，使用首列名称作为主键
            # 与当前字段名列表交集，避免参数传入多余的无效名称
            primary = primary or []
            primary = list(set(primary) & set(col_list))
            if len(primary) == 0:
                primary = [col_list[0]]
            table_creat_sql += 'PRIMARY KEY ({0})'.format(','.join(f'"{p}"' for p in primary))

            if table_creat_sql[-1] == ',':
                table_creat_sql = table_creat_sql[:-1]
            table_creat_sql += ');'

        try:
            # loggingManager.logger.info('开始创建表格')
            logger.info('开始创建表格 %s' % table_name)
            # 创建数据库游标，用 with 语句自动关闭游标
            with conn.cursor() as cur:
                # 执行 SQL 语句
                cur.execute(table_creat_sql)
                # 提交事务
                conn.commit()
        except (Exception, DatabaseError) as e:
            # loggingManager.logger.error('PostgreSQL 建表失败：%s' % e)
            logger.error('PostgreSQL 建表失败：%s' % e)

    def __check_table_exist(self, conn: connection, table_name: str) -> bool:
        '''
        判断表格是否存在

        Parameters:

            table_name - 表格名称

        Returns:

            bool - 表格是否存在
        '''
        try:
            logger.debug('检查表格 %s 是否存在' % table_name)
            # 创建数据库游标，用 with 语句自动关闭游标
            with conn.cursor() as cur:
                # 执行 SQL 语句
                cur.execute(
                    "SELECT EXISTS(SELECT * FROM information_schema.tables WHERE table_name = '{0}');".format(table_name,))
                # 提交事务
                conn.commit()
                return cur.fetchone()[0]
        except (Exception, DatabaseError) as e:
            logger.error('PostgreSQL 检查表格 %s 是否存在失败：%s' % (table_name, e))

    def df_to_DB(self, df: pd.DataFrame, table_name: str, primary: list = None, ctype: dict = None):
        '''
        将 DataFrame 数据导入 PostgreSQL 数据库

        Parameters:

            df - DataFrame 格式数据，DataFrame 的第一列为主键

            tabel_name - 表格名称

            ctype - 表格列数据类型，用于创建表，为 PostgreSQL 类型

            primary - 主键列表，支持联合主键

        Returns:

            None
        '''

        # 创建 PostgreSQL 数据库连接
        with psycopg2.connect(database=self.postgresql_database, user=self.postgresql_user, password=self.postgresql_password, host=self.postgresql_host, port=self.postgresql_port) as conn:
            conn.autocommit = True
            table_name = re.sub('[^0-9a-zA-Z_]+', '_', table_name)
            if not self.__check_table_exist(conn, table_name):
                self.__creat_table(
                    conn, table_name=table_name, col_list=df.columns.to_list(), primary=primary, ctype=ctype)

            self.__store_data(conn, df, table_name, primary=primary)

    def query_by_sql(self, sql: str) -> pd.DataFrame:
        '''
        通过 SQL 语句查询数据

        Parameters:

            sql - SQL 语句

        Returns:

            pd.DataFrame - 查询结果
        '''
        # 创建 PostgreSQL 数据库连接
        with psycopg2.connect(database=self.postgresql_database, user=self.postgresql_user, password=self.postgresql_password, host=self.postgresql_host, port=self.postgresql_port) as conn:
            conn.autocommit = True
            # 创建数据库游标，用 with 语句自动关闭游标
            with conn.cursor() as cur:
                # 执行 SQL 语句
                cur.execute(sql)
                # 提交事务
                conn.commit()
                if cur.description is not None:
                    return pd.DataFrame(cur.fetchall())

    def query_from_DB(self, table_name: str, col_list: list = None, conditions: Union[dict, str] = None) -> pd.DataFrame:
        '''
        从 PostgreSQL 数据库中查询数据

        Parameters:

            table_name - 表格名称

            col_list - 需要查询的字段列表

            conditions - 查询条件，字典类型为列值对，值为列表时为多值查询

        Returns:

            pd.DataFrame - 查询结果
        '''
        # 创建 PostgreSQL 数据库连接
        with psycopg2.connect(database=self.postgresql_database, user=self.postgresql_user, password=self.postgresql_password, host=self.postgresql_host, port=self.postgresql_port) as conn:
            conn.autocommit = True
            if not self.__check_table_exist(conn, table_name):
                logger.error('表格 %s 不存在' % table_name)
                return pd.DataFrame()
            else:
                return self.__query_data(conn, table_name, col_list, conditions)

    def __query_data(self, conn: connection, table_name: str, col_list: list = None, conditions: Union[dict, str] = None) -> pd.DataFrame:
        '''
        从 PostgreSQL 数据库中查询数据

        Parameters:

            conn - PostgreSQL 连接，请注意，本函数不负责关闭连接

            table_name - 表格名称

            col_list - 需要查询的字段列表

            conditions - 查询条件

        Returns:

            pd.DataFrame - 查询结果
        '''
        try:
            logger.debug('查询表格 %s 列名' % table_name)
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT column_name, data_type FROM information_schema.columns where table_name = '{table_name}';")
                conn.commit()
                records = cur.fetchall()
                column_name = [x[0] for x in records]
                # data_type = [x[1] for x in records]
                # column_type_map = dict(zip(column_name, data_type))
                column_name = [x for x in column_name if x != '__modified_at']
        except (Exception, DatabaseError) as e:
            logger.error('PostgreSQL 查询表格 %s 列名失败：%s' % (table_name, e))
            return None
        if col_list is None:
            col_list = column_name
        sel_list = ','.join([f'"{x}"' for x in col_list])

        try:
            logger.debug('开始查询表格 %s' % table_name)
            # 创建数据库游标，用 with 语句自动关闭游标
            with conn.cursor() as cur:
                # 执行 SQL 语句
                if conditions is None:
                    cur.execute(f'SELECT {sel_list} FROM {table_name};')
                else:
                    if isinstance(conditions, dict):
                        cond_list = []
                        for key, value in conditions.items():
                            if isinstance(value, list):
                                value = ','.join([f"'{x}'" if isinstance(x, str) else str(x) for x in value])
                                cond_list.append(f'"{key}" IN ({value})')
                            else:
                                value = f"'{value}'" if isinstance(value, str) else value
                                cond_list.append(f'"{key}" = {value}')
                        predicate = ' AND '.join(cond_list)
                    else:
                        predicate = conditions
                    cur.execute(f'SELECT {sel_list} FROM {table_name} WHERE {predicate};')
                # 提交事务
                conn.commit()
                return pd.DataFrame(cur.fetchall(), columns=col_list)
        except (Exception, DatabaseError) as e:
            logger.error('PostgreSQL 查询表格 %s 失败：%s' % (table_name, e))
            return None

    def __store_data(self, conn: connection, df: pd.DataFrame, table_name: str, primary: list = None):
        '''
        将 DataFrame 数据存储到 PostgreSQL 数据库

        Parameters:

            conn - PostgreSQL 连接，请注意，本函数不负责关闭连接

            df - DataFrame 数据

            tabel_name - 表格名称

            primary - 主键列表

        Returns:

            None
        '''
        # 获得表字段、主键与非主键
        col_list = df.columns.to_list()
        primary = primary or []
        primary = list(set(primary) & set(col_list))
        if len(primary) == 0:
            primary = [col_list[0]]
        non_primary = list(set(col_list) - set(primary))
        df.dropna(subset=primary, inplace=True) # 主键约束
        df.drop_duplicates(subset=primary, inplace=True)  # 去重
        df[non_primary] = df[non_primary].replace({'': None, 'null': None})  # 非主键 '' 与 'null' 替换为 null
        df[non_primary] = df[non_primary].replace({pd.NA: None})  # 非主键 NA 替换为 null
        # 将 DataFrame 数据转换为元组列表
        data = [tuple(x) for x in df.values]

        col_list = ['\"'+x+'\"' for x in col_list]
        excluded_str = ','.join(
            ['"'+x+'"'+'=excluded.'+'"'+x+'"' for x in non_primary])  # 用于 ON CONFLICT 语句

        try:
            logger.debug('写入 PostgreSQL 数据库表: %s' % table_name)
            # 创建数据库游标，用 with 语句自动关闭游标
            with conn.cursor() as cur:
                # 将已有数据转移至历史表
                cur.execute('INSERT INTO {0}_audit SELECT * FROM {0}; TRUNCATE {0};'.format(table_name))
                conn.commit()
            with conn.cursor() as cur:
                # 插入新数据
                execute_values(cur, 'INSERT INTO {0} VALUES %s ON CONFLICT ({1}) DO UPDATE SET {2};'.format(
                    table_name, ','.join(f'"{p}"' for p in primary), excluded_str), data)
                # 提交事务
                conn.commit()
            logger.debug('%s 数据写入成功' % table_name)
        except (Exception, DatabaseError) as e:
            logger.error('%s 数据写入失败：%s' % (table_name, e))
