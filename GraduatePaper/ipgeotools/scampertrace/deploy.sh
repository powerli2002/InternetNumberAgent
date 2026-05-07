#!/bin/bash

# ScamperTrace 自动部署脚本
# 用于自动下载和配置 miniconda、scamper，创建虚拟环境并安装依赖

set -e  # 出错时退出

# 颜色输出函数
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info() {
    echo -e "${BLUE}[信息]${NC} $1"
}

success() {
    echo -e "${GREEN}[成功]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[警告]${NC} $1"
}

error() {
    echo -e "${RED}[错误]${NC} $1"
}

# 安装状态文件
INSTALL_STATUS_FILE="$HOME/.scampertrace_install_status"

# 检查安装状态
check_install_status() {
    local step="$1"
    if [[ -f "$INSTALL_STATUS_FILE" ]] && grep -q "^$step$" "$INSTALL_STATUS_FILE"; then
        return 0  # 已安装
    else
        return 1  # 未安装
    fi
}

# 标记安装完成
mark_install_complete() {
    local step="$1"
    echo "$step" >> "$INSTALL_STATUS_FILE"
}

# 检查操作系统
detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        OS="Linux"
        if command -v apt-get &> /dev/null; then
            DISTRO="debian"
        elif command -v yum &> /dev/null; then
            DISTRO="redhat"
        elif command -v pacman &> /dev/null; then
            DISTRO="arch"
        else
            DISTRO="unknown"
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        OS="macOS"
        DISTRO="macos"
    else
        OS="unknown"
        DISTRO="unknown"
    fi
    
    info "检测到操作系统: $OS ($DISTRO)"
}

# 检查命令是否存在
command_exists() {
    command -v "$1" &> /dev/null
}

# 重试下载函数
retry_download() {
    local url="$1"
    local output="$2"
    local max_retries="${3:-3}"
    local delay="${4:-5}"
    
    for ((i=1; i<=max_retries; i++)); do
        if wget -O "$output" "$url" 2>/dev/null; then
            return 0
        fi
        warning "下载失败 (尝试 $i/$max_retries)"
        if [[ $i -lt $max_retries ]]; then
            sleep $delay
        fi
    done
    return 1
}

# 安装系统依赖
install_system_deps() {
    if check_install_status "system_deps"; then
        success "系统依赖已安装，跳过"
        return 0
    fi
    
    info "正在安装系统依赖..."
    
    case $DISTRO in
        "debian")
            sudo apt-get update
            sudo apt-get install -y wget curl build-essential
            ;;
        "redhat")
            sudo yum update -y
            sudo yum install -y wget curl gcc gcc-c++ make
            ;;
        "arch")
            sudo pacman -Sy --noconfirm wget curl base-devel
            ;;
        "macos")
            if ! command_exists brew; then
                warning "未检测到Homebrew，请手动安装: https://brew.sh/"
                read -p "按回车键继续..."
            else
                brew install wget curl
            fi
            ;;
        *)
            warning "未知的系统发行版，跳过系统依赖安装"
            ;;
    esac
    
    mark_install_complete "system_deps"
    success "系统依赖安装完成"
}

