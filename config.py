#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Discord中文抽奖机器人配置管理
"""

import os
from dotenv import load_dotenv
import logging

# 加载环境变量
load_dotenv()

class Config:
    """配置类"""
    
    # Discord配置
    DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
    BOT_PREFIX = os.getenv('BOT_PREFIX', '!')
    
    # 数据库配置
    DATABASE_NAME = os.getenv('DATABASE_NAME', 'lottery_bot.db')
    
    # 日志配置
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # 抽奖配置
    MAX_LOTTERY_TITLE_LENGTH = 100
    MAX_LOTTERY_DESCRIPTION_LENGTH = 500
    MAX_PRIZE_COUNT = 20
    MAX_PARTICIPANTS_LIMIT = 10000
    MAX_RANDOM_CHOICES = 20
    MAX_RANDOM_NUMBERS = 10
    MAX_RANDOM_RANGE = 1000000
    
    # 权限配置
    ADMIN_PERMISSIONS = ['manage_messages', 'administrator']
    
    # 颜色配置
    COLORS = {
        'primary': 0x4ecdc4,      # 青绿色
        'success': 0x4ecdc4,      # 成功 - 青绿色
        'error': 0xff6b6b,        # 错误 - 红色
        'warning': 0xffa726,      # 警告 - 橙色
        'info': 0x95a5a6,         # 信息 - 灰色
        'secondary': 0x95a5a6     # 次要 - 灰色
    }
    
    # 表情符号配置
    EMOJIS = {
        'lottery': '🎲',
        'prize': '🏆',
        'winner': '🎉',
        'participant': '👥',
        'time': '⏰',
        'stats': '📊',
        'tools': '🛠️',
        'success': '✅',
        'error': '❌',
        'warning': '⚠️',
        'info': 'ℹ️',
        'random': '🎯',
        'number': '🔢'
    }
    
    @classmethod
    def validate_config(cls):
        """验证配置"""
        errors = []
        
        if not cls.DISCORD_TOKEN:
            errors.append("DISCORD_TOKEN未设置")
        
        if cls.DISCORD_TOKEN == 'your_discord_bot_token_here':
            errors.append("请设置有效的DISCORD_TOKEN")
        
        # 验证日志级别
        valid_log_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if cls.LOG_LEVEL not in valid_log_levels:
            errors.append(f"无效的LOG_LEVEL: {cls.LOG_LEVEL}")
        
        return errors
    
    @classmethod
    def setup_logging(cls):
        """设置日志"""
        logging.basicConfig(
            level=getattr(logging, cls.LOG_LEVEL),
            format=cls.LOG_FORMAT,
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('bot.log', encoding='utf-8')
            ]
        )
        
        # 设置discord.py日志级别
        discord_logger = logging.getLogger('discord')
        discord_logger.setLevel(logging.WARNING)
        
        return logging.getLogger(__name__)

# 创建全局配置实例
config = Config()

# 验证配置
config_errors = config.validate_config()
if config_errors:
    print("❌ 配置错误:")
    for error in config_errors:
        print(f"  - {error}")
    exit(1)
