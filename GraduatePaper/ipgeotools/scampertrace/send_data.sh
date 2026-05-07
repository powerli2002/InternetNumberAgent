#!/bin/bash

# --- 脚本说明 ---
# 功能：将本机上的一个文件发送到三个指定的探针服务器。
# 用法：./send_file.sh <local_file_path>
# 示例：./send_file.sh /Users/lizijian/code/BUPT/scampertrace/data/input/connect_foreign_ipv6_prefix.csv
# -----------------

# 1. 检查用户是否提供了文件路径作为参数
if [ -z "$1" ]; then
    echo "错误: 请提供需要发送的文件的完整路径作为参数。"
    echo "用法: $0 <local_file_path>"
    exit 1
fi

# 2. 从第一个参数中获取本地文件路径
LOCAL_FILE_PATH=$1

# 3. 检查本地文件是否存在，如果不存在则报错退出
if [ ! -f "$LOCAL_FILE_PATH" ]; then
    echo "错误: 文件不存在或不是一个有效文件: ${LOCAL_FILE_PATH}"
    exit 1
fi

# 4. 定义目标服务器列表 (数组) 和远程目标目录
REMOTE_SERVERS=(
    "niclab@192.168.100.1"
    "zp@192.168.100.3"
    "jxx@192.168.100.4"
)

REMOTE_DEST_PATH="~/code/scampertrace/data/input"

# --- 开始执行发送操作 ---

echo "==> 准备发送文件: ${LOCAL_FILE_PATH}"
echo "==> 目标目录: ${REMOTE_DEST_PATH}"
echo "-----------------------------------------------------"

# 5. 循环遍历服务器列表，并对每个服务器执行 scp 命令
for server in "${REMOTE_SERVERS[@]}"; do
    echo "--> 正在发送到 ${server}..."
    scp "${LOCAL_FILE_PATH}" "${server}:${REMOTE_DEST_PATH}"
done

echo "-----------------------------------------------------"
echo "==> 文件已成功发送到所有服务器。"
