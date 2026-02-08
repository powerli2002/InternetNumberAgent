FROM python:3.10-slim
LABEL maintainer=="lgh"
# 将 python 添加进环境变量
ENV PATH /usr/local/bin:$PATH
# 用于程序判断是否在容器中运行
ENV IN_DOCKER_CONTAINER True
# 设置工作目录
ADD . /work
WORKDIR /work
# 配置环境
RUN ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo 'Asia/Shanghai' > /etc/timezone \
    && mkdir -p /data \
    && mkdir -p /logs \
    && if [ -f /etc/apt/sources.list ]; then sed -i 's#http://archive.ubuntu.com/#http://mirrors.tuna.tsinghua.edu.cn/#g' /etc/apt/sources.list; fi \
    && if [ -f /etc/apt/sources.list.d/debian.sources ]; then sed -i 's#http://deb.debian.org#http://mirrors.tuna.tsinghua.edu.cn#g' /etc/apt/sources.list.d/debian.sources; fi \
    && apt-get update -y \
    && apt-get upgrade -y \
    && apt-get install -y whois \
    && apt-get install -y postgresql \
    && apt-get install -y libpq-dev gcc
# 安装依赖
RUN pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn \
    && pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