# 安装Miniconda
install_miniconda() {
    if check_install_status "miniconda"; then
        success "Miniconda已安装，跳过"
        return 0
    fi
    
    info "检查Miniconda安装状态..."
    
    if command_exists conda; then
        success "Miniconda已安装"
        mark_install_complete "miniconda"
        return 0
    fi
    
    # 检查是否已存在miniconda3目录
    if [[ -d "$HOME/miniconda3" ]]; then
        success "检测到已存在的miniconda3目录，跳过安装"
        # 添加到PATH
        export PATH="$HOME/miniconda3/bin:$PATH"
        mark_install_complete "miniconda"
        return 0
    fi
    
    info "正在下载并安装Miniconda..."
    
    # 确定架构和下载链接
    if [[ "$OS" == "Linux" ]]; then
        if [[ $(uname -m) == "x86_64" ]]; then
            MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
        else
            MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh"
        fi
    elif [[ "$OS" == "macOS" ]]; then
        if [[ $(uname -m) == "arm64" ]]; then
            MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh"
        else
            MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-x86_64.sh"
        fi
    else
        error "不支持的操作系统: $OS"
        exit 1
    fi
    
    # 下载Miniconda安装脚本
    MINICONDA_INSTALLER="/tmp/miniconda.sh"
    info "从阿里云镜像下载Miniconda: $MINICONDA_URL"
    
    retry_download "$MINICONDA_URL" "$MINICONDA_INSTALLER" 5 10
    
    # 安装Miniconda
    info "正在安装Miniconda..."
    chmod +x "$MINICONDA_INSTALLER"
    
    bash "$MINICONDA_INSTALLER" -b -p "$HOME/miniconda3"
    
    # 初始化conda
    info "正在初始化conda..."
    "$HOME/miniconda3/bin/conda" init
    
    # 添加到PATH
    export PATH="$HOME/miniconda3/bin:$PATH"
    
    # 配置conda镜像源
    info "正在配置conda镜像源..."
    
    # 先接受Anaconda条款服务
    info "正在接受Anaconda条款服务..."
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main || true
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r || true
    
    # 尝试配置清华镜像源，如果失败则使用默认源
    info "尝试配置清华镜像源..."
    mirror_success=false
    
    # 测试清华镜像源是否可用
    if curl -s --connect-timeout 5 https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/ >/dev/null 2>&1; then
        info "清华镜像源可用，正在配置..."
        if conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/ 2>/dev/null; then
            conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/free/ 2>/dev/null || true
            conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r/ 2>/dev/null || true
            conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/pro/ 2>/dev/null || true
            info "清华镜像源配置成功"
            mirror_success=true
        else
            warning "清华镜像源配置失败"
        fi
    else
        warning "清华镜像源不可访问"
    fi
    
    # 如果镜像源配置失败，使用默认源
    if [[ "$mirror_success" == "false" ]]; then
        warning "镜像源配置失败，使用默认源"
        # 清除可能有问题的频道配置
        conda config --remove channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/ 2>/dev/null || true
        conda config --remove channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/free/ 2>/dev/null || true
        conda config --remove channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r/ 2>/dev/null || true
        conda config --remove channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/pro/ 2>/dev/null || true
    fi
    
    conda config --set show_channel_urls yes || true
    
    # 清理安装文件
    rm -f "$MINICONDA_INSTALLER"
    
    mark_install_complete "miniconda"
    success "Miniconda安装完成"
}

# 创建虚拟环境
create_conda_env() {
    if check_install_status "conda_env"; then
        success "虚拟环境已创建，跳过"
        return 0
    fi
    
    info "正在创建ScamperTrace虚拟环境..."
    
    # 确保conda在PATH中
    if ! command_exists conda; then
        export PATH="$HOME/miniconda3/bin:$PATH"
    fi
    
    # 再次确保条款服务已接受
    info "确保Anaconda条款服务已接受..."
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main || true
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r || true
    
    # 检查环境是否已存在
    if conda env list | grep -q "scampertrace"; then
        success "scampertrace环境已存在，跳过创建"
        mark_install_complete "conda_env"
        return 0
    fi
    
    # 创建新环境，测试镜像源可用性
    info "正在创建虚拟环境..."
    
    # 测试清华镜像源是否可用于创建环境
    if curl -s --connect-timeout 5 https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/ >/dev/null 2>&1; then
        info "尝试使用清华镜像源创建环境..."
        if conda create -n scampertrace python=3.9 -y -c https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/ 2>/dev/null; then
            info "使用清华镜像源创建环境成功"
        else
            warning "清华镜像源创建环境失败，尝试使用默认源..."
            conda create -n scampertrace python=3.9 -y
        fi
    else
        warning "清华镜像源不可访问，使用默认源创建环境..."
        conda create -n scampertrace python=3.9 -y
    fi
    
    mark_install_complete "conda_env"
    success "虚拟环境创建完成"
}

