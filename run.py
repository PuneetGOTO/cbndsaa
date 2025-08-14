#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Discord抽奖机器人简单启动器
解决Windows中文编码问题
"""

import os
import sys
import subprocess
import platform

def main():
    print("=" * 50)
    print("Discord Lottery Bot - Simple Launcher")
    print("=" * 50)
    print()
    
    # 检查Python版本
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print(f"[ERROR] Python 3.8+ required, current: {version.major}.{version.minor}")
        input("Press Enter to exit...")
        return
    
    print(f"[OK] Python {version.major}.{version.minor}.{version.micro}")
    
    # 检查.env文件
    if not os.path.exists('.env'):
        if os.path.exists('.env.example'):
            print("[INFO] Creating .env from .env.example...")
            try:
                with open('.env.example', 'r', encoding='utf-8') as src:
                    content = src.read()
                with open('.env', 'w', encoding='utf-8') as dst:
                    dst.write(content)
                print("[OK] .env file created")
                print()
                print("[WARNING] Please edit .env file and set your DISCORD_TOKEN")
                print("Then run this script again.")
                input("Press Enter to exit...")
                return
            except Exception as e:
                print(f"[ERROR] Failed to create .env: {e}")
                input("Press Enter to exit...")
                return
        else:
            print("[ERROR] .env.example not found")
            input("Press Enter to exit...")
            return
    
    # 检查Token
    try:
        from dotenv import load_dotenv
        load_dotenv()
        token = os.getenv('DISCORD_TOKEN')
        if not token or token == 'your_discord_bot_token_here':
            print("[ERROR] Please set DISCORD_TOKEN in .env file")
            input("Press Enter to exit...")
            return
    except ImportError:
        print("[INFO] Installing python-dotenv...")
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'python-dotenv'])
    
    # 安装依赖
    if os.path.exists('requirements.txt'):
        print("[INFO] Installing dependencies...")
        try:
            result = subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'], 
                                  capture_output=True, text=True)
            if result.returncode != 0:
                print(f"[ERROR] Failed to install dependencies: {result.stderr}")
                input("Press Enter to exit...")
                return
            print("[OK] Dependencies installed")
        except Exception as e:
            print(f"[ERROR] Installation failed: {e}")
            input("Press Enter to exit...")
            return
    
    print()
    print("[INFO] Starting Discord Lottery Bot...")
    print("=" * 50)
    print()
    
    # 启动机器人
    try:
        import bot
    except KeyboardInterrupt:
        print("\n[INFO] Bot stopped by user")
    except Exception as e:
        print(f"\n[ERROR] Bot failed to start: {e}")
        input("Press Enter to exit...")

if __name__ == "__main__":
    main()
