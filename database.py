#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Discord中文抽奖机器人数据库工具
"""

import sqlite3
import json
import datetime
import logging
from typing import List, Dict, Optional, Tuple
from config import config

logger = logging.getLogger(__name__)

class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self, db_name: str = None):
        self.db_name = db_name or config.DATABASE_NAME
        self.conn = None
        self.init_database()
    
    def init_database(self):
        """初始化数据库连接和表结构"""
        try:
            self.conn = sqlite3.connect(self.db_name, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row  # 使结果可以通过列名访问
            self.create_tables()
            logger.info(f"数据库初始化成功: {self.db_name}")
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")
            raise
    
    def create_tables(self):
        """创建数据库表"""
        cursor = self.conn.cursor()
        
        # 抽奖表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS lotteries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                creator_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                prizes TEXT NOT NULL,  -- JSON格式存储奖品
                max_participants INTEGER DEFAULT -1,
                end_time TIMESTAMP,
                status TEXT DEFAULT 'active',  -- active, ended, cancelled
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                winner_selection_method TEXT DEFAULT 'random',  -- random, weighted
                allow_multiple_entries BOOLEAN DEFAULT FALSE,
                required_roles TEXT,  -- JSON格式存储需要的角色ID
                blacklisted_users TEXT,  -- JSON格式存储黑名单用户ID
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 参与者表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lottery_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                discord_id TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                weight INTEGER DEFAULT 1,
                FOREIGN KEY (lottery_id) REFERENCES lotteries (id),
                UNIQUE(lottery_id, user_id)
            )
        ''')
        
        # 中奖记录表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS winners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lottery_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                prize_name TEXT NOT NULL,
                won_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (lottery_id) REFERENCES lotteries (id)
            )
        ''')
        
        # 统计表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                total_lotteries INTEGER DEFAULT 0,
                total_participants INTEGER DEFAULT 0,
                total_winners INTEGER DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id)
            )
        ''')
        
        # 创建索引以提高查询性能
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_lotteries_guild_id ON lotteries(guild_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_lotteries_status ON lotteries(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_participants_lottery_id ON participants(lottery_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_participants_user_id ON participants(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_winners_lottery_id ON winners(lottery_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_winners_user_id ON winners(user_id)')
        
        self.conn.commit()
        logger.info("数据库表创建完成")
    
    def create_lottery(self, guild_id: int, channel_id: int, creator_id: int, 
                      title: str, prizes: List[Dict], description: str = None,
                      max_participants: int = -1, end_time: datetime.datetime = None,
                      allow_multiple: bool = False, required_roles: List[int] = None) -> int:
        """创建抽奖"""
        cursor = self.conn.cursor()
        
        prizes_json = json.dumps(prizes, ensure_ascii=False)
        required_roles_json = json.dumps(required_roles) if required_roles else None
        
        cursor.execute('''
            INSERT INTO lotteries (
                guild_id, channel_id, creator_id, title, description, prizes,
                max_participants, end_time, allow_multiple_entries, required_roles
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            guild_id, channel_id, creator_id, title, description or "无描述",
            prizes_json, max_participants, end_time, allow_multiple, required_roles_json
        ))
        
        lottery_id = cursor.lastrowid
        self.conn.commit()
        
        # 更新统计
        self.update_guild_stats(guild_id)
        
        logger.info(f"创建抽奖成功: ID={lottery_id}, 标题={title}")
        return lottery_id
    
    def join_lottery(self, lottery_id: int, user_id: int, discord_id: str = None) -> bool:
        """参与抽奖"""
        cursor = self.conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO participants (lottery_id, user_id, discord_id)
                VALUES (?, ?, ?)
            ''', (lottery_id, user_id, discord_id or str(user_id)))
            
            self.conn.commit()
            logger.info(f"用户 {user_id} 参与抽奖 {lottery_id}")
            return True
            
        except sqlite3.IntegrityError:
            # 用户已参与
            return False
    
    def increase_participation_weight(self, lottery_id: int, user_id: int) -> bool:
        """增加参与权重（重复参与）"""
        cursor = self.conn.cursor()
        
        cursor.execute('''
            UPDATE participants SET weight = weight + 1 
            WHERE lottery_id = ? AND user_id = ?
        ''', (lottery_id, user_id))
        
        if cursor.rowcount > 0:
            self.conn.commit()
            logger.info(f"用户 {user_id} 在抽奖 {lottery_id} 中增加权重")
            return True
        return False
    
    def get_lottery(self, lottery_id: int, guild_id: int = None) -> Optional[Dict]:
        """获取抽奖信息"""
        cursor = self.conn.cursor()
        
        query = 'SELECT * FROM lotteries WHERE id = ?'
        params = [lottery_id]
        
        if guild_id:
            query += ' AND guild_id = ?'
            params.append(guild_id)
        
        cursor.execute(query, params)
        row = cursor.fetchone()
        
        if row:
            lottery = dict(row)
            lottery['prizes'] = json.loads(lottery['prizes'])
            if lottery['required_roles']:
                lottery['required_roles'] = json.loads(lottery['required_roles'])
            return lottery
        return None
    
    def get_active_lotteries(self, guild_id: int, limit: int = 10) -> List[Dict]:
        """获取活跃抽奖列表"""
        cursor = self.conn.cursor()
        
        cursor.execute('''
            SELECT * FROM lotteries 
            WHERE guild_id = ? AND status = 'active'
            ORDER BY created_at DESC
            LIMIT ?
        ''', (guild_id, limit))
        
        lotteries = []
        for row in cursor.fetchall():
            lottery = dict(row)
            lottery['prizes'] = json.loads(lottery['prizes'])
            if lottery['required_roles']:
                lottery['required_roles'] = json.loads(lottery['required_roles'])
            lotteries.append(lottery)
        
        return lotteries
    
    def get_participants(self, lottery_id: int) -> List[Tuple[int, int]]:
        """获取抽奖参与者 (user_id, weight)"""
        cursor = self.conn.cursor()
        
        cursor.execute('''
            SELECT user_id, weight FROM participants 
            WHERE lottery_id = ?
        ''', (lottery_id,))
        
        return cursor.fetchall()
    
    def get_participant_count(self, lottery_id: int) -> int:
        """获取参与者数量"""
        cursor = self.conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) FROM participants WHERE lottery_id = ?
        ''', (lottery_id,))
        
        return cursor.fetchone()[0]
    
    def add_winners(self, lottery_id: int, winners: List[Tuple[int, str]]):
        """添加中奖记录"""
        cursor = self.conn.cursor()
        
        cursor.executemany('''
            INSERT INTO winners (lottery_id, user_id, prize_name)
            VALUES (?, ?, ?)
        ''', [(lottery_id, user_id, prize_name) for user_id, prize_name in winners])
        
        self.conn.commit()
        logger.info(f"添加中奖记录: 抽奖ID={lottery_id}, 中奖人数={len(winners)}")
    
    def update_lottery_status(self, lottery_id: int, status: str):
        """更新抽奖状态"""
        cursor = self.conn.cursor()
        
        cursor.execute('''
            UPDATE lotteries SET status = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE id = ?
        ''', (status, lottery_id))
        
        self.conn.commit()
        logger.info(f"抽奖 {lottery_id} 状态更新为: {status}")
    
    def get_user_stats(self, user_id: int, guild_id: int) -> Dict:
        """获取用户统计信息"""
        cursor = self.conn.cursor()
        
        # 参与次数
        cursor.execute('''
            SELECT COUNT(DISTINCT lottery_id) FROM participants 
            WHERE user_id = ? AND lottery_id IN (
                SELECT id FROM lotteries WHERE guild_id = ?
            )
        ''', (user_id, guild_id))
        participated_count = cursor.fetchone()[0]
        
        # 中奖次数
        cursor.execute('''
            SELECT COUNT(*) FROM winners 
            WHERE user_id = ? AND lottery_id IN (
                SELECT id FROM lotteries WHERE guild_id = ?
            )
        ''', (user_id, guild_id))
        won_count = cursor.fetchone()[0]
        
        # 最近中奖记录
        cursor.execute('''
            SELECT l.title, w.prize_name, w.won_at 
            FROM winners w
            JOIN lotteries l ON w.lottery_id = l.id
            WHERE w.user_id = ? AND l.guild_id = ?
            ORDER BY w.won_at DESC
            LIMIT 5
        ''', (user_id, guild_id))
        recent_wins = cursor.fetchall()
        
        return {
            'participated_count': participated_count,
            'won_count': won_count,
            'win_rate': (won_count / participated_count * 100) if participated_count > 0 else 0,
            'recent_wins': [dict(row) for row in recent_wins]
        }
    
    def get_guild_stats(self, guild_id: int) -> Dict:
        """获取服务器统计信息"""
        cursor = self.conn.cursor()
        
        # 基本统计
        cursor.execute('SELECT COUNT(*) FROM lotteries WHERE guild_id = ?', (guild_id,))
        total_lotteries = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM lotteries WHERE guild_id = ? AND status = "active"', (guild_id,))
        active_lotteries = cursor.fetchone()[0]
        
        cursor.execute('''
            SELECT COUNT(*) FROM participants p
            JOIN lotteries l ON p.lottery_id = l.id
            WHERE l.guild_id = ?
        ''', (guild_id,))
        total_participations = cursor.fetchone()[0]
        
        cursor.execute('''
            SELECT COUNT(*) FROM winners w
            JOIN lotteries l ON w.lottery_id = l.id
            WHERE l.guild_id = ?
        ''', (guild_id,))
        total_wins = cursor.fetchone()[0]
        
        # 最活跃用户
        cursor.execute('''
            SELECT p.user_id, COUNT(*) as participation_count
            FROM participants p
            JOIN lotteries l ON p.lottery_id = l.id
            WHERE l.guild_id = ?
            GROUP BY p.user_id
            ORDER BY participation_count DESC
            LIMIT 5
        ''', (guild_id,))
        top_participants = cursor.fetchall()
        
        # 最幸运用户
        cursor.execute('''
            SELECT w.user_id, COUNT(*) as win_count
            FROM winners w
            JOIN lotteries l ON w.lottery_id = l.id
            WHERE l.guild_id = ?
            GROUP BY w.user_id
            ORDER BY win_count DESC
            LIMIT 5
        ''', (guild_id,))
        top_winners = cursor.fetchall()
        
        return {
            'total_lotteries': total_lotteries,
            'active_lotteries': active_lotteries,
            'completed_lotteries': total_lotteries - active_lotteries,
            'total_participations': total_participations,
            'total_wins': total_wins,
            'average_win_rate': (total_wins / total_participations * 100) if total_participations > 0 else 0,
            'top_participants': [dict(row) for row in top_participants],
            'top_winners': [dict(row) for row in top_winners]
        }
    
    def update_guild_stats(self, guild_id: int):
        """更新服务器统计"""
        cursor = self.conn.cursor()
        
        stats = self.get_guild_stats(guild_id)
        
        cursor.execute('''
            INSERT OR REPLACE INTO statistics 
            (guild_id, total_lotteries, total_participants, total_winners, last_updated)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (guild_id, stats['total_lotteries'], stats['total_participations'], stats['total_wins']))
        
        self.conn.commit()
    
    def get_expired_lotteries(self) -> List[Dict]:
        """获取已过期的抽奖"""
        cursor = self.conn.cursor()
        current_time = datetime.datetime.now()
        
        cursor.execute('''
            SELECT * FROM lotteries 
            WHERE status = 'active' AND end_time <= ? AND end_time IS NOT NULL
        ''', (current_time,))
        
        lotteries = []
        for row in cursor.fetchall():
            lottery = dict(row)
            lottery['prizes'] = json.loads(lottery['prizes'])
            lotteries.append(lottery)
        
        return lotteries
    
    def cleanup_old_data(self, days: int = 90):
        """清理旧数据"""
        cursor = self.conn.cursor()
        cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days)
        
        # 删除旧的已结束抽奖及相关数据
        cursor.execute('''
            DELETE FROM winners WHERE lottery_id IN (
                SELECT id FROM lotteries 
                WHERE status IN ('ended', 'cancelled') AND updated_at < ?
            )
        ''', (cutoff_date,))
        
        cursor.execute('''
            DELETE FROM participants WHERE lottery_id IN (
                SELECT id FROM lotteries 
                WHERE status IN ('ended', 'cancelled') AND updated_at < ?
            )
        ''', (cutoff_date,))
        
        cursor.execute('''
            DELETE FROM lotteries 
            WHERE status IN ('ended', 'cancelled') AND updated_at < ?
        ''', (cutoff_date,))
        
        deleted_count = cursor.rowcount
        self.conn.commit()
        
        logger.info(f"清理了 {deleted_count} 条旧数据记录")
        return deleted_count
    
    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            logger.info("数据库连接已关闭")

# 创建全局数据库管理器实例
db_manager = DatabaseManager()