# 验证scamper安装
verify_scamper_installation() {
    local scamper_ok=false
    local sc_warts2csv_ok=false
    
    # 检查scamper主程序
    if command_exists scamper; then
        # scamper -v 可能返回非零退出码但仍然表示工具可用
        local scamper_output=$(scamper -v 2>&1)
        if [[ "$scamper_output" =~ "scamper version" ]]; then
            info "scamper主程序正常 ($(echo "$scamper_output" | head -1))"
            scamper_ok=true
        else
            error "scamper主程序无法运行"
        fi
    else
        error "scamper主程序未安装"
    fi
    
    # 检查sc_warts2csv工具
    if command_exists sc_warts2csv; then
        # 简单检查工具是否可执行，避免挂起
        if [[ -x "$(which sc_warts2csv)" ]]; then
            info "sc_warts2csv工具正常"
            sc_warts2csv_ok=true
        else
            error "sc_warts2csv工具无法运行"
        fi
    else
        error "sc_warts2csv工具未安装"
    fi
    
    if [[ "$scamper_ok" == "true" && "$sc_warts2csv_ok" == "true" ]]; then
        success "scamper安装验证通过"
        return 0
    else
        error "scamper安装验证失败"
        return 1
    fi
}

# 从源码编译scamper
compile_scamper() {
    info "正在从源码编译安装scamper..."
    
    # 安装编译依赖
    case $DISTRO in
        "debian")
            sudo apt-get install -y build-essential libssl-dev autoconf automake libtool
            ;;
        "redhat")
            sudo yum groupinstall -y "Development Tools"
            sudo yum install -y openssl-devel autoconf automake libtool
            ;;
        "macos")
            # macOS通常已有编译工具
            xcode-select --install 2>/dev/null || true
            if command_exists brew; then
                brew install autoconf automake libtool
            fi
            ;;
    esac
    
    # 下载scamper源码
    SCAMPER_VERSION="20230323"
    SCAMPER_URL="https://www.caida.org/tools/measurement/scamper/code/scamper-cvs-${SCAMPER_VERSION}.tar.gz"
    SCAMPER_DIR="/tmp/scamper-build"
    
    mkdir -p "$SCAMPER_DIR"
    cd "$SCAMPER_DIR"
    
    info "下载scamper源码..."
    if ! retry_download "$SCAMPER_URL" "scamper.tar.gz" 3 5; then
        error "下载scamper源码失败"
        exit 1
    fi
    
    tar -xzf scamper.tar.gz
    cd "scamper-cvs-${SCAMPER_VERSION}"
    
    info "配置编译选项..."
    ./configure --prefix=/usr/local
    
    info "编译scamper（这可能需要几分钟）..."
    make -j$(nproc 2>/dev/null || echo 4)
    
    info "安装scamper..."
    sudo make install
    
    # 更新动态链接库缓存
    if [[ "$OS" == "Linux" ]]; then
        sudo ldconfig
    fi
    
    # 清理临时文件
    cd /
    rm -rf "$SCAMPER_DIR"
    
    success "scamper编译安装完成"
}

# 安装scamper
install_scamper() {
    if check_install_status "scamper"; then
        success "scamper已安装，跳过"
        return 0
    fi
    
    info "检查scamper安装状态..."
    
    # 先验证现有安装
    if verify_scamper_installation; then
        success "scamper已正确安装，跳过"
        mark_install_complete "scamper"
        return 0
    fi
    
    info "正在安装scamper..."
    
    case $DISTRO in
        "debian"|"redhat"|"arch")
            # Linux系统直接从源码编译
            info "Linux系统检测到，从源码编译安装scamper..."
            compile_scamper
            ;;
        "macos")
            if command_exists brew; then
                if brew install scamper; then
                    success "通过Homebrew安装scamper成功"
                else
                    warning "Homebrew安装失败，尝试从源码编译..."
                    compile_scamper
                fi
            else
                warning "未检测到Homebrew，从源码编译安装..."
                compile_scamper
            fi
            ;;
        *)
            warning "未知系统发行版，尝试从源码编译..."
            compile_scamper
            ;;
    esac
    
    # 验证安装
    if verify_scamper_installation; then
        mark_install_complete "scamper"
        success "scamper安装完成"
    else
        error "scamper安装失败"
        exit 1
    fi
}

