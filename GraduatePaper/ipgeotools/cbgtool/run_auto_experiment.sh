#!/bin/bash
# 自动实验运行脚本

# 设置默认参数
LIMIT=1000
DRY_RUN=0
OFFLINE=0
LIST_ONLY=0

# 显示帮助信息
show_help() {
    echo "CBG自动实验运行脚本"
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  -h, --help       显示帮助信息"
    echo "  -l, --limit N    设置目标数量限制 (默认: 1000)"
    echo "  -d, --dry-run    模拟运行，不实际执行实验"
    echo "  -o, --offline    离线模式，不获取地址信息"
    echo "  --list           仅列出实验状态，不执行实验"
    echo ""
    echo "示例:"
    echo "  $0 --limit 500 --offline    使用离线模式运行，限制500个目标"
    echo "  $0 --dry-run               模拟运行，不实际执行"
    echo "  $0 --list                  仅列出实验状态"
    exit 0
}

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    key="$1"
    case $key in
        -h|--help)
            show_help
            ;;
        -l|--limit)
            LIMIT="$2"
            shift
            shift
            ;;
        -d|--dry-run)
            DRY_RUN=1
            shift
            ;;
        -o|--offline)
            OFFLINE=1
            shift
            ;;
        --list)
            LIST_ONLY=1
            shift
            ;;
        *)
            echo "未知选项: $key"
            show_help
            ;;
    esac
done

# 构建命令
CMD="python scripts/auto_experiment.py --limit $LIMIT"

if [ $DRY_RUN -eq 1 ]; then
    CMD="$CMD --dry-run"
fi

if [ $OFFLINE -eq 1 ]; then
    CMD="$CMD --offline"
fi

if [ $LIST_ONLY -eq 1 ]; then
    CMD="$CMD --list"
fi

# 显示将要执行的命令
echo "执行命令: $CMD"
echo "-----------------------------------"

# 在screen会话中运行命令

# 直接运行命令
eval $CMD
