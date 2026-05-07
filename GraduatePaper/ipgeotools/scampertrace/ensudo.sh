#!/bin/bash

# ScamperTrace - sudo免密权限配置脚本
# 用于配置scamper命令的sudo免密执行权限

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查是否为root用户
check_root() {
    if [[ $EUID -eq 0 ]]; then
        log_error "请不要以root用户运行此脚本"
        exit 1
    fi
}

# 检查scamper是否已安装
check_scamper() {
    local scamper_path=$(which scamper 2>/dev/null || echo "")
    
    if [[ -z "$scamper_path" ]]; then
        log_error "未找到scamper命令，请先安装scamper"
        log_info "安装命令示例:"
        log_info "  Ubuntu/Debian: sudo apt-get install scamper"
        log_info "  CentOS/RHEL: sudo yum install scamper"
        log_info "  macOS: brew install scamper"
        exit 1
    fi
    
    echo "$scamper_path"
}

# 配置sudo免密权限
configure_sudo_nopasswd() {
    log_info "正在配置scamper的sudo免密权限..."
    
    local user_name=$(whoami)
    local scamper_path=$(check_scamper)
    
    local sudoers_line="$user_name ALL=(ALL) NOPASSWD: $scamper_path"
    local sudoers_file="/etc/sudoers.d/scampertrace"
    
    # 检查是否已经配置
    if sudo test -f "$sudoers_file" && sudo grep -q "$sudoers_line" "$sudoers_file" 2>/dev/null; then
        log_success "sudo免密权限已配置"
        return 0
    fi
    
    log_info "用户: $user_name"
    log_info "scamper路径: $scamper_path"
    log_info "配置行: $sudoers_line"
    
    # 检查scamper是否可执行
    if [[ ! -x "$scamper_path" ]]; then
        log_error "scamper文件不可执行: $scamper_path"
        exit 1
    fi
    
    # 用户确认
    log_warning "即将添加以下配置到 $sudoers_file 文件："
    echo "  $sudoers_line"
    echo ""
    read -p "是否继续？(y/N): " -n 1 -r
    echo ""
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_warning "用户取消操作"
        exit 0
    fi
    
    # 创建临时文件验证语法
    local temp_file=$(mktemp)
    echo "$sudoers_line" > "$temp_file"
    
    if ! sudo visudo -c -f "$temp_file" >/dev/null 2>&1; then
        log_error "sudoers配置语法无效"
        rm -f "$temp_file"
        exit 1
    fi
    
    # 备份现有sudoers文件（如果存在）
    if sudo test -f "$sudoers_file"; then
        local backup_file="${sudoers_file}.backup.$(date +%Y%m%d_%H%M%S)"
        sudo cp "$sudoers_file" "$backup_file"
        log_info "已备份现有配置到: $backup_file"
    fi
    
    # 添加配置到sudoers.d
    log_info "正在添加sudo免密配置..."
    {
        echo "# ScamperTrace sudo免密配置 - 自动生成于 $(date)"
        echo "$sudoers_line"
    } | sudo tee "$sudoers_file" > /dev/null
    
    # 设置正确的权限
    sudo chmod 440 "$sudoers_file"
    
    rm -f "$temp_file"
    
    # 验证配置
    if sudo -n "$scamper_path" -v >/dev/null 2>&1; then
        log_success "sudo免密权限配置成功"
        log_info "测试命令: sudo $scamper_path -v"
    else
        log_warning "sudo免密权限可能配置失败，请手动验证: sudo $scamper_path -v"
    fi
}

# 移除sudo免密配置
remove_sudo_nopasswd() {
    log_info "正在移除scamper的sudo免密配置..."
    
    local sudoers_file="/etc/sudoers.d/scampertrace"
    
    if sudo test -f "$sudoers_file"; then
        log_info "找到配置文件: $sudoers_file"
        
        # 用户确认
        log_warning "即将删除以下文件："
        echo "  $sudoers_file"
        echo ""
        read -p "是否继续？(y/N): " -n 1 -r
        echo ""
        
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_warning "用户取消操作"
            exit 0
        fi
        
        # 备份后删除
        local backup_file="${sudoers_file}.removed.$(date +%Y%m%d_%H%M%S)"
        sudo cp "$sudoers_file" "$backup_file"
        sudo rm "$sudoers_file"
        
        log_success "已移除sudo免密配置"
        log_info "备份文件: $backup_file"
    else
        log_info "未找到配置文件: $sudoers_file"
    fi
}

# 检查当前配置状态
check_status() {
    log_info "检查sudo免密配置状态..."
    
    local user_name=$(whoami)
    local scamper_path=$(which scamper 2>/dev/null || echo "")
    local sudoers_file="/etc/sudoers.d/scampertrace"
    local sudoers_line="$user_name ALL=(ALL) NOPASSWD: $scamper_path"
    
    echo "用户: $user_name"
    echo "scamper路径: $scamper_path"
    echo "配置文件: $sudoers_file"
    echo ""
    
    if [[ -z "$scamper_path" ]]; then
        log_error "scamper未安装"
        return 1
    fi
    
    if sudo test -f "$sudoers_file"; then
        log_success "配置文件存在"
        if sudo grep -q "$sudoers_line" "$sudoers_file" 2>/dev/null; then
            log_success "配置正确"
            
            # 测试sudo权限
            if sudo -n "$scamper_path" -v >/dev/null 2>&1; then
                log_success "sudo免密权限工作正常"
            else
                log_error "sudo免密权限测试失败"
            fi
        else
            log_warning "配置文件存在但内容不匹配"
        fi
    else
        log_warning "配置文件不存在"
    fi
}

# 显示帮助信息
show_help() {
    echo "ScamperTrace - sudo免密权限配置脚本"
    echo ""
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  configure    配置sudo免密权限（默认）"
    echo "  remove       移除sudo免密配置"
    echo "  status       检查当前配置状态"
    echo "  help         显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0                    # 配置sudo免密权限"
    echo "  $0 configure          # 配置sudo免密权限"
    echo "  $0 remove             # 移除配置"
    echo "  $0 status             # 检查状态"
}

# 主函数
main() {
    check_root
    
    case "${1:-configure}" in
        "configure"|"")
            configure_sudo_nopasswd
            ;;
        "remove")
            remove_sudo_nopasswd
            ;;
        "status")
            check_status
            ;;
        "help"|"-h"|"--help")
            show_help
            ;;
        *)
            log_error "未知选项: $1"
            show_help
            exit 1
            ;;
    esac
}

# 运行主函数
main "$@" 