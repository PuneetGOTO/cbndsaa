#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Discord中文抽奖机器人启动脚本
支持Windows和Ubuntu系统
"""

import os
import sys
import platform
import subprocess
import logging

def check_python_version():
    """检查Python版本"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print("❌ 错误: 需要Python 3.8或更高版本")
        print(f"当前版本: Python {version.major}.{version.minor}.{version.micro}")
        return False
    print(f"✅ Python版本检查通过: {version.major}.{version.minor}.{version.micro}")
    return True

def check_dependencies():
    """检查依赖包"""
    required_packages = [
        'discord.py',
        'python-dotenv'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
            print(f"✅ {package} 已安装")
        except ImportError:
            missing_packages.append(package)
            print(f"❌ {package} 未安装")
    
    return missing_packages

def install_dependencies():
    """安装依赖包"""
    print("🔧 正在安装依赖包...")
    
    try:
        # 确定pip命令
        pip_cmd = 'pip3' if platform.system() != 'Windows' else 'pip'
        
        # 尝试使用pip安装
        result = subprocess.run([pip_cmd, 'install', '-r', 'requirements.txt'], 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ 依赖包安装成功")
            return True
        else:
            print(f"❌ 安装失败: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ 安装过程中出现错误: {e}")
        return False

def check_env_file():
    """检查环境配置文件"""
    if not os.path.exists('.env'):
        if os.path.exists('.env.example'):
            print("⚠️  未找到.env文件，正在从.env.example创建...")
            try:
                with open('.env.example', 'r', encoding='utf-8') as example:
                    content = example.read()
                with open('.env', 'w', encoding='utf-8') as env_file:
                    env_file.write(content)
                print("✅ .env文件创建成功")
                print("⚠️  请编辑.env文件并设置您的DISCORD_TOKEN")
                return False
            except Exception as e:
                print(f"❌ 创建.env文件失败: {e}")
                return False
        else:
            print("❌ 未找到.env.example文件")
            return False
    
    # 检查TOKEN是否已设置
    from dotenv import load_dotenv
    load_dotenv()
    
    token = os.getenv('DISCORD_TOKEN')
    if not token or token == 'your_discord_bot_token_here':
        print("❌ 请在.env文件中设置有效的DISCORD_TOKEN")
        return False
    
    print("✅ 环境配置检查通过")
    return True

def main():
    """主函数"""
    print("🎲 Discord中文抽奖机器人启动检查")
    print("=" * 50)
    
    # 检查Python版本
    if not check_python_version():
        sys.exit(1)
    
    # 检查依赖包
    missing_packages = check_dependencies()
    if missing_packages:
        print(f"\n⚠️  发现缺失的依赖包: {', '.join(missing_packages)}")
        response = input("是否自动安装缺失的依赖包? (y/n): ").lower().strip()
        
        if response in ['y', 'yes', '是', 'Y']:
            if not install_dependencies():
                print("❌ 依赖包安装失败，请手动安装")
                sys.exit(1)
        else:
            print("❌ 请手动安装依赖包: pip install -r requirements.txt")
            sys.exit(1)
    
    # 检查环境配置
    if not check_env_file():
        sys.exit(1)
    
    print("\n🚀 所有检查通过，正在启动机器人...")
    print("=" * 50)
    
    # 启动机器人
    try:
        import bot
    except KeyboardInterrupt:
        print("\n👋 机器人已停止")
    except Exception as e:
        print(f"\n❌ 启动失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
