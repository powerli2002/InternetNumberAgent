#!/bin/bash

# Clash节点切换脚本
# 使用方法: ./switch_clash_node.sh [list|switch|current]

CLASH_API="http://127.0.0.1:9090"
PROXY_GROUP="GLOBAL"  # 根据您的配置调整

# 显示帮助信息
show_help() {
    echo "Clash节点切换工具"
    echo "使用方法:"
    echo "  $0 list           - 列出所有可用节点"
    echo "  $0 current        - 显示当前选择的节点"
    echo "  $0 switch <名称>  - 切换到指定节点"
    echo "  $0 test           - 测试当前节点连接"
    echo ""
    echo "示例:"
    echo "  $0 list"
    echo "  $0 switch '香港节点'"
    echo "  $0 current"
}

# 列出所有可用节点
list_nodes() {
    echo "获取可用节点列表..."
    curl -s "$CLASH_API/proxies/$PROXY_GROUP" | \
    python3 -c "
import json, sys
data = json.load(sys.stdin)
if 'all' in data:
    print('可用节点:')
    for i, node in enumerate(data['all'], 1):
        current = '★' if node == data.get('now', '') else ' '
        print(f'{current} {i:2d}. {node}')
else:
    print('无法获取节点列表')
"
}

# 显示当前节点
show_current() {
    echo "当前选择的节点:"
    curl -s "$CLASH_API/proxies/$PROXY_GROUP" | \
    python3 -c "
import json, sys
data = json.load(sys.stdin)
current = data.get('now', '未知')
print(f'当前节点: {current}')
"
}

# 切换节点
switch_node() {
    local node_name="$1"
    if [ -z "$node_name" ]; then
        echo "错误: 请指定节点名称"
        echo "使用 '$0 list' 查看可用节点"
        return 1
    fi
    
    echo "正在切换到节点: $node_name"
    result=$(curl -s -X PUT "$CLASH_API/proxies/$PROXY_GROUP" \
        -H "Content-Type: application/json" \
        -d "{\"name\": \"$node_name\"}")
    
    if [ $? -eq 0 ]; then
        echo "✅ 节点切换成功!"
        show_current
    else
        echo "❌ 节点切换失败"
        return 1
    fi
}

# 测试当前节点连接
test_connection() {
    echo "测试当前节点连接..."
    echo "1. 测试代理连接:"
    if curl -x http://localhost:7890 -s --connect-timeout 10 \
       "https://www.google.com" > /dev/null; then
        echo "✅ 代理连接正常"
    else
        echo "❌ 代理连接失败"
    fi
    
    echo "2. 测试OpenStreetMap API:"
    if curl -x http://localhost:7890 -s --connect-timeout 10 \
       "https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=40&lon=116" > /dev/null; then
        echo "✅ OpenStreetMap API连接正常"
    else
        echo "❌ OpenStreetMap API连接失败"
    fi
}

# 交互式节点选择
interactive_switch() {
    echo "=== 交互式节点选择 ==="
    
    # 获取节点列表
    nodes=$(curl -s "$CLASH_API/proxies/$PROXY_GROUP" | \
    python3 -c "
import json, sys
data = json.load(sys.stdin)
if 'all' in data:
    for node in data['all']:
        print(node)
" 2>/dev/null)
    
    if [ -z "$nodes" ]; then
        echo "❌ 无法获取节点列表"
        return 1
    fi
    
    # 显示节点列表
    echo "可用节点:"
    echo "$nodes" | nl -w2 -s'. '
    
    # 让用户选择
    echo ""
    read -p "请输入节点序号: " choice
    
    if [[ "$choice" =~ ^[0-9]+$ ]]; then
        selected_node=$(echo "$nodes" | sed -n "${choice}p")
        if [ -n "$selected_node" ]; then
            switch_node "$selected_node"
        else
            echo "❌ 无效的序号"
        fi
    else
        echo "❌ 请输入有效的数字"
    fi
}

# 主函数
main() {
    case "$1" in
        "list"|"l")
            list_nodes
            ;;
        "current"|"c")
            show_current
            ;;
        "switch"|"s")
            if [ -n "$2" ]; then
                switch_node "$2"
            else
                interactive_switch
            fi
            ;;
        "test"|"t")
            test_connection
            ;;
        "help"|"h"|"--help"|"-h")
            show_help
            ;;
        "")
            show_help
            ;;
        *)
            echo "❌ 未知参数: $1"
            show_help
            return 1
            ;;
    esac
}

# 检查依赖
if ! command -v curl &> /dev/null; then
    echo "❌ 错误: 需要安装curl"
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 需要安装python3"
    exit 1
fi

# 运行主函数
main "$@" 