# 配置sudo免密权限
configure_sudo_nopasswd() {
    if check_install_status "sudo_config"; then
        success "sudo免密权限已配置，跳过"
        return 0
    fi
    
    info "正在配置scamper的sudo免密权限..."
    
    local user_name=$(whoami)
    local scamper_path=$(which scamper 2>/dev/null || echo "")
    
    if [[ -z "$scamper_path" ]]; then
        error "未找到scamper命令，请先安装scamper"
        return 1
    fi
    
    local sudoers_line="$user_name ALL=(ALL) NOPASSWD: $scamper_path"
    local sudoers_file="/etc/sudoers.d/scampertrace"
    
    # 检查是否已经配置
    if sudo test -f "$sudoers_file" && sudo grep -q "$sudoers_line" "$sudoers_file" 2>/dev/null; then
        success "sudo免密权限已配置"
        mark_install_complete "sudo_config"
        return 0
    fi
    
    info "用户: $user_name"
    info "scamper路径: $scamper_path"
    info "配置行: $sudoers_line"
    
    # 检查scamper是否可执行
    if [[ ! -x "$scamper_path" ]]; then
        error "scamper文件不可执行: $scamper_path"
        return 1
    fi
    
    # 用户确认
    warning "即将添加以下配置到 $sudoers_file 文件："
    echo "  $sudoers_line"
    echo ""
    read -p "是否继续？(y/N): " -n 1 -r
    echo ""
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        warning "用户取消操作"
        return 0
    fi
    
    # 创建临时文件验证语法
    local temp_file=$(mktemp)
    echo "$sudoers_line" > "$temp_file"
    
    if ! sudo visudo -c -f "$temp_file" >/dev/null 2>&1; then
        error "sudoers配置语法无效"
        rm -f "$temp_file"
        return 1
    fi
    
    # 备份现有sudoers文件（如果存在）
    if sudo test -f "$sudoers_file"; then
        local backup_file="${sudoers_file}.backup.$(date +%Y%m%d_%H%M%S)"
        sudo cp "$sudoers_file" "$backup_file"
        info "已备份现有配置到: $backup_file"
    fi
    
    # 添加配置到sudoers.d
    info "正在添加sudo免密配置..."
    {
        echo "# ScamperTrace sudo免密配置 - 自动生成于 $(date)"
        echo "$sudoers_line"
    } | sudo tee "$sudoers_file" > /dev/null
    
    # 设置正确的权限
    sudo chmod 440 "$sudoers_file"
    
    rm -f "$temp_file"
    
    # 验证配置
    if sudo -n "$scamper_path" -v >/dev/null 2>&1; then
        success "sudo免密权限配置成功"
        info "测试命令: sudo $scamper_path -v"
        mark_install_complete "sudo_config"
    else
        warning "sudo免密权限可能配置失败，请手动验证: sudo $scamper_path -v"
    fi
}

# 安装Python依赖
install_python_deps() {
    if check_install_status "python_deps"; then
        success "Python依赖已安装，跳过"
        return 0
    fi
    
    info "正在安装Python依赖..."
    
    # 激活conda环境
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
    conda activate scampertrace
    
    # 升级pip并配置阿里云镜像
    pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/
    pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
    pip config set global.trusted-host mirrors.aliyun.com
    
    # 安装项目依赖
    if [[ -f "requirements.txt" ]]; then
        pip install -r requirements.txt
    else
        # 手动安装核心依赖
        pip install pandas
    fi
    
    mark_install_complete "python_deps"
    success "Python依赖安装完成"
}

# 验证安装
verify_installation() {
    info "正在验证安装..."
    
    # 检查conda
    if ! command_exists conda; then
        export PATH="$HOME/miniconda3/bin:$PATH"
    fi
    
    if ! command_exists conda; then
        error "conda未正确安装"
        return 1
    fi
    
    # 检查scamper
    if ! verify_scamper_installation; then
        error "scamper未正确安装"
        return 1
    fi
    
    # 检查Python环境
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
    if ! conda activate scampertrace 2>/dev/null; then
        error "scampertrace环境未正确创建"
        return 1
    fi
    
    # 检查Python依赖
    if ! python -c "import pandas; print('pandas版本:', pandas.__version__)" 2>/dev/null; then
        error "pandas未正确安装"
        return 1
    fi
    
    success "所有组件验证通过"
    return 0
}

