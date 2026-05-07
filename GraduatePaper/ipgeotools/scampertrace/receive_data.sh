#!/bin/bash

# --- 脚本说明 ---
# 功能：从三个不同的探针服务器上拷贝指定的数据文件到目标服务器。
# 用法：./copy_probe_data.sh <source_filename>
# 示例：./copy_probe_data.sh connect_foreign_ipv6_prefix_result.csv
# -----------------

# 1. 检查用户是否提供了文件名参数
if [ -z "$1" ]; then
    # 如果第一个参数 ($1) 为空，则打印用法说明并退出
    echo "错误: 请提供源文件名作为参数。"
    echo "用法: $0 <source_filename>"
    exit 1
fi

# 2. 从命令行第一个参数中读取源文件名，并将其存储在变量中
SOURCE_FILENAME=$1

# 3. 定义一些通用变量，方便未来修改和阅读
# 源服务器上的文件基础路径
SOURCE_BASE_PATH="~/code/scampertrace/data/output"

# 目标服务器和路径
DEST_USER_HOST="root@10.99.8.11"
DEST_BASE_PATH="/home/lzj/MyPaper/Miniproject/scampertrace/data/output"

# --- 开始执行拷贝操作 ---

echo "==> 开始从探针服务器拷贝文件: ${SOURCE_FILENAME}"
echo "-----------------------------------------------------"

# 从 Probe 1 拷贝
echo "[1/3] 正在从 Probe 1 (niclab@192.168.100.1) 拷贝..."
scp niclab@192.168.100.1:${SOURCE_BASE_PATH}/${SOURCE_FILENAME} ${DEST_USER_HOST}:${DEST_BASE_PATH}/probe1_${SOURCE_FILENAME}

# 从 Probe 3 拷贝
echo "[2/3] 正在从 Probe 3 (zp@192.168.100.3) 拷贝..."
scp zp@192.168.100.3:${SOURCE_BASE_PATH}/${SOURCE_FILENAME} ${DEST_USER_HOST}:${DEST_BASE_PATH}/probe3_${SOURCE_FILENAME}

# 从 Probe 4 拷贝
echo "[3/3] 正在从 Probe 4 (jxx@192.168.100.4) 拷贝..."
scp jxx@192.168.100.4:${SOURCE_BASE_PATH}/${SOURCE_FILENAME} ${DEST_USER_HOST}:${DEST_BASE_PATH}/probe4_${SOURCE_FILENAME}

echo "-----------------------------------------------------"
echo "==> 所有文件拷贝完成。"
