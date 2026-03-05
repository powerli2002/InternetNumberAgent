import paramiko
import time
import re
import os
from apscheduler.schedulers.background import BlockingScheduler

SSH_HOST = ''
SSH_USER = ''
SSH_PWD = ''
REMOTE_PATH = ''
TARGET_FILE = ''
LOCAL_PATH = ''


class SSHConnection:
    def __init__(self, host='127.0.0.1', port=22, user='root', pwd='root'):
        '''
        初始化连接创建Transport通道

        '''
        self.host = host
        self.port = port
        self.user = user
        self.pwd = pwd

        self.ssh_obj = paramiko.SSHClient()
        self.ssh_obj.set_missing_host_key_policy(paramiko.AutoAddPolicy)
        self.ssh_obj.load_system_host_keys()
        self.ssh_obj.connect(hostname=self.host, port=self.port, username=self.user, password=self.pwd)

        self.sftp = paramiko.SFTPClient.from_transport(self.ssh_obj.get_transport())

    def close(self):
        '''
        关闭通道

        '''
        self.sftp.close()
        self.ssh_obj.close()

    def upload(self, local_path, remote_path):
        '''
        上传文件到远程主机

        '''
        self.sftp.put(local_path, remote_path)

    def download(self, local_path, remote_path):
        '''
        从远程主机下载文件到本地

        '''
        self.sftp.get(remote_path, local_path)

    def mkdir(self, target_path, mode='0777'):
        '''
        在远程主机上创建目录

        '''
        self.sftp.mkdir(target_path, mode)

    def rmdir(self, target_path):
        '''
        删除远程主机上的目录

        '''
        self.sftp.rmdir(target_path)

    def listdir(self, target_path):
        '''
        查看目录下文件以及子目录（如果需要更加细粒度的文件信息建议使用listdir_attr）

        '''
        return self.sftp.listdir(target_path)

    def remove(self, target_path):
        '''
        删除文件

        '''
        self.sftp.remove(target_path)

    def listdirattr(self, target_path):
        '''
        查看目录下文件以及子目录的详细信息（包含内容和参考os.stat返回一个FSTPAttributes对象，对象的具体属性请用__dict__查看）

        '''
        try:
            list = self.sftp.listdir_attr(target_path)
        except BaseException as e:
            print(e)
        return list

    def stat(self, remote_path):
        '''
        获取文件详情

        '''
        return self.sftp.stat(remote_path)

    def cmd(self, command):
        '''
        SSHClient输入命令远程操作主机

        '''

        # ssh.connect(hostname=self.host,port=self.port,username=self.user,password=self.pwd)
        stdin, stdout, stderr = self.ssh_obj.exec_command(command, get_pty=True)
        result = stdout.read()
        print(result)
        return result

    def get_which_entity(self, remote_path, entity_name):
        '''
        获取csv文件路径中最新的AS实体

        '''
        if entity_name == 'org_entity':
            pattern = re.compile('^org_entity_\d{4}-\d{2}-\d{2}.csv')
        else:
            pattern = re.compile('^as_entity_\d{4}-\d{2}-\d{2}.csv')
        entity_list = [os.path.join(remote_path, f) for f in self.listdir(remote_path) if pattern.match(f)]
        entity_list.sort()
        print(entity_list)
        self.download(os.path.join(LOCAL_PATH, f"{entity_name}.csv"), entity_list[-1])


def main():
    ssh = SSHConnection(host=SSH_HOST, port=22, user=SSH_USER, pwd=SSH_PWD)
    ssh.get_which_entity(remote_path=REMOTE_PATH, entity_name=TARGET_FILE)
    ssh.close()


if __name__ == '__main__':
    main()
    # scheduler = BlockingScheduler()
    # scheduler.add_job(func=main, trigger='cron', year='*', month='*', day='last')
    # scheduler.start()