# 创建启动脚本
create_launch_script() {
    if check_install_status "launch_script"; then
        success "启动脚本已创建，跳过"
        return 0
    fi
    
    info "正在创建启动脚本..."
    
    cat > run_scampertrace.sh << 'EOF'
#!/bin/bash

# ScamperTrace启动脚本

# 设置UTF-8环境变量
export PYTHONIOENCODING=utf-8
export LANG=zh_CN.UTF-8

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 激活conda环境
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate scampertrace

# 检查是否有输入文件
if [[ ! -f "data/input/prefix.csv" ]]; then
    echo "未找到输入文件 data/input/prefix.csv"
    echo "正在创建示例文件..."
    mkdir -p data/input
    cat > data/input/prefix.csv << 'SAMPLE'
ipv4,ipv6
8.8.8.0/24,2001:4860:4860::/48
1.1.1.0/24,2606:4700:4700::/48
SAMPLE
    echo "已创建示例文件 data/input/prefix.csv"
    echo "请编辑此文件添加您的网络前缀，然后重新运行脚本"
    exit 0
fi

# 运行ScamperTrace
echo "正在启动ScamperTrace..."
python main.py "$@"
EOF
    
    chmod +x run_scampertrace.sh
    
    mark_install_complete "launch_script"
    success "启动脚本创建完成: run_scampertrace.sh"
}

# 显示使用说明
show_usage() {
    info "部署完成！使用说明："
    echo ""
    echo "1. 手动激活环境:"
    echo "   source ~/miniconda3/etc/profile.d/conda.sh"
    echo "   conda activate scampertrace"
    echo "   python main.py"
    echo ""
    echo "2. 配置输入文件:"
    echo "   编辑 data/input/prefix.csv 文件"
    echo ""
    echo "3. 查看结果:"
    echo "   结果保存在 data/output/ 目录"
    echo "   日志保存在 logs/ 目录"
    echo ""
    echo "4. 单独配置sudo权限:"
    echo "   ./deploy.sh --sudo-only"
    echo ""
    echo "5. 重新安装（清除状态）:"
    echo "   rm ~/.scampertrace_install_status"
    echo "   ./deploy.sh"
    echo ""
    echo "注意:"
    echo "- scamper已配置sudo免密权限"
    echo "- 如果遇到权限问题，请检查 /etc/sudoers.d/scampertrace 文件"
    echo "- 或者手动配置: sudo visudo -f /etc/sudoers.d/scampertrace"
}

# 主函数
main() {
    # 处理命令行参数
    if [[ "$1" == "--sudo-only" ]]; then
        echo "===================================================="
        echo "     ScamperTrace Sudo权限配置工具"
        echo "===================================================="
        echo ""
        
        # 检测操作系统
        detect_os
        
        # 配置sudo免密权限
        configure_sudo_nopasswd
        
        success "Sudo权限配置完成！"
        return 0
    fi
    
    echo "===================================================="
    echo "     ScamperTrace 自动部署脚本"
    echo "===================================================="
    echo ""
    
    # 检查是否为root用户
    if [[ $EUID -eq 0 ]]; then
        warning "不建议以root用户运行此脚本"
        read -p "是否继续? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
    
    # 检测操作系统
    detect_os
    
    # 安装系统依赖
    install_system_deps
    
    # 安装Miniconda
    install_miniconda
    
    # 创建虚拟环境
    create_conda_env
    
    # 安装scamper
    install_scamper
    
    # 安装Python依赖
    install_python_deps
    
    # 配置sudo免密权限
    configure_sudo_nopasswd
    
    # 验证安装
    if ! verify_installation; then
        error "安装验证失败，请检查错误信息"
        exit 1
    fi
    
    # 创建启动脚本
    create_launch_script
    
    # 显示使用说明
    show_usage
    
    success "ScamperTrace部署完成！"
}

# 捕获错误和中断信号
trap 'error "部署过程中断"; exit 1' INT TERM

# 运行主函数
main "$@"