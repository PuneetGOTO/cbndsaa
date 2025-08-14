#!/bin/bash
#
# This script is used to manually start the Discord Lottery Bot.
# It ensures that the bot runs within its dedicated Python virtual environment.

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Activate the virtual environment
source "${SCRIPT_DIR}/venv/bin/activate"

# Run the bot
python3 "${SCRIPT_DIR}/bot.py"


# Discord中文抽奖机器人 - Linux/Ubuntu启动脚本

echo "=========================================="
echo "   Discord中文抽奖机器人 - Linux启动脚本"
echo "=========================================="
echo

# 检查Python3是否安装
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到Python3，请先安装"
    echo "Ubuntu/Debian: sudo apt install python3 python3-pip"
    echo "CentOS/RHEL: sudo yum install python3 python3-pip"
    exit 1
fi

echo "✅ Python3已安装: $(python3 --version)"

# 检查pip3是否安装
if ! command -v pip3 &> /dev/null; then
    echo "❌ 错误: 未找到pip3，请先安装"
    echo "Ubuntu/Debian: sudo apt install python3-pip"
    exit 1
fi

echo "✅ pip3已安装"
echo

# 检查requirements.txt是否存在
if [ ! -f "requirements.txt" ]; then
    echo "❌ 错误: 未找到requirements.txt文件"
    exit 1
fi

# 检查.env文件是否存在
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "⚠️  未找到.env文件，正在从.env.example创建..."
        cp .env.example .env
        echo "✅ .env文件创建成功"
        echo
        echo "⚠️  请编辑.env文件并设置您的DISCORD_TOKEN"
        echo "使用以下命令编辑: nano .env 或 vim .env"
        echo "编辑完成后，请重新运行此脚本"
        exit 0
    else
        echo "❌ 错误: 未找到.env.example文件"
        exit 1
    fi
fi

echo "🔧 正在检查并安装依赖包..."

# 创建虚拟环境（可选）
if [ ! -d "venv" ]; then
    echo "📦 创建Python虚拟环境..."
    python3 -m venv venv
    echo "✅ 虚拟环境创建成功"
fi

# 激活虚拟环境
echo "🔄 激活虚拟环境..."
source venv/bin/activate

# 安装依赖包
pip3 install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "❌ 依赖包安装失败"
    exit 1
fi

echo
echo "✅ 依赖包检查完成"
echo
echo "🚀 正在启动Discord抽奖机器人..."
echo "=========================================="
echo

# 启动机器人
python3 bot.py

echo
echo "👋 机器人已停止运行"
