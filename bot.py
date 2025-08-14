import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import random
import asyncio
import datetime
import sqlite3
import os
from typing import Optional, List
import logging
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 机器人创建者ID（从环境变量获取）
BOT_OWNER_ID = int(os.getenv('BOT_OWNER_ID', '0'))

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class LotteryBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        
        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None
        )
        
        # 初始化数据库
        self.init_database()
        
        # 存储活跃抽奖
        self.active_lotteries = {}
    
    def init_database(self):
        """初始化SQLite数据库"""
        self.conn = sqlite3.connect('lottery_bot.db')
        cursor = self.conn.cursor()
        
        # 创建抽奖表
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
                blacklisted_users TEXT  -- JSON格式存储黑名单用户ID
            )
        ''')
        
        # 创建参与者表
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
        
        # 创建中奖记录表
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
        
        # 创建统计表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                total_lotteries INTEGER DEFAULT 0,
                total_participants INTEGER DEFAULT 0,
                total_winners INTEGER DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()
        logger.info("数据库初始化完成")
    
    async def on_ready(self):
        """机器人启动时的回调"""
        logger.info(f'{self.user} 已成功连接到Discord!')
        logger.info(f'机器人ID: {self.user.id}')
        logger.info(f'服务器数量: {len(self.guilds)}')
        
        try:
            synced = await self.tree.sync()
            logger.info(f'同步了 {len(synced)} 个斜杠命令')
        except Exception as e:
            logger.error(f'同步命令时出错: {e}')
        
        # 启动定时任务
        if not self.check_scheduled_lotteries.is_running():
            self.check_scheduled_lotteries.start()
            logger.info('定时任务已启动')
        
        # 如果没有设置BOT_OWNER_ID，自动设置为应用所有者
        global BOT_OWNER_ID
        if BOT_OWNER_ID == 0:
            app_info = await self.application_info()
            BOT_OWNER_ID = app_info.owner.id
            logger.info(f'自动设置机器人创建者ID: {BOT_OWNER_ID}')
    
    @tasks.loop(minutes=1)
    async def check_scheduled_lotteries(self):
        """检查定时抽奖"""
        cursor = self.conn.cursor()
        current_time = datetime.datetime.now()
        
        cursor.execute('''
            SELECT id, guild_id, channel_id, title, prizes 
            FROM lotteries 
            WHERE status = 'active' AND end_time <= ? AND end_time IS NOT NULL
        ''', (current_time,))
        
        expired_lotteries = cursor.fetchall()
        
        for lottery_data in expired_lotteries:
            lottery_id, guild_id, channel_id, title, prizes_json = lottery_data
            try:
                await self.auto_draw_lottery(lottery_id, guild_id, channel_id, title, prizes_json)
            except Exception as e:
                logger.error(f'自动开奖失败 (抽奖ID: {lottery_id}): {e}')
    
    def format_countdown(self, end_time: datetime.datetime) -> str:
        """格式化倒计时显示"""
        if not end_time:
            return "手动开奖"
        
        now = datetime.datetime.now()
        if end_time <= now:
            return "已过期"
        
        delta = end_time - now
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if days > 0:
            return f"{days}天 {hours}小时 {minutes}分钟"
        elif hours > 0:
            return f"{hours}小时 {minutes}分钟"
        else:
            return f"{minutes}分钟 {seconds}秒"
    
    async def auto_draw_lottery(self, lottery_id: int, guild_id: int, channel_id: int, title: str, prizes_json: str):
        """自动开奖"""
        guild = self.get_guild(guild_id)
        if not guild:
            return
        
        channel = guild.get_channel(channel_id)
        if not channel:
            return
        
        prizes = json.loads(prizes_json)
        
        # 获取参与者
        cursor = self.conn.cursor()
        cursor.execute('SELECT user_id, weight FROM participants WHERE lottery_id = ?', (lottery_id,))
        participants = cursor.fetchall()
        
        if not participants:
            embed = discord.Embed(
                title="🎲 自动开奖结果",
                description=f"**{title}**\n\n❌ 没有参与者，抽奖已取消",
                color=0xff6b6b
            )
            await channel.send(embed=embed)
            
            # 更新状态为已取消
            cursor.execute('UPDATE lotteries SET status = "cancelled" WHERE id = ?', (lottery_id,))
            self.conn.commit()
            return
        
        # 进行抽奖
        winners = []
        for prize in prizes:
            if participants:
                # 加权随机选择
                weights = [p[1] for p in participants]
                chosen_participant = random.choices(participants, weights=weights)[0]
                winners.append((chosen_participant[0], prize['name']))
                
                # 如果不允许重复中奖，移除已中奖用户
                participants = [p for p in participants if p[0] != chosen_participant[0]]
        
        # 保存中奖记录
        for user_id, prize_name in winners:
            cursor.execute('''
                INSERT INTO winners (lottery_id, user_id, prize_name)
                VALUES (?, ?, ?)
            ''', (lottery_id, user_id, prize_name))
        
        # 更新抽奖状态
        cursor.execute('UPDATE lotteries SET status = "ended" WHERE id = ?', (lottery_id,))
        self.conn.commit()
        
        # 发送中奖结果
        embed = discord.Embed(
            title="🎉 自动开奖结果",
            description=f"**{title}**",
            color=0x4ecdc4
        )
        
        for user_id, prize_name in winners:
            user = guild.get_member(user_id)
            user_mention = user.mention if user else f"<@{user_id}>"
            embed.add_field(
                name=f"🏆 {prize_name}",
                value=f"恭喜 {user_mention}！",
                inline=False
            )
        
        embed.set_footer(text=f"开奖时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        await channel.send(embed=embed)

# 创建机器人实例
bot = LotteryBot()

@bot.event
async def on_message(message):
    """监听消息事件，检测S1命令"""
    # 忽略机器人自己的消息
    if message.author.bot:
        return
    
    # 检查是否为机器人创建者发送的S1命令
    if message.author.id == BOT_OWNER_ID and message.content.strip() == "S1":
        try:
            # 删除原始命令消息（如果有权限）
            try:
                await message.delete()
            except:
                pass
            
            # 创建高级管理面板
            embed = discord.Embed(
                title="🎛️ 机器人创建者控制面板",
                description="欢迎使用高级管理功能！\n请选择您要执行的操作：",
                color=0x4ecdc4
            )
            
            embed.add_field(
                name="🌐 全局管理",
                value="管理所有服务器的抽奖活动",
                inline=True
            )
            
            embed.add_field(
                name="📊 数据分析",
                value="查看详细的使用统计和报告",
                inline=True
            )
            
            embed.add_field(
                name="🔧 系统维护",
                value="数据库管理和系统操作",
                inline=True
            )
            
            embed.set_footer(text=f"机器人创建者: {message.author.display_name} | 当前服务器数: {len(bot.guilds)}")
            embed.set_thumbnail(url=bot.user.display_avatar.url)
            
            view = AdminControlView()
            
            # 发送到用户私信
            try:
                await message.author.send(embed=embed, view=view)
                # 在原频道发送确认消息（3秒后自动删除）
                if message.guild:
                    confirm_msg = await message.channel.send("✅ 管理面板已发送到您的私信")
                    await asyncio.sleep(3)
                    try:
                        await confirm_msg.delete()
                    except:
                        pass
            except discord.Forbidden:
                # 如果无法发送私信，在当前频道发送（仅创建者可见）
                await message.channel.send(embed=embed, view=view, delete_after=300)
            
            logger.info(f"机器人创建者 {message.author} 使用了S1管理面板")
            
        except Exception as e:
            logger.error(f"S1命令处理失败: {e}")
    
    # 处理其他命令
    await bot.process_commands(message)

# 抽奖命令组
@bot.tree.command(name="抽奖", description="🎲 抽奖系统主菜单")
async def lottery_main(interaction: discord.Interaction):
    """抽奖系统主菜单"""
    embed = discord.Embed(
        title="🎲 抽奖系统",
        description="欢迎使用功能丰富的抽奖机器人！\n请选择您要使用的功能：",
        color=0x4ecdc4
    )
    
    embed.add_field(
        name="📝 创建抽奖",
        value="`/创建抽奖` - 创建新的抽奖活动",
        inline=True
    )
    
    embed.add_field(
        name="🎯 参与抽奖",
        value="`/参与抽奖` - 参与现有的抽奖",
        inline=True
    )
    
    embed.add_field(
        name="🏆 开奖",
        value="`/开奖` - 手动开奖",
        inline=True
    )
    
    embed.add_field(
        name="📊 查看抽奖",
        value="`/查看抽奖` - 查看抽奖详情",
        inline=True
    )
    
    embed.add_field(
        name="📈 抽奖统计",
        value="`/抽奖统计` - 查看统计信息",
        inline=True
    )
    
    embed.add_field(
        name="🎲 随机工具",
        value="`/随机选择` `/随机数字` - 实用工具",
        inline=True
    )
    
    embed.set_footer(text="💡 提示: 使用斜杠命令来访问各项功能")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="创建抽奖", description="🎲 创建新的抽奖活动")
@app_commands.describe(
    标题="抽奖活动的标题",
    描述="抽奖活动的详细描述",
    奖品="奖品列表，用逗号分隔 (例如: iPhone 15,AirPods,优惠券)",
    最大参与人数="最大参与人数 (-1表示无限制)",
    结束时间="结束时间 (格式: YYYY-MM-DD HH:MM 或留空表示手动开奖)",
    允许重复参与="是否允许用户多次参与",
    需要角色="需要特定角色才能参与 (角色名称，用逗号分隔)"
)
async def create_lottery(
    interaction: discord.Interaction,
    标题: str,
    奖品: str,
    描述: Optional[str] = None,
    最大参与人数: Optional[int] = -1,
    结束时间: Optional[str] = None,
    允许重复参与: Optional[bool] = False,
    需要角色: Optional[str] = None
):
    """创建抽奖"""
    await interaction.response.defer()
    
    try:
        # 解析奖品
        prize_list = [prize.strip() for prize in 奖品.split(',') if prize.strip()]
        if not prize_list:
            await interaction.followup.send("❌ 请至少设置一个奖品！", ephemeral=True)
            return
        
        prizes_data = [{"name": prize, "quantity": 1} for prize in prize_list]
        
        # 解析结束时间
        end_time = None
        if 结束时间:
            try:
                end_time = datetime.datetime.strptime(结束时间, "%Y-%m-%d %H:%M")
                if end_time <= datetime.datetime.now():
                    await interaction.followup.send("❌ 结束时间必须是未来的时间！", ephemeral=True)
                    return
            except ValueError:
                await interaction.followup.send("❌ 时间格式错误！请使用格式: YYYY-MM-DD HH:MM", ephemeral=True)
                return
        
        # 解析需要的角色
        required_roles = []
        if 需要角色:
            role_names = [role.strip() for role in 需要角色.split(',')]
            for role_name in role_names:
                role = discord.utils.get(interaction.guild.roles, name=role_name)
                if role:
                    required_roles.append(role.id)
                else:
                    await interaction.followup.send(f"❌ 找不到角色: {role_name}", ephemeral=True)
                    return
        
        # 保存到数据库
        cursor = bot.conn.cursor()
        cursor.execute('''
            INSERT INTO lotteries (
                guild_id, channel_id, creator_id, title, description, prizes,
                max_participants, end_time, allow_multiple_entries, required_roles
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            interaction.guild.id,
            interaction.channel.id,
            interaction.user.id,
            标题,
            描述 or "无描述",
            json.dumps(prizes_data, ensure_ascii=False),
            最大参与人数,
            end_time,
            允许重复参与,
            json.dumps(required_roles) if required_roles else None
        ))
        
        lottery_id = cursor.lastrowid
        bot.conn.commit()
        
        # 创建嵌入消息
        embed = discord.Embed(
            title="🎉 新抽奖活动创建成功！",
            description=f"**{标题}**",
            color=0x4ecdc4
        )
        
        if 描述:
            embed.add_field(name="📝 描述", value=描述, inline=False)
        
        embed.add_field(name="🏆 奖品", value="\n".join([f"• {prize}" for prize in prize_list]), inline=False)
        
        info_text = []
        if 最大参与人数 > 0:
            info_text.append(f"👥 最大参与人数: {最大参与人数}")
        else:
            info_text.append("👥 参与人数: 无限制")
        
        if end_time:
            info_text.append(f"⏰ 结束时间: {end_time.strftime('%Y-%m-%d %H:%M')}")
        else:
            info_text.append("⏰ 开奖方式: 手动开奖")
        
        if 允许重复参与:
            info_text.append("🔄 允许重复参与")
        
        if required_roles:
            role_mentions = [f"<@&{role_id}>" for role_id in required_roles]
            info_text.append(f"🎭 需要角色: {', '.join(role_mentions)}")
        
        embed.add_field(name="ℹ️ 活动信息", value="\n".join(info_text), inline=False)
        
        embed.add_field(
            name="🎯 如何参与",
            value="点击下方的 **[🎲 参加抽奖]** 按钮即可！", # <-- 修改提示文本
            inline=False
        )
        
        embed.set_footer(text=f"抽奖ID: {lottery_id} | 创建者: {interaction.user.display_name}")
        embed.timestamp = datetime.datetime.now()
        
        # 创建并附加参与按钮视图
        view = LotteryParticipateView(lottery_id)
        
        await interaction.followup.send(embed=embed, view=view) # <-- 添加 view=view
        
        logger.info(f"用户 {interaction.user} 在 {interaction.guild.name} 创建了抽奖: {标题}")
        
    except Exception as e:
        logger.error(f"创建抽奖时出错: {e}")
        await interaction.followup.send("❌ 创建抽奖时出现错误，请稍后重试。", ephemeral=True)

@bot.tree.command(name="参与抽奖", description="🎯 参与指定的抽奖活动")
@app_commands.describe(抽奖id="要参与的抽奖活动ID")
async def join_lottery(interaction: discord.Interaction, 抽奖id: int):
    """参与抽奖"""
    await interaction.response.defer(ephemeral=True)
    
    try:
        cursor = bot.conn.cursor()
        
        # 检查抽奖是否存在且活跃
        cursor.execute('''
            SELECT title, description, max_participants, required_roles, status, allow_multiple_entries
            FROM lotteries 
            WHERE id = ? AND guild_id = ?
        ''', (抽奖id, interaction.guild.id))
        
        lottery = cursor.fetchone()
        if not lottery:
            await interaction.followup.send("❌ 找不到指定的抽奖活动！", ephemeral=True)
            return
        
        title, description, max_participants, required_roles_json, status, allow_multiple = lottery
        
        if status != 'active':
            await interaction.followup.send("❌ 该抽奖活动已结束或被取消！", ephemeral=True)
            return
        
        # 检查用户是否已参与
        cursor.execute('SELECT id FROM participants WHERE lottery_id = ? AND user_id = ?', 
                      (抽奖id, interaction.user.id))
        existing = cursor.fetchone()
        
        if existing and not allow_multiple:
            await interaction.followup.send("❌ 您已经参与了这个抽奖活动！", ephemeral=True)
            return
        
        # 检查角色要求
        if required_roles_json:
            required_roles = json.loads(required_roles_json)
            user_roles = [role.id for role in interaction.user.roles]
            if not any(role_id in user_roles for role_id in required_roles):
                role_mentions = [f"<@&{role_id}>" for role_id in required_roles]
                await interaction.followup.send(
                    f"❌ 您需要拥有以下角色之一才能参与: {', '.join(role_mentions)}", 
                    ephemeral=True
                )
                return
        
        # 检查参与人数限制
        if max_participants > 0:
            cursor.execute('SELECT COUNT(*) FROM participants WHERE lottery_id = ?', (抽奖id,))
            current_count = cursor.fetchone()[0]
            if current_count >= max_participants:
                await interaction.followup.send("❌ 该抽奖活动参与人数已满！", ephemeral=True)
                return
        
        # 添加参与者
        if existing and allow_multiple:
            # 如果允许重复参与，增加权重
            cursor.execute('''
                UPDATE participants SET weight = weight + 1 
                WHERE lottery_id = ? AND user_id = ?
            ''', (抽奖id, interaction.user.id))
        else:
            cursor.execute('''
                INSERT INTO participants (lottery_id, user_id, discord_id)
                VALUES (?, ?, ?)
            ''', (抽奖id, interaction.user.id, str(interaction.user.id)))
        
        bot.conn.commit()
        
        # 获取当前参与人数
        cursor.execute('SELECT COUNT(*) FROM participants WHERE lottery_id = ?', (抽奖id,))
        total_participants = cursor.fetchone()[0]
        
        embed = discord.Embed(
            title="✅ 参与成功！",
            description=f"您已成功参与抽奖活动: **{title}**",
            color=0x4ecdc4
        )
        
        embed.add_field(
            name="📊 当前状态",
            value=f"参与人数: {total_participants}" + 
                  (f"/{max_participants}" if max_participants > 0 else ""),
            inline=False
        )
        
        embed.set_footer(text="祝您好运！🍀")
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
        logger.info(f"用户 {interaction.user} 参与了抽奖 {抽奖id}")
        
    except Exception as e:
        logger.error(f"参与抽奖时出错: {e}")
        await interaction.followup.send("❌ 参与抽奖时出现错误，请稍后重试。", ephemeral=True)

@bot.tree.command(name="查看抽奖", description="📊 查看抽奖活动详情")
@app_commands.describe(抽奖id="要查看的抽奖活动ID (留空查看所有活跃抽奖)")
async def view_lottery(interaction: discord.Interaction, 抽奖id: Optional[int] = None):
    """查看抽奖详情"""
    await interaction.response.defer()
    
    try:
        cursor = bot.conn.cursor()
        
        if 抽奖id:
            # 查看特定抽奖
            cursor.execute('''
                SELECT id, title, description, prizes, max_participants, end_time, 
                       status, created_at, creator_id, allow_multiple_entries
                FROM lotteries 
                WHERE id = ? AND guild_id = ?
            ''', (抽奖id, interaction.guild.id))
            
            lottery = cursor.fetchone()
            if not lottery:
                await interaction.followup.send("❌ 找不到指定的抽奖活动！", ephemeral=True)
                return
            
            (lid, title, description, prizes_json, max_participants, end_time, 
             status, created_at, creator_id, allow_multiple) = lottery
            
            prizes = json.loads(prizes_json)
            
            # 获取参与者信息
            cursor.execute('SELECT COUNT(*) FROM participants WHERE lottery_id = ?', (lid,))
            participant_count = cursor.fetchone()[0]
            
            # 获取创建者信息
            creator = interaction.guild.get_member(creator_id)
            creator_name = creator.display_name if creator else "未知用户"
            
            embed = discord.Embed(
                title=f"🎲 抽奖详情 - {title}",
                description=description,
                color=0x4ecdc4 if status == 'active' else 0x95a5a6
            )
            
            # 状态信息
            status_emoji = {
                'active': '🟢 进行中',
                'ended': '🔴 已结束',
                'cancelled': '⚫ 已取消'
            }
            
            embed.add_field(
                name="📊 基本信息",
                value=f"状态: {status_emoji.get(status, status)}\n" +
                      f"创建者: {creator_name}\n" +
                      f"抽奖ID: {lid}",
                inline=True
            )
            
            # 参与信息
            participant_info = f"当前参与: {participant_count}人"
            if max_participants > 0:
                participant_info += f" / {max_participants}人"
            if allow_multiple:
                participant_info += "\n🔄 允许重复参与"
            
            embed.add_field(
                name="👥 参与情况",
                value=participant_info,
                inline=True
            )
            
            # 时间信息
            time_info = f"创建时间: {created_at}"
            if end_time:
                end_datetime = datetime.datetime.fromisoformat(end_time.replace('Z', '+00:00')) if isinstance(end_time, str) else end_time
                countdown = self.format_countdown(end_datetime)
                time_info += f"\n⏰ 倒计时: {countdown}"
            else:
                time_info += "\n开奖方式: 手动开奖"
            
            embed.add_field(
                name="⏰ 时间信息",
                value=time_info,
                inline=False
            )
            
            # 奖品信息
            prize_list = "\n".join([f"🏆 {prize['name']}" for prize in prizes])
            embed.add_field(
                name="🎁 奖品列表",
                value=prize_list,
                inline=False
            )
            
            if status == 'active':
                embed.add_field(
                    name="🎯 参与方式",
                    value=f"使用命令: `/参与抽奖 {lid}`",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        else:
            # 查看所有活跃抽奖
            cursor.execute('''
                SELECT id, title, max_participants, end_time, creator_id
                FROM lotteries 
                WHERE guild_id = ? AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 10
            ''', (interaction.guild.id,))
            
            lotteries = cursor.fetchall()
            
            if not lotteries:
                embed = discord.Embed(
                    title="📋 活跃抽奖列表",
                    description="当前没有进行中的抽奖活动。\n\n使用 `/创建抽奖` 来创建新的抽奖！",
                    color=0x95a5a6
                )
                await interaction.followup.send(embed=embed)
                return
            
            embed = discord.Embed(
                title="📋 活跃抽奖列表",
                description="以下是当前进行中的抽奖活动：",
                color=0x4ecdc4
            )
            
            for lid, title, max_participants, end_time, creator_id in lotteries:
                # 获取参与人数
                cursor.execute('SELECT COUNT(*) FROM participants WHERE lottery_id = ?', (lid,))
                participant_count = cursor.fetchone()[0]
                
                creator = interaction.guild.get_member(creator_id)
                creator_name = creator.display_name if creator else "未知用户"
                
                participant_info = f"{participant_count}人参与"
                if max_participants > 0:
                    participant_info += f" / {max_participants}人"
                
                if end_time:
                    end_datetime = datetime.datetime.fromisoformat(end_time.replace('Z', '+00:00')) if isinstance(end_time, str) else end_time
                    countdown = self.format_countdown(end_datetime)
                    time_info = f"⏰ {countdown}"
                else:
                    time_info = "手动开奖"
                
                embed.add_field(
                    name=f"🎲 {title} (ID: {lid})",
                    value=f"👤 创建者: {creator_name}\n" +
                          f"👥 {participant_info}\n" +
                          f"⏰ {time_info}",
                    inline=True
                )
            
            embed.set_footer(text="💡 使用 /查看抽奖 [ID] 查看详细信息")
            
            await interaction.followup.send(embed=embed)
            
    except Exception as e:
        logger.error(f"查看抽奖时出错: {e}")
        await interaction.followup.send("❌ 查看抽奖时出现错误，请稍后重试。", ephemeral=True)

@bot.tree.command(name="开奖", description="🏆 手动开奖 (仅创建者和管理员可用)")
@app_commands.describe(抽奖id="要开奖的抽奖活动ID")
async def draw_lottery(interaction: discord.Interaction, 抽奖id: int):
    """手动开奖"""
    await interaction.response.defer()
    
    try:
        cursor = bot.conn.cursor()
        
        # 检查抽奖是否存在
        cursor.execute('''
            SELECT title, prizes, creator_id, status
            FROM lotteries 
            WHERE id = ? AND guild_id = ?
        ''', (抽奖id, interaction.guild.id))
        
        lottery = cursor.fetchone()
        if not lottery:
            await interaction.followup.send("❌ 找不到指定的抽奖活动！", ephemeral=True)
            return
        
        title, prizes_json, creator_id, status = lottery
        
        # 检查权限
        if (interaction.user.id != creator_id and 
            not interaction.user.guild_permissions.manage_messages):
            await interaction.followup.send("❌ 只有抽奖创建者或管理员才能开奖！", ephemeral=True)
            return
        
        if status != 'active':
            await interaction.followup.send("❌ 该抽奖活动已结束或被取消！", ephemeral=True)
            return
        
        # 获取参与者
        cursor.execute('SELECT user_id, weight FROM participants WHERE lottery_id = ?', (抽奖id,))
        participants = cursor.fetchall()
        
        if not participants:
            embed = discord.Embed(
                title="🎲 开奖结果",
                description=f"**{title}**\n\n❌ 没有参与者，无法进行开奖！",
                color=0xff6b6b
            )
            await interaction.followup.send(embed=embed)
            return
        
        prizes = json.loads(prizes_json)
        
        # 进行抽奖
        winners = []
        available_participants = participants.copy()
        
        for prize in prizes:
            if available_participants:
                # 加权随机选择
                weights = [p[1] for p in available_participants]
                chosen_participant = random.choices(available_participants, weights=weights)[0]
                winners.append((chosen_participant[0], prize['name']))
                
                # 移除已中奖用户（避免重复中奖）
                available_participants = [p for p in available_participants if p[0] != chosen_participant[0]]
        
        # 保存中奖记录
        for user_id, prize_name in winners:
            cursor.execute('''
                INSERT INTO winners (lottery_id, user_id, prize_name)
                VALUES (?, ?, ?)
            ''', (抽奖id, user_id, prize_name))
        
        # 更新抽奖状态
        cursor.execute('UPDATE lotteries SET status = "ended" WHERE id = ?', (抽奖id,))
        bot.conn.commit()
        
        # 创建中奖结果嵌入
        embed = discord.Embed(
            title="🎉 开奖结果",
            description=f"**{title}**\n\n恭喜以下用户中奖！",
            color=0x4ecdc4
        )
        
        for user_id, prize_name in winners:
            user = interaction.guild.get_member(user_id)
            user_mention = user.mention if user else f"<@{user_id}>"
            embed.add_field(
                name=f"🏆 {prize_name}",
                value=f"恭喜 {user_mention}！",
                inline=False
            )
        
        embed.add_field(
            name="📊 抽奖统计",
            value=f"总参与人数: {len(participants)}人\n" +
                  f"中奖人数: {len(winners)}人",
            inline=False
        )
        
        embed.set_footer(text=f"开奖时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 执行者: {interaction.user.display_name}")
        
        await interaction.followup.send(embed=embed)
        
        logger.info(f"用户 {interaction.user} 对抽奖 {抽奖id} 进行了开奖")
        
    except Exception as e:
        logger.error(f"开奖时出错: {e}")
        await interaction.followup.send("❌ 开奖时出现错误，请稍后重试。", ephemeral=True)

# S1管理面板相关类
class AdminControlView(discord.ui.View):
    """管理员控制面板视图"""
    
    def __init__(self):
        super().__init__(timeout=300)  # 5分钟超时
    
    @discord.ui.select(
        placeholder="选择管理功能...",
        options=[
            discord.SelectOption(
                label="📊 服务器统计",
                description="查看所有服务器的抽奖统计",
                value="server_stats",
                emoji="📊"
            ),
            discord.SelectOption(
                label="🎲 活跃抽奖管理",
                description="管理所有服务器的活跃抽奖",
                value="active_lotteries",
                emoji="🎲"
            ),
            discord.SelectOption(
                label="📢 全局公告",
                description="向指定服务器发送公告",
                value="global_announcement",
                emoji="📢"
            ),
            discord.SelectOption(
                label="🔧 系统管理",
                description="数据库清理、重启等系统操作",
                value="system_management",
                emoji="🔧"
            ),
            discord.SelectOption(
                label="📈 详细报告",
                description="生成详细的使用报告",
                value="detailed_report",
                emoji="📈"
            ),
            discord.SelectOption(
                label="🔍 用户管理",
                description="查看和管理特定用户的活动",
                value="user_management",
                emoji="🔍"
            ),
            discord.SelectOption(
                label="🏰 服务器管理",
                description="深度管理特定服务器",
                value="guild_management",
                emoji="🏰"
            ),
            discord.SelectOption(
                label="📝 日志查看",
                description="查看机器人运行日志",
                value="log_viewer",
                emoji="📝"
            ),
            discord.SelectOption(
                label="⚙️ 高级设置",
                description="机器人的高级配置选项",
                value="advanced_settings",
                emoji="⚙️"
            ),
            discord.SelectOption(
                label="🎯 实时监控",
                description="实时监控机器人状态",
                value="realtime_monitor",
                emoji="🎯"
            ),
            discord.SelectOption(
                label="🎲 创建抽奖",
                description="在指定服务器和频道创建抽奖",
                value="create_lottery",
                emoji="🎲"
            )
        ]
    )
    async def admin_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        """管理员选择处理"""
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ 权限不足！", ephemeral=True)
            return
        
        if select.values[0] == "global_announcement":
            # 对于模态框，不需要defer
            await self.show_announcement_modal(interaction)
        else:
            # 对于其他操作，先defer
            await interaction.response.defer()
            
            if select.values[0] == "server_stats":
                await self.show_server_stats(interaction)
            elif select.values[0] == "active_lotteries":
                await self.show_active_lotteries_management(interaction)
            elif select.values[0] == "system_management":
                await self.show_system_management(interaction)
            elif select.values[0] == "detailed_report":
                await self.show_detailed_report(interaction)
            elif select.values[0] == "user_management":
                await self.show_user_management(interaction)
            elif select.values[0] == "guild_management":
                await self.show_guild_management(interaction)
            elif select.values[0] == "log_viewer":
                await self.show_log_viewer(interaction)
            elif select.values[0] == "advanced_settings":
                await self.show_advanced_settings(interaction)
            elif select.values[0] == "realtime_monitor":
                await self.show_realtime_monitor(interaction)
            elif select.values[0] == "create_lottery":
                await self.show_create_lottery(interaction)
    
    async def show_server_stats(self, interaction: discord.Interaction):
        """显示服务器统计"""
        cursor = bot.conn.cursor()
        
        # 获取所有服务器统计
        guilds_info = []
        for guild in bot.guilds:
            cursor.execute('SELECT COUNT(*) FROM lotteries WHERE guild_id = ?', (guild.id,))
            total_lotteries = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM lotteries WHERE guild_id = ? AND status = "active"', (guild.id,))
            active_lotteries = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT COUNT(*) FROM participants p
                JOIN lotteries l ON p.lottery_id = l.id
                WHERE l.guild_id = ?
            ''', (guild.id,))
            total_participants = cursor.fetchone()[0]
            
            guilds_info.append({
                'name': guild.name,
                'id': guild.id,
                'member_count': guild.member_count,
                'total_lotteries': total_lotteries,
                'active_lotteries': active_lotteries,
                'total_participants': total_participants
            })
        
        # 创建统计嵌入
        embed = discord.Embed(
            title="🌐 全局服务器统计",
            description=f"机器人当前在 {len(bot.guilds)} 个服务器中运行",
            color=0x4ecdc4
        )
        
        for guild_info in guilds_info[:10]:  # 限制显示前10个服务器
            embed.add_field(
                name=f"🏰 {guild_info['name']}",
                value=f"ID: {guild_info['id']}\n" +
                      f"成员: {guild_info['member_count']}\n" +
                      f"总抽奖: {guild_info['total_lotteries']}\n" +
                      f"活跃: {guild_info['active_lotteries']}\n" +
                      f"参与: {guild_info['total_participants']}",
                inline=True
            )
        
        if len(bot.guilds) > 10:
            embed.set_footer(text=f"显示前10个服务器，总共{len(bot.guilds)}个服务器")
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def show_user_management(self, interaction: discord.Interaction):
        """显示用户管理面板"""
        embed = discord.Embed(
            title="🔍 用户管理中心",
            description="管理和查看用户活动数据",
            color=0x4ecdc4
        )
        
        view = UserManagementView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    
    async def show_guild_management(self, interaction: discord.Interaction):
        """显示服务器管理面板"""
        embed = discord.Embed(
            title="🏰 服务器管理中心",
            description="深度管理和配置服务器设置",
            color=0x4ecdc4
        )
        
        view = GuildManagementView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    
    async def show_log_viewer(self, interaction: discord.Interaction):
        """显示日志查看器"""
        try:
            # 读取最近的日志
            with open('bot.log', 'r', encoding='utf-8') as f:
                lines = f.readlines()
                recent_logs = lines[-50:]  # 最近50行
            
            log_content = ''.join(recent_logs)
            if len(log_content) > 1900:  # Discord嵌入消息限制
                log_content = log_content[-1900:]
                log_content = "..." + log_content
            
            embed = discord.Embed(
                title="📝 机器人运行日志",
                description=f"```\n{log_content}\n```",
                color=0x4ecdc4
            )
            
            embed.set_footer(text="显示最近50行日志")
            
        except FileNotFoundError:
            embed = discord.Embed(
                title="📝 日志查看器",
                description="未找到日志文件",
                color=0xff6b6b
            )
        except Exception as e:
            embed = discord.Embed(
                title="📝 日志查看器",
                description=f"读取日志失败: {e}",
                color=0xff6b6b
            )
        
        view = LogViewerView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    
    async def show_advanced_settings(self, interaction: discord.Interaction):
        """显示高级设置面板"""
        embed = discord.Embed(
            title="⚙️ 高级设置中心",
            description="机器人的高级配置和系统设置",
            color=0xffa726
        )
        
        view = AdvancedSettingsView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    
    async def show_realtime_monitor(self, interaction: discord.Interaction):
        """显示实时监控面板"""
        import psutil
        import sys
        
        # 获取系统信息
        memory = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=1)
        
        embed = discord.Embed(
            title="🎯 实时监控面板",
            description="机器人和系统的实时状态监控",
            color=0x9c27b0
        )
        
        embed.add_field(
            name="🤖 机器人状态",
            value=f"延迟: {round(bot.latency * 1000)}ms\n" +
                  f"服务器数: {len(bot.guilds)}\n" +
                  f"用户数: {len(bot.users)}\n" +
                  f"活跃抽奖: {len(bot.active_lotteries)}",
            inline=True
        )
        
        embed.add_field(
            name="💻 系统资源",
            value=f"CPU使用率: {cpu_percent}%\n" +
                  f"内存使用: {memory.percent}%\n" +
                  f"可用内存: {memory.available // (1024**3):.1f}GB",
            inline=True
        )
        
        embed.add_field(
            name="🔧 技术信息",
            value=f"Python: {sys.version.split()[0]}\n" +
                  f"Discord.py: {discord.__version__}\n" +
                  f"运行时间: {self.get_uptime()}",
            inline=True
        )
        
        view = RealtimeMonitorView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    
    async def show_create_lottery(self, interaction: discord.Interaction):
        """显示创建抽奖面板"""
        embed = discord.Embed(
            title="🎲 创建抽奖中心",
            description="选择服务器和频道来创建抽奖活动",
            color=0xe74c3c
        )
        
        view = CreateLotteryView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    
    def get_uptime(self):
        """获取机器人运行时间"""
        import time
        uptime_seconds = time.time() - bot.start_time
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{int(hours)}小时{int(minutes)}分钟"
    
    async def show_active_lotteries_management(self, interaction: discord.Interaction):
        """显示所有活跃抽奖"""
        cursor = bot.conn.cursor()
        
        cursor.execute('''
            SELECT l.id, l.title, l.guild_id, l.creator_id, l.created_at, l.end_time,
                   COUNT(p.id) as participant_count
            FROM lotteries l
            LEFT JOIN participants p ON l.id = p.lottery_id
            WHERE l.status = 'active'
            GROUP BY l.id
            ORDER BY l.created_at DESC
            LIMIT 20
        ''')
        
        active_lotteries = cursor.fetchall()
        
        if not active_lotteries:
            embed = discord.Embed(
                title="🎲 全局活跃抽奖",
                description="当前没有活跃的抽奖活动",
                color=0x95a5a6
            )
        else:
            embed = discord.Embed(
                title="🎲 全局活跃抽奖管理",
                description=f"当前有 {len(active_lotteries)} 个活跃抽奖",
                color=0x4ecdc4
            )
            
            for lottery in active_lotteries[:10]:
                guild = bot.get_guild(lottery[2])
                guild_name = guild.name if guild else "未知服务器"
                
                creator = bot.get_user(lottery[3])
                creator_name = creator.display_name if creator else "未知用户"
                
                countdown = "手动开奖"
                if lottery[5]:  # end_time
                    end_time = datetime.datetime.fromisoformat(lottery[5])
                    countdown = bot.format_countdown(end_time)
                
                embed.add_field(
                    name=f"🎯 {lottery[1]} (ID: {lottery[0]})",
                    value=f"🏰 服务器: {guild_name}\n" +
                          f"👤 创建者: {creator_name}\n" +
                          f"👥 参与: {lottery[6]}人\n" +
                          f"⏰ {countdown}",
                    inline=True
                )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def show_announcement_modal(self, interaction: discord.Interaction):
        """显示公告发送模态框"""
        modal = AnnouncementModal()
        await interaction.response.send_modal(modal)
    
    async def show_system_management(self, interaction: discord.Interaction):
        """显示系统管理选项"""
        embed = discord.Embed(
            title="🔧 系统管理",
            description="选择要执行的系统管理操作",
            color=0xffa726
        )
        
        view = SystemManagementView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    
    async def show_detailed_report(self, interaction: discord.Interaction):
        """显示详细报告"""
        cursor = bot.conn.cursor()
        
        # 收集详细统计数据
        cursor.execute('SELECT COUNT(*) FROM lotteries')
        total_lotteries = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM participants')
        total_participants = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM winners')
        total_winners = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM lotteries WHERE status = "active"')
        active_lotteries = cursor.fetchone()[0]
        
        # 最活跃的服务器
        cursor.execute('''
            SELECT l.guild_id, COUNT(*) as lottery_count
            FROM lotteries l
            GROUP BY l.guild_id
            ORDER BY lottery_count DESC
            LIMIT 5
        ''')
        top_guilds = cursor.fetchall()
        
        embed = discord.Embed(
            title="📈 机器人详细使用报告",
            description="全面的机器人使用统计数据",
            color=0x4ecdc4
        )
        
        embed.add_field(
            name="📊 总体统计",
            value=f"总服务器数: {len(bot.guilds)}\n" +
                  f"总抽奖数: {total_lotteries}\n" +
                  f"活跃抽奖: {active_lotteries}\n" +
                  f"总参与次数: {total_participants}\n" +
                  f"总中奖次数: {total_winners}\n" +
                  f"平均中奖率: {(total_winners/total_participants*100) if total_participants > 0 else 0:.1f}%",
            inline=False
        )
        
        if top_guilds:
            guild_text = "\n".join([
                f"{i+1}. {bot.get_guild(guild_id).name if bot.get_guild(guild_id) else 'Unknown'}: {count}个抽奖"
                for i, (guild_id, count) in enumerate(top_guilds)
            ])
            embed.add_field(
                name="🏆 最活跃服务器",
                value=guild_text,
                inline=False
            )
        
        embed.set_footer(text=f"报告生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        await interaction.followup.send(embed=embed, ephemeral=True)

class AnnouncementModal(discord.ui.Modal):
    """公告发送模态框"""
    
    def __init__(self):
        super().__init__(title="📢 发送全局公告")
        
        self.server_id = discord.ui.TextInput(
            label="服务器ID (留空发送到所有服务器)",
            placeholder="输入服务器ID，留空则发送到所有服务器",
            required=False,
            max_length=20
        )
        
        self.channel_name = discord.ui.TextInput(
            label="频道名称",
            placeholder="输入要发送的频道名称 (如: general, 抽奖频道)",
            required=True,
            max_length=100
        )
        
        self.announcement = discord.ui.TextInput(
            label="公告内容",
            placeholder="输入要发送的公告内容...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000
        )
        
        self.add_item(self.server_id)
        self.add_item(self.channel_name)
        self.add_item(self.announcement)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        target_guilds = []
        if self.server_id.value.strip():
            # 发送到特定服务器
            try:
                guild_id = int(self.server_id.value.strip())
                guild = bot.get_guild(guild_id)
                if guild:
                    target_guilds = [guild]
                else:
                    await interaction.followup.send("❌ 找不到指定的服务器！", ephemeral=True)
                    return
            except ValueError:
                await interaction.followup.send("❌ 服务器ID格式错误！", ephemeral=True)
                return
        else:
            # 发送到所有服务器
            target_guilds = bot.guilds
        
        sent_count = 0
        failed_count = 0
        
        for guild in target_guilds:
            try:
                # 查找指定名称的频道
                channel = discord.utils.get(guild.text_channels, name=self.channel_name.value.strip())
                if not channel:
                    # 如果找不到，尝试查找包含该名称的频道
                    for ch in guild.text_channels:
                        if self.channel_name.value.strip().lower() in ch.name.lower():
                            channel = ch
                            break
                
                if channel:
                    embed = discord.Embed(
                        title="📢 机器人公告",
                        description=self.announcement.value,
                        color=0x4ecdc4
                    )
                    embed.set_footer(text=f"来自机器人管理员 | {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
                    
                    await channel.send(embed=embed)
                    sent_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                failed_count += 1
                logger.error(f"发送公告到 {guild.name} 失败: {e}")
        
        result_embed = discord.Embed(
            title="📢 公告发送结果",
            description=f"✅ 成功发送: {sent_count} 个服务器\n❌ 发送失败: {failed_count} 个服务器",
            color=0x4ecdc4 if failed_count == 0 else 0xffa726
        )
        
        await interaction.followup.send(embed=result_embed, ephemeral=True)

class SystemManagementView(discord.ui.View):
    """系统管理视图"""
    
    def __init__(self):
        super().__init__(timeout=300)
    
    @discord.ui.button(label="🗑️ 清理旧数据", style=discord.ButtonStyle.secondary)
    async def cleanup_data(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ 权限不足！", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        # 清理90天前的数据
        cursor = bot.conn.cursor()
        cutoff_date = datetime.datetime.now() - datetime.timedelta(days=90)
        
        # 删除旧的已结束抽奖
        cursor.execute('''
            DELETE FROM winners WHERE lottery_id IN (
                SELECT id FROM lotteries 
                WHERE status IN ('ended', 'cancelled') AND created_at < ?
            )
        ''', (cutoff_date,))
        
        cursor.execute('''
            DELETE FROM participants WHERE lottery_id IN (
                SELECT id FROM lotteries 
                WHERE status IN ('ended', 'cancelled') AND created_at < ?
            )
        ''', (cutoff_date,))
        
        cursor.execute('''
            DELETE FROM lotteries 
            WHERE status IN ('ended', 'cancelled') AND created_at < ?
        ''', (cutoff_date,))
        
        deleted_count = cursor.rowcount
        bot.conn.commit()
        
        embed = discord.Embed(
            title="🗑️ 数据清理完成",
            description=f"已清理 {deleted_count} 条90天前的旧数据记录",
            color=0x4ecdc4
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="📊 数据库状态", style=discord.ButtonStyle.primary)
    async def database_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ 权限不足！", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        cursor = bot.conn.cursor()
        
        # 获取各表的记录数
        cursor.execute('SELECT COUNT(*) FROM lotteries')
        lotteries_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM participants')
        participants_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM winners')
        winners_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM statistics')
        stats_count = cursor.fetchone()[0]
        
        embed = discord.Embed(
            title="📊 数据库状态",
            description="当前数据库表记录统计",
            color=0x4ecdc4
        )
        
        embed.add_field(
            name="📋 数据表统计",
            value=f"抽奖记录: {lotteries_count}\n" +
                  f"参与记录: {participants_count}\n" +
                  f"中奖记录: {winners_count}\n" +
                  f"统计记录: {stats_count}",
            inline=False
        )
        
        # 数据库文件大小
        try:
            db_size = os.path.getsize('lottery_bot.db')
            size_mb = db_size / (1024 * 1024)
            embed.add_field(
                name="💾 数据库文件",
                value=f"文件大小: {size_mb:.2f} MB",
                inline=False
            )
        except:
            pass
        
        await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="抽奖统计", description="📈 查看抽奖统计信息")
@app_commands.describe(用户="查看特定用户的统计 (留空查看服务器统计)")
async def lottery_stats(interaction: discord.Interaction, 用户: Optional[discord.Member] = None):
    """查看抽奖统计"""
    await interaction.response.defer()
    
    try:
        cursor = bot.conn.cursor()
        
        if 用户:
            # 查看特定用户统计
            user_id = 用户.id
            
            # 参与的抽奖数量
            cursor.execute('''
                SELECT COUNT(DISTINCT lottery_id) FROM participants 
                WHERE user_id = ? AND lottery_id IN (
                    SELECT id FROM lotteries WHERE guild_id = ?
                )
            ''', (user_id, interaction.guild.id))
            participated_count = cursor.fetchone()[0]
            
            # 中奖次数
            cursor.execute('''
                SELECT COUNT(*) FROM winners 
                WHERE user_id = ? AND lottery_id IN (
                    SELECT id FROM lotteries WHERE guild_id = ?
                )
            ''', (user_id, interaction.guild.id))
            won_count = cursor.fetchone()[0]
            
            # 最近中奖记录
            cursor.execute('''
                SELECT l.title, w.prize_name, w.won_at 
                FROM winners w
                JOIN lotteries l ON w.lottery_id = l.id
                WHERE w.user_id = ? AND l.guild_id = ?
                ORDER BY w.won_at DESC
                LIMIT 5
            ''', (user_id, interaction.guild.id))
            recent_wins = cursor.fetchall()
            
            embed = discord.Embed(
                title=f"📊 {用户.display_name} 的抽奖统计",
                color=0x4ecdc4
            )
            
            embed.set_thumbnail(url=用户.display_avatar.url)
            
            # 基本统计
            win_rate = (won_count / participated_count * 100) if participated_count > 0 else 0
            embed.add_field(
                name="🎯 基本统计",
                value=f"参与抽奖: {participated_count} 次\n" +
                      f"中奖次数: {won_count} 次\n" +
                      f"中奖率: {win_rate:.1f}%",
                inline=True
            )
            
            # 最近中奖记录
            if recent_wins:
                recent_text = "\n".join([
                    f"• **{title}** - {prize_name}\n  {won_at}"
                    for title, prize_name, won_at in recent_wins[:3]
                ])
                embed.add_field(
                    name="🏆 最近中奖记录",
                    value=recent_text,
                    inline=False
                )
            else:
                embed.add_field(
                    name="🏆 最近中奖记录",
                    value="暂无中奖记录",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        else:
            # 查看服务器统计
            # 总抽奖数
            cursor.execute('SELECT COUNT(*) FROM lotteries WHERE guild_id = ?', (interaction.guild.id,))
            total_lotteries = cursor.fetchone()[0]
            
            # 活跃抽奖数
            cursor.execute('SELECT COUNT(*) FROM lotteries WHERE guild_id = ? AND status = "active"', (interaction.guild.id,))
            active_lotteries = cursor.fetchone()[0]
            
            # 总参与次数
            cursor.execute('''
                SELECT COUNT(*) FROM participants p
                JOIN lotteries l ON p.lottery_id = l.id
                WHERE l.guild_id = ?
            ''', (interaction.guild.id,))
            total_participations = cursor.fetchone()[0]
            
            # 总中奖次数
            cursor.execute('''
                SELECT COUNT(*) FROM winners w
                JOIN lotteries l ON w.lottery_id = l.id
                WHERE l.guild_id = ?
            ''', (interaction.guild.id,))
            total_wins = cursor.fetchone()[0]
            
            # 最活跃的用户
            cursor.execute('''
                SELECT p.user_id, COUNT(*) as participation_count
                FROM participants p
                JOIN lotteries l ON p.lottery_id = l.id
                WHERE l.guild_id = ?
                GROUP BY p.user_id
                ORDER BY participation_count DESC
                LIMIT 5
            ''', (interaction.guild.id,))
            top_participants = cursor.fetchall()
            
            # 最幸运的用户
            cursor.execute('''
                SELECT w.user_id, COUNT(*) as win_count
                FROM winners w
                JOIN lotteries l ON w.lottery_id = l.id
                WHERE l.guild_id = ?
                GROUP BY w.user_id
                ORDER BY win_count DESC
                LIMIT 5
            ''', (interaction.guild.id,))
            top_winners = cursor.fetchall()
            
            embed = discord.Embed(
                title=f"📊 {interaction.guild.name} 抽奖统计",
                description="服务器抽奖活动总览",
                color=0x4ecdc4
            )
            
            embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
            
            # 基本统计
            embed.add_field(
                name="🎲 抽奖统计",
                value=f"总抽奖数: {total_lotteries}\n" +
                      f"进行中: {active_lotteries}\n" +
                      f"已完成: {total_lotteries - active_lotteries}",
                inline=True
            )
            
            embed.add_field(
                name="👥 参与统计",
                value=f"总参与次数: {total_participations}\n" +
                      f"总中奖次数: {total_wins}\n" +
                      f"平均中奖率: {(total_wins/total_participations*100) if total_participations > 0 else 0:.1f}%",
                inline=True
            )
            
            # 最活跃用户
            if top_participants:
                participant_text = "\n".join([
                    f"{i+1}. <@{user_id}> - {count}次"
                    for i, (user_id, count) in enumerate(top_participants[:3])
                ])
                embed.add_field(
                    name="🔥 最活跃用户",
                    value=participant_text,
                    inline=True
                )
            
            # 最幸运用户
            if top_winners:
                winner_text = "\n".join([
                    f"{i+1}. <@{user_id}> - {count}次中奖"
                    for i, (user_id, count) in enumerate(top_winners[:3])
                ])
                embed.add_field(
                    name="🍀 最幸运用户",
                    value=winner_text,
                    inline=True
                )
            
            embed.set_footer(text=f"统计时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            await interaction.followup.send(embed=embed)
            
    except Exception as e:
        logger.error(f"查看统计时出错: {e}")
        await interaction.followup.send("❌ 查看统计时出现错误，请稍后重试。", ephemeral=True)

@bot.tree.command(name="随机选择", description="🎲 从提供的选项中随机选择一个")
@app_commands.describe(选项="用逗号分隔的选项 (例如: 苹果,香蕉,橙子)")
async def random_choice(interaction: discord.Interaction, 选项: str):
    """随机选择工具"""
    await interaction.response.defer()
    
    try:
        choices = [choice.strip() for choice in 选项.split(',') if choice.strip()]
        
        if len(choices) < 2:
            await interaction.followup.send("❌ 请提供至少两个选项！", ephemeral=True)
            return
        
        if len(choices) > 20:
            await interaction.followup.send("❌ 选项数量不能超过20个！", ephemeral=True)
            return
        
        selected = random.choice(choices)
        
        embed = discord.Embed(
            title="🎲 随机选择结果",
            color=0x4ecdc4
        )
        
        embed.add_field(
            name="🎯 选中的选项",
            value=f"**{selected}**",
            inline=False
        )
        
        embed.add_field(
            name="📝 所有选项",
            value="\n".join([f"{'✅' if choice == selected else '❌'} {choice}" for choice in choices]),
            inline=False
        )
        
        embed.set_footer(text=f"请求者: {interaction.user.display_name}")
        
        await interaction.followup.send(embed=embed)
        
        logger.info(f"用户 {interaction.user} 使用随机选择: {选项} -> {selected}")
        
    except Exception as e:
        logger.error(f"随机选择时出错: {e}")
        await interaction.followup.send("❌ 随机选择时出现错误，请稍后重试。", ephemeral=True)

@bot.tree.command(name="随机数字", description="🔢 生成指定范围内的随机数字")
@app_commands.describe(
    最小值="最小值 (默认: 1)",
    最大值="最大值 (默认: 100)",
    数量="生成数量 (默认: 1, 最多: 10)"
)
async def random_number(interaction: discord.Interaction, 最小值: int = 1, 最大值: int = 100, 数量: int = 1):
    """随机数字生成工具"""
    await interaction.response.defer()
    
    try:
        if 最小值 >= 最大值:
            await interaction.followup.send("❌ 最小值必须小于最大值！", ephemeral=True)
            return
        
        if 数量 < 1 or 数量 > 10:
            await interaction.followup.send("❌ 数量必须在1-10之间！", ephemeral=True)
            return
        
        if 最大值 - 最小值 > 1000000:
            await interaction.followup.send("❌ 数字范围不能超过1,000,000！", ephemeral=True)
            return
        
        numbers = [random.randint(最小值, 最大值) for _ in range(数量)]
        
        embed = discord.Embed(
            title="🔢 随机数字生成结果",
            color=0x4ecdc4
        )
        
        if 数量 == 1:
            embed.add_field(
                name="🎯 生成的数字",
                value=f"**{numbers[0]}**",
                inline=False
            )
        else:
            embed.add_field(
                name=f"🎯 生成的 {数量} 个数字",
                value="\n".join([f"**{i+1}.** {num}" for i, num in enumerate(numbers)]),
                inline=False
            )
        
        embed.add_field(
            name="📊 参数信息",
            value=f"范围: {最小值} ~ {最大值}\n数量: {数量}",
            inline=False
        )
        
        embed.set_footer(text=f"请求者: {interaction.user.display_name}")
        
        await interaction.followup.send(embed=embed)
        
        logger.info(f"用户 {interaction.user} 生成随机数字: {最小值}-{最大值}, 数量: {数量}")
        
    except Exception as e:
        logger.error(f"生成随机数字时出错: {e}")
        await interaction.followup.send("❌ 生成随机数字时出现错误，请稍后重试。", ephemeral=True)

@bot.tree.command(name="取消抽奖", description="❌ 取消抽奖活动 (仅创建者和管理员可用)")
@app_commands.describe(抽奖id="要取消的抽奖活动ID")
async def cancel_lottery(interaction: discord.Interaction, 抽奖id: int):
    """取消抽奖"""
    await interaction.response.defer()
    
    try:
        cursor = bot.conn.cursor()
        
        # 检查抽奖是否存在
        cursor.execute('''
            SELECT title, creator_id, status
            FROM lotteries 
            WHERE id = ? AND guild_id = ?
        ''', (抽奖id, interaction.guild.id))
        
        lottery = cursor.fetchone()
        if not lottery:
            await interaction.followup.send("❌ 找不到指定的抽奖活动！", ephemeral=True)
            return
        
        title, creator_id, status = lottery
        
        # 检查权限
        if (interaction.user.id != creator_id and 
            not interaction.user.guild_permissions.manage_messages):
            await interaction.followup.send("❌ 只有抽奖创建者或管理员才能取消抽奖！", ephemeral=True)
            return
        
        if status != 'active':
            await interaction.followup.send("❌ 该抽奖活动已结束或已被取消！", ephemeral=True)
            return
        
        # 更新抽奖状态
        cursor.execute('UPDATE lotteries SET status = "cancelled" WHERE id = ?', (抽奖id,))
        bot.conn.commit()
        
        embed = discord.Embed(
            title="❌ 抽奖已取消",
            description=f"抽奖活动 **{title}** 已被取消。",
            color=0xff6b6b
        )
        
        embed.add_field(
            name="📊 取消信息",
            value=f"抽奖ID: {抽奖id}\n执行者: {interaction.user.display_name}",
            inline=False
        )
        
        embed.set_footer(text=f"取消时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        await interaction.followup.send(embed=embed)
        
        logger.info(f"用户 {interaction.user} 取消了抽奖 {抽奖id}")
        
    except Exception as e:
        logger.error(f"取消抽奖时出错: {e}")
        await interaction.followup.send("❌ 取消抽奖时出现错误，请稍后重试。", ephemeral=True)

@bot.tree.command(name="我的抽奖", description="👤 查看您参与和创建的抽奖")
async def my_lotteries(interaction: discord.Interaction):
    """查看用户的抽奖"""
    await interaction.response.defer(ephemeral=True)
    
    try:
        cursor = bot.conn.cursor()
        user_id = interaction.user.id
        
        # 我创建的抽奖
        cursor.execute('''
            SELECT id, title, status, created_at
            FROM lotteries 
            WHERE creator_id = ? AND guild_id = ?
            ORDER BY created_at DESC
            LIMIT 5
        ''', (user_id, interaction.guild.id))
        created_lotteries = cursor.fetchall()
        
        # 我参与的抽奖
        cursor.execute('''
            SELECT l.id, l.title, l.status, p.joined_at
            FROM participants p
            JOIN lotteries l ON p.lottery_id = l.id
            WHERE p.user_id = ? AND l.guild_id = ?
            ORDER BY p.joined_at DESC
            LIMIT 5
        ''', (user_id, interaction.guild.id))
        participated_lotteries = cursor.fetchall()
        
        # 我的中奖记录
        cursor.execute('''
            SELECT l.title, w.prize_name, w.won_at
            FROM winners w
            JOIN lotteries l ON w.lottery_id = l.id
            WHERE w.user_id = ? AND l.guild_id = ?
            ORDER BY w.won_at DESC
            LIMIT 5
        ''', (user_id, interaction.guild.id))
        my_wins = cursor.fetchall()
        
        embed = discord.Embed(
            title=f"👤 {interaction.user.display_name} 的抽奖记录",
            color=0x4ecdc4
        )
        
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        
        # 我创建的抽奖
        if created_lotteries:
            created_text = "\n".join([
                f"• **{title}** ({status}) - ID: {lid}"
                for lid, title, status, created_at in created_lotteries
            ])
            embed.add_field(
                name="📝 我创建的抽奖",
                value=created_text,
                inline=False
            )
        
        # 我参与的抽奖
        if participated_lotteries:
            participated_text = "\n".join([
                f"• **{title}** ({status}) - ID: {lid}"
                for lid, title, status, joined_at in participated_lotteries
            ])
            embed.add_field(
                name="🎯 我参与的抽奖",
                value=participated_text,
                inline=False
            )
        
        # 我的中奖记录
        if my_wins:
            wins_text = "\n".join([
                f"🏆 **{title}** - {prize_name}\n  {won_at}"
                for title, prize_name, won_at in my_wins[:3]
            ])
            embed.add_field(
                name="🎉 我的中奖记录",
                value=wins_text,
                inline=False
            )
        
        if not created_lotteries and not participated_lotteries and not my_wins:
            embed.description = "您还没有创建或参与任何抽奖活动。\n\n使用 `/创建抽奖` 来创建您的第一个抽奖！"
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
    except Exception as e:
        logger.error(f"查看个人抽奖时出错: {e}")
        await interaction.followup.send("❌ 查看个人抽奖时出现错误，请稍后重试。", ephemeral=True)

# 抽奖参与按钮视图
class LotteryParticipateView(discord.ui.View):
    """抽奖参与按钮视图"""
    
    def __init__(self, lottery_id: int):
        super().__init__(timeout=None)  # 持久化视图
        self.lottery_id = lottery_id
    
    @discord.ui.button(label="🎲 参加抽奖", style=discord.ButtonStyle.primary, emoji="🎲")
    async def participate_lottery(self, interaction: discord.Interaction, button: discord.ui.Button):
        """参加抽奖按钮"""
        # 使用 defer 确保有足够时间处理
        await interaction.response.defer(ephemeral=True)

        try:
            # 获取数据库连接
            cursor = bot.conn.cursor()

            # 检查抽奖是否存在和有效
            cursor.execute("""
                SELECT title, end_time, max_participants, allow_multiple_entries, required_roles, 
                       creator_id, guild_id, channel_id, status
                FROM lotteries WHERE id = ?
            """, (self.lottery_id,))
            
            lottery = cursor.fetchone()
            if not lottery:
                await interaction.followup.send("❌ 抽奖不存在！", ephemeral=True)
                return
            
            # 正确的列索引
            l_title, l_end_time, l_max_participants, l_allow_multiple, l_required_roles_json, _, _, _, l_status = lottery

            if l_status != 'active':
                await interaction.followup.send("❌ 抽奖已结束或被取消！", ephemeral=True)
                return
            
            # 检查是否已过期
            if l_end_time:
                end_time = datetime.datetime.fromisoformat(l_end_time)
                if datetime.datetime.now() > end_time:
                    await interaction.followup.send("❌ 抽奖已过期！", ephemeral=True)
                    return
            
            # 检查角色要求
            if l_required_roles_json and interaction.guild:
                required_roles_ids = json.loads(l_required_roles_json)
                user_role_ids = {role.id for role in interaction.user.roles}
                if not any(role_id in user_role_ids for role_id in required_roles_ids):
                    role_mentions = [f"<@&{role_id}>" for role_id in required_roles_ids]
                    await interaction.followup.send(f"❌ 您需要拥有以下角色之一才能参与: {', '.join(role_mentions)}", ephemeral=True)
                    return
            
            # 检查是否已参与
            cursor.execute("SELECT COUNT(*) FROM participants WHERE lottery_id = ? AND user_id = ?", 
                          (self.lottery_id, interaction.user.id))
            participation_count = cursor.fetchone()[0]
            
            if participation_count > 0 and not l_allow_multiple:
                await interaction.followup.send("❌ 您已经参与过此抽奖了！", ephemeral=True)
                return
            
            # 检查人数限制
            if l_max_participants > 0:
                cursor.execute("SELECT COUNT(*) FROM participants WHERE lottery_id = ?", 
                              (self.lottery_id,))
                current_participants = cursor.fetchone()[0]
                if current_participants >= l_max_participants:
                    await interaction.followup.send("❌ 抽奖人数已满！", ephemeral=True)
                    return
            
            # 添加参与记录
            cursor.execute("""
                INSERT INTO participants (lottery_id, user_id, discord_id)
                VALUES (?, ?, ?)
            """, (self.lottery_id, interaction.user.id, str(interaction.user.id)))
            
            bot.conn.commit()
            
            # 更新参与统计
            cursor.execute("SELECT COUNT(*) FROM participants WHERE lottery_id = ?", (self.lottery_id,))
            total_participants = cursor.fetchone()[0]
            
            await interaction.followup.send(
                f"✅ 成功参与抽奖 **{l_title}**！\n"
                f"🎯 当前参与人数: {total_participants}" + 
                (f"/{l_max_participants}" if l_max_participants > 0 else ""),
                ephemeral=True
            )
            
            logger.info(f"用户 {interaction.user} 通过按钮参与了抽奖 {self.lottery_id}")
            
        except sqlite3.IntegrityError:
             # 处理用户已经参与但 allow_multiple 为 False 的情况
            await interaction.followup.send("❌ 您已经参与过此抽奖了！", ephemeral=True)
        except Exception as e:
            logger.error(f"按钮参与抽奖时出错: {e}")
            await interaction.followup.send("❌ 参与抽奖时出现错误，请稍后重试。", ephemeral=True)

# 创建抽奖视图
class CreateLotteryView(discord.ui.View):
    """创建抽奖视图"""
    
    def __init__(self):
        super().__init__(timeout=300)
        self.selected_guild = None
        self.selected_channel = None
        
        # 预填充服务器选项
        guild_options = []
        guilds = bot.guilds[:25]  # Discord限制最多25个选项
        for guild in guilds:
            guild_options.append(discord.SelectOption(
                label=guild.name[:100],  # 限制长度
                description=f"ID: {guild.id} | 成员: {guild.member_count}",
                value=str(guild.id)
            ))
        
        # 创建服务器选择器
        guild_select = discord.ui.Select(
            placeholder="选择服务器...",
            min_values=1,
            max_values=1,
            options=guild_options,
            row=0
        )
        guild_select.callback = self.select_guild
        self.add_item(guild_select)
        
        # 创建频道选择器（初始为禁用状态）
        channel_select = discord.ui.Select(
            placeholder="先选择服务器...",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label="请先选择服务器", value="none")],
            disabled=True,
            row=1
        )
        channel_select.callback = self.select_channel
        self.add_item(channel_select)
        
        # 创建抽奖按钮
        create_button = discord.ui.Button(
            label="🎲 开始创建抽奖",
            style=discord.ButtonStyle.success,
            disabled=True,
            row=2
        )
        create_button.callback = self.create_lottery_button
        self.add_item(create_button)
    
    async def select_guild(self, interaction: discord.Interaction):
        """服务器选择器回调"""
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ 权限不足！", ephemeral=True)
            return
        
        self.selected_guild = int(interaction.data['values'][0])
        guild = bot.get_guild(self.selected_guild)
        
        # 更新频道选择器
        channel_select = self.children[1]  # 第二个组件是频道选择器
        channel_select.options.clear()
        channel_select.placeholder = "选择频道..."
        channel_select.disabled = False
        
        # 添加文字频道选项
        text_channels = [ch for ch in guild.text_channels if ch.permissions_for(guild.me).send_messages][:25]
        for channel in text_channels:
            channel_select.add_option(
                label=f"#{channel.name}"[:100],
                description=f"ID: {channel.id}",
                value=str(channel.id)
            )
        
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🎲 创建抽奖中心",
                description=f"已选择服务器: **{guild.name}**\n现在请选择频道...",
                color=0xe74c3c
            ),
            view=self
        )
    
    async def select_channel(self, interaction: discord.Interaction):
        """频道选择器回调"""
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ 权限不足！", ephemeral=True)
            return
        
        if not self.selected_guild:
            await interaction.response.send_message("❌ 请先选择服务器！", ephemeral=True)
            return
        
        self.selected_channel = int(interaction.data['values'][0])
        guild = bot.get_guild(self.selected_guild)
        channel = guild.get_channel(self.selected_channel)
        
        # 启用创建按钮
        create_button = self.children[2]  # 第三个组件是创建按钮
        create_button.disabled = False
        
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🎲 创建抽奖中心",
                description=f"已选择服务器: **{guild.name}**\n已选择频道: **#{channel.name}**\n\n点击下方按钮开始创建抽奖！",
                color=0x2ecc71
            ),
            view=self
        )
    
    async def create_lottery_button(self, interaction: discord.Interaction):
        """创建抽奖按钮回调"""
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ 权限不足！", ephemeral=True)
            return
        
        if not self.selected_guild or not self.selected_channel:
            await interaction.response.send_message("❌ 请先选择服务器和频道！", ephemeral=True)
            return
        
        # 显示抽奖创建模态框
        modal = CreateLotteryModal(self.selected_guild, self.selected_channel)
        await interaction.response.send_modal(modal)

# 创建抽奖模态框
class CreateLotteryModal(discord.ui.Modal):
    """创建抽奖模态框"""
    
    def __init__(self, guild_id: int, channel_id: int):
        super().__init__(title="🎲 创建新抽奖")
        self.guild_id = guild_id
        self.channel_id = channel_id
    
    title_input = discord.ui.TextInput(
        label="抽奖标题",
        placeholder="输入抽奖活动的标题...",
        max_length=100,
        required=True
    )
    
    description_input = discord.ui.TextInput(
        label="抽奖描述",
        placeholder="输入抽奖活动的详细描述...",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False
    )
    
    winners_input = discord.ui.TextInput(
        label="中奖人数",
        placeholder="输入中奖人数 (默认: 1)",
        max_length=3,
        required=False
    )
    
    duration_input = discord.ui.TextInput(
        label="持续时间 (分钟)",
        placeholder="输入抽奖持续时间，留空为手动开奖",
        max_length=10,
        required=False
    )
    
    max_participants_input = discord.ui.TextInput(
        label="最大参与人数",
        placeholder="输入最大参与人数，留空为无限制",
        max_length=10,
        required=False
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        """提交创建抽奖"""
        try:
            # 解析输入
            title = self.title_input.value
            description = self.description_input.value or "无描述"
            winners = int(self.winners_input.value) if self.winners_input.value else 1
            max_participants = int(self.max_participants_input.value) if self.max_participants_input.value else None
            
            # 计算结束时间
            end_time = None
            if self.duration_input.value:
                try:
                    duration_minutes = int(self.duration_input.value)
                    end_time = datetime.datetime.now() + datetime.timedelta(minutes=duration_minutes)
                except ValueError:
                    await interaction.response.send_message("❌ 持续时间格式错误！", ephemeral=True)
                    return
            
            # 获取数据库连接
            cursor = bot.conn.cursor()
            
            # 创建抽奖记录
            cursor.execute("""
                INSERT INTO lotteries (guild_id, channel_id, creator_id, title, description, 
                                     prizes, max_participants, end_time, status, 
                                     allow_multiple_entries)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', 1)
            """, (
                self.guild_id, self.channel_id, interaction.user.id, title, description,
                f'["{winners}个奖品"]',  # JSON格式的奖品列表
                max_participants if max_participants else -1,
                end_time.isoformat() if end_time else None
            ))
            
            lottery_id = cursor.lastrowid
            bot.conn.commit()
            
            # 获取目标频道并发送抽奖消息
            guild = bot.get_guild(self.guild_id)
            channel = guild.get_channel(self.channel_id)
            
            if channel:
                # 创建抽奖嵌入消息
                embed = discord.Embed(
                    title=f"🎲 {title}",
                    description=description,
                    color=0x3498db
                )
                
                embed.add_field(name="🏆 中奖人数", value=str(winners), inline=True)
                embed.add_field(name="👥 参与人数", value="0" + (f"/{max_participants}" if max_participants else ""), inline=True)
                
                if end_time:
                    countdown = bot.format_countdown(end_time)
                    embed.add_field(name="⏰ 剩余时间", value=countdown, inline=True)
                else:
                    embed.add_field(name="⏰ 开奖方式", value="手动开奖", inline=True)
                
                embed.add_field(name="🎯 抽奖ID", value=str(lottery_id), inline=True)
                embed.add_field(name="👤 创建者", value=str(interaction.user), inline=True)
                embed.add_field(name="📅 创建时间", value=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), inline=True)
                
                embed.set_footer(text="点击下方按钮参与抽奖！")
                
                # 添加参与按钮
                view = LotteryParticipateView(lottery_id)
                
                await channel.send(embed=embed, view=view)
                
                await interaction.response.send_message(
                    f"✅ 抽奖创建成功！\n"
                    f"🎲 **{title}**\n"
                    f"🏰 服务器: {guild.name}\n"
                    f"📢 频道: #{channel.name}\n"
                    f"🎯 抽奖ID: {lottery_id}",
                    ephemeral=True
                )
                
                logger.info(f"创建者 {interaction.user} 通过S1面板在 {guild.name}#{channel.name} 创建了抽奖: {title}")
            
            else:
                await interaction.response.send_message("❌ 无法访问目标频道！", ephemeral=True)
                
        except Exception as e:
            logger.error(f"S1面板创建抽奖时出错: {e}")
            await interaction.response.send_message("❌ 创建抽奖时出现错误，请稍后重试。", ephemeral=True)

# 新增的管理面板视图类
class UserManagementView(discord.ui.View):
    """用户管理视图"""
    
    def __init__(self):
        super().__init__(timeout=300)
    
    @discord.ui.button(label="🔍 查找用户", style=discord.ButtonStyle.primary)
    async def search_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ 权限不足！", ephemeral=True)
            return
        
        modal = UserSearchModal()
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="🏆 最活跃用户", style=discord.ButtonStyle.secondary)
    async def top_users(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ 权限不足！", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        cursor = bot.conn.cursor()
        
        # 最活跃用户
        cursor.execute('''
            SELECT p.user_id, COUNT(*) as participation_count
            FROM participants p
            GROUP BY p.user_id
            ORDER BY participation_count DESC
            LIMIT 10
        ''')
        top_participants = cursor.fetchall()
        
        # 最幸运用户
        cursor.execute('''
            SELECT w.user_id, COUNT(*) as win_count
            FROM winners w
            GROUP BY w.user_id
            ORDER BY win_count DESC
            LIMIT 10
        ''')
        top_winners = cursor.fetchall()
        
        embed = discord.Embed(
            title="🏆 全球最活跃用户排行榜",
            color=0x4ecdc4
        )
        
        if top_participants:
            participant_text = "\n".join([
                f"{i+1}. <@{user_id}> - {count}次参与"
                for i, (user_id, count) in enumerate(top_participants[:5])
            ])
            embed.add_field(
                name="🔥 最活跃参与者",
                value=participant_text,
                inline=True
            )
        
        if top_winners:
            winner_text = "\n".join([
                f"{i+1}. <@{user_id}> - {count}次中奖"
                for i, (user_id, count) in enumerate(top_winners[:5])
            ])
            embed.add_field(
                name="🍀 最幸运用户",
                value=winner_text,
                inline=True
            )
        
        await interaction.followup.send(embed=embed, ephemeral=True)

class GuildManagementView(discord.ui.View):
    """服务器管理视图"""
    
    def __init__(self):
        super().__init__(timeout=300)
    
    @discord.ui.button(label="📊 服务器详情", style=discord.ButtonStyle.primary)
    async def guild_details(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ 权限不足！", ephemeral=True)
            return
        
        modal = GuildSearchModal()
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="📝 服务器列表", style=discord.ButtonStyle.success)
    async def guild_list(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ 权限不足！", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        guilds_info = []
        for guild in bot.guilds:
            cursor = bot.conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM lotteries WHERE guild_id = ?', (guild.id,))
            lottery_count = cursor.fetchone()[0]
            
            guilds_info.append({
                'name': guild.name,
                'id': guild.id,
                'member_count': guild.member_count,
                'lottery_count': lottery_count,
                'owner': guild.owner.display_name if guild.owner else '未知'
            })
        
        # 按成员数排序
        guilds_info.sort(key=lambda x: x['member_count'], reverse=True)
        
        embed = discord.Embed(
            title="📝 服务器列表",
            description=f"机器人当前在 {len(guilds_info)} 个服务器中",
            color=0x4ecdc4
        )
        
        for guild_info in guilds_info[:10]:
            embed.add_field(
                name=f"🏰 {guild_info['name']}",
                value=f"ID: {guild_info['id']}\n" +
                      f"成员: {guild_info['member_count']}\n" +
                      f"抽奖: {guild_info['lottery_count']}\n" +
                      f"所有者: {guild_info['owner']}",
                inline=True
            )
        
        if len(guilds_info) > 10:
            embed.set_footer(text=f"显示前10个服务器，总共{len(guilds_info)}个")
        
        await interaction.followup.send(embed=embed, ephemeral=True)

class LogViewerView(discord.ui.View):
    """日志查看器视图"""
    
    def __init__(self):
        super().__init__(timeout=300)
    
    @discord.ui.button(label="🔄 刷新日志", style=discord.ButtonStyle.primary)
    async def refresh_logs(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ 权限不足！", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            with open('bot.log', 'r', encoding='utf-8') as f:
                lines = f.readlines()
                recent_logs = lines[-50:]
            
            log_content = ''.join(recent_logs)
            if len(log_content) > 1900:
                log_content = log_content[-1900:]
                log_content = "..." + log_content
            
            embed = discord.Embed(
                title="📝 机器人运行日志 (已刷新)",
                description=f"```\n{log_content}\n```",
                color=0x4ecdc4
            )
            
            embed.set_footer(text=f"刷新时间: {datetime.datetime.now().strftime('%H:%M:%S')}")
            
        except Exception as e:
            embed = discord.Embed(
                title="📝 日志刷新失败",
                description=f"错误: {e}",
                color=0xff6b6b
            )
        
        await interaction.followup.send(embed=embed, ephemeral=True)

class AdvancedSettingsView(discord.ui.View):
    """高级设置视图"""
    
    def __init__(self):
        super().__init__(timeout=300)
    
    @discord.ui.button(label="📊 系统信息", style=discord.ButtonStyle.primary)
    async def system_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ 权限不足！", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        import psutil
        import sys
        
        # 获取系统信息
        memory = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=1)
        
        embed = discord.Embed(
            title="📊 系统信息",
            color=0x4ecdc4
        )
        
        embed.add_field(
            name="🔧 Python信息",
            value=f"Python版本: {sys.version.split()[0]}\n" +
                  f"Discord.py: {discord.__version__}",
            inline=True
        )
        
        embed.add_field(
            name="💻 系统资源",
            value=f"CPU使用率: {cpu_percent}%\n" +
                  f"内存使用: {memory.percent}%\n" +
                  f"可用内存: {memory.available // (1024**3):.1f}GB",
            inline=True
        )
        
        embed.add_field(
            name="🤖 机器人状态",
            value=f"延迟: {round(bot.latency * 1000)}ms\n" +
                  f"服务器数: {len(bot.guilds)}\n" +
                  f"用户数: {len(bot.users)}",
            inline=True
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="📡 状态设置", style=discord.ButtonStyle.secondary)
    async def status_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ 权限不足！", ephemeral=True)
            return
        
        modal = StatusSettingsModal()
        await interaction.response.send_modal(modal)

class RealtimeMonitorView(discord.ui.View):
    """实时监控视图"""
    
    def __init__(self):
        super().__init__(timeout=300)
    
    @discord.ui.button(label="🔄 刷新监控", style=discord.ButtonStyle.primary)
    async def refresh_monitor(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ 权限不足！", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        import psutil
        import sys
        import time
        
        # 获取系统信息
        memory = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=1)
        
        embed = discord.Embed(
            title="🎯 实时监控面板 (已刷新)",
            description="机器人和系统的实时状态监控",
            color=0x9c27b0
        )
        
        embed.add_field(
            name="🤖 机器人状态",
            value=f"延迟: {round(bot.latency * 1000)}ms\n" +
                  f"服务器数: {len(bot.guilds)}\n" +
                  f"用户数: {len(bot.users)}\n" +
                  f"活跃抽奖: {len(bot.active_lotteries)}",
            inline=True
        )
        
        embed.add_field(
            name="💻 系统资源",
            value=f"CPU使用率: {cpu_percent}%\n" +
                  f"内存使用: {memory.percent}%\n" +
                  f"可用内存: {memory.available // (1024**3):.1f}GB",
            inline=True
        )
        
        embed.add_field(
            name="🔧 技术信息",
            value=f"Python: {sys.version.split()[0]}\n" +
                  f"Discord.py: {discord.__version__}\n" +
                  f"当前时间: {datetime.datetime.now().strftime('%H:%M:%S')}",
            inline=True
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)

# 新增的模态框类
class UserSearchModal(discord.ui.Modal):
    """用户搜索模态框"""
    
    def __init__(self):
        super().__init__(title="🔍 用户搜索")
        
        self.user_input = discord.ui.TextInput(
            label="用户ID或用户名",
            placeholder="输入用户ID或用户名进行搜索...",
            required=True,
            max_length=100
        )
        
        self.add_item(self.user_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        search_term = self.user_input.value.strip()
        
        # 尝试按ID搜索
        try:
            user_id = int(search_term)
            user = bot.get_user(user_id)
        except ValueError:
            # 按用户名搜索
            user = discord.utils.find(lambda u: search_term.lower() in u.display_name.lower(), bot.users)
        
        if not user:
            await interaction.followup.send("❌ 未找到该用户", ephemeral=True)
            return
        
        # 获取用户统计
        cursor = bot.conn.cursor()
        
        # 参与次数
        cursor.execute('SELECT COUNT(*) FROM participants WHERE user_id = ?', (user.id,))
        participation_count = cursor.fetchone()[0]
        
        # 中奖次数
        cursor.execute('SELECT COUNT(*) FROM winners WHERE user_id = ?', (user.id,))
        win_count = cursor.fetchone()[0]
        
        # 创建的抽奖
        cursor.execute('SELECT COUNT(*) FROM lotteries WHERE creator_id = ?', (user.id,))
        created_count = cursor.fetchone()[0]
        
        embed = discord.Embed(
            title=f"🔍 用户信息: {user.display_name}",
            color=0x4ecdc4
        )
        
        embed.set_thumbnail(url=user.display_avatar.url)
        
        embed.add_field(
            name="📊 基本信息",
            value=f"用户ID: {user.id}\n" +
                  f"用户名: {user.name}\n" +
                  f"显示名: {user.display_name}",
            inline=True
        )
        
        win_rate = (win_count / participation_count * 100) if participation_count > 0 else 0
        embed.add_field(
            name="🎯 抽奖统计",
            value=f"参与次数: {participation_count}\n" +
                  f"中奖次数: {win_count}\n" +
                  f"中奖率: {win_rate:.1f}%\n" +
                  f"创建抽奖: {created_count}",
            inline=True
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)

class GuildSearchModal(discord.ui.Modal):
    """服务器搜索模态框"""
    
    def __init__(self):
        super().__init__(title="📊 服务器搜索")
        
        self.guild_input = discord.ui.TextInput(
            label="服务器ID或名称",
            placeholder="输入服务器ID或名称进行搜索...",
            required=True,
            max_length=100
        )
        
        self.add_item(self.guild_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        search_term = self.guild_input.value.strip()
        
        # 尝试按ID搜索
        try:
            guild_id = int(search_term)
            guild = bot.get_guild(guild_id)
        except ValueError:
            # 按名称搜索
            guild = discord.utils.find(lambda g: search_term.lower() in g.name.lower(), bot.guilds)
        
        if not guild:
            await interaction.followup.send("❌ 未找到该服务器", ephemeral=True)
            return
        
        # 获取服务器统计
        cursor = bot.conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM lotteries WHERE guild_id = ?', (guild.id,))
        total_lotteries = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM lotteries WHERE guild_id = ? AND status = "active"', (guild.id,))
        active_lotteries = cursor.fetchone()[0]
        
        cursor.execute('''
            SELECT COUNT(*) FROM participants p 
            JOIN lotteries l ON p.lottery_id = l.id 
            WHERE l.guild_id = ?
        ''', (guild.id,))
        total_participants = cursor.fetchone()[0]
        
        embed = discord.Embed(
            title=f"📊 服务器信息: {guild.name}",
            color=0x4ecdc4
        )
        
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        
        embed.add_field(
            name="🏰 基本信息",
            value=f"服务器ID: {guild.id}\n" +
                  f"成员数: {guild.member_count}\n" +
                  f"所有者: {guild.owner.display_name if guild.owner else '未知'}\n" +
                  f"创建时间: {guild.created_at.strftime('%Y-%m-%d')}",
            inline=True
        )
        
        embed.add_field(
            name="🎲 抽奖统计",
            value=f"总抽奖数: {total_lotteries}\n" +
                  f"活跃抽奖: {active_lotteries}\n" +
                  f"总参与: {total_participants}",
            inline=True
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)

class StatusSettingsModal(discord.ui.Modal):
    """状态设置模态框"""
    
    def __init__(self):
        super().__init__(title="📡 机器人状态设置")
        
        self.status_input = discord.ui.TextInput(
            label="状态文本",
            placeholder="输入新的机器人状态文本...",
            required=True,
            max_length=128
        )
        
        self.add_item(self.status_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        status_text = self.status_input.value.strip()
        
        try:
            # 设置机器人状态
            activity = discord.Game(name=status_text)
            await bot.change_presence(activity=activity)
            
            embed = discord.Embed(
                title="✅ 状态设置成功",
                description=f"机器人状态已更新为: **{status_text}**",
                color=0x4ecdc4
            )
            
        except Exception as e:
            embed = discord.Embed(
                title="❌ 状态设置失败",
                description=f"错误: {e}",
                color=0xff6b6b
            )
        
        await interaction.followup.send(embed=embed, ephemeral=True)

# 添加一些基本的斜杠命令用于测试
@bot.tree.command(name="测试抽奖", description="创建一个测试抽奖（带参与按钮）")
async def test_lottery(interaction: discord.Interaction, 
                      title: str = "测试抽奖", 
                      description: str = "这是一个测试抽奖",
                      duration: int = 10):
    """创建测试抽奖命令"""
    try:
        # 获取数据库连接
        cursor = bot.conn.cursor()
        
        # 计算结束时间
        end_time = datetime.datetime.now() + datetime.timedelta(minutes=duration)
        
        # 创建抽奖记录
        cursor.execute("""
            INSERT INTO lotteries (guild_id, channel_id, creator_id, title, description, 
                                 prizes, end_time, status, allow_multiple_entries)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 1)
        """, (
            interaction.guild.id, interaction.channel.id, interaction.user.id, 
            title, description, '["1个奖品"]', end_time.isoformat()
        ))
        
        lottery_id = cursor.lastrowid
        bot.conn.commit()
        
        # 创建抽奖嵌入消息
        embed = discord.Embed(
            title=f"🎲 {title}",
            description=description,
            color=0x3498db
        )
        
        embed.add_field(name="🏆 中奖人数", value="1", inline=True)
        embed.add_field(name="👥 参与人数", value="0", inline=True)
        
        countdown = bot.format_countdown(end_time)
        embed.add_field(name="⏰ 剩余时间", value=countdown, inline=True)
        
        embed.add_field(name="🎯 抽奖ID", value=str(lottery_id), inline=True)
        embed.add_field(name="👤 创建者", value=str(interaction.user), inline=True)
        embed.add_field(name="📅 创建时间", value=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), inline=True)
        
        embed.set_footer(text="点击下方按钮参与抽奖！")
        
        # 添加参与按钮
        view = LotteryParticipateView(lottery_id)
        
        await interaction.response.send_message(embed=embed, view=view)
        
        logger.info(f"用户 {interaction.user} 创建了测试抽奖: {title}")
        
    except Exception as e:
        logger.error(f"创建测试抽奖时出错: {e}")
        await interaction.response.send_message("❌ 创建抽奖时出现错误，请稍后重试。", ephemeral=True)



if __name__ == "__main__":
    # 添加启动时间记录
    import time
    bot.start_time = time.time()
    
    # 从环境变量读取token
    TOKEN = os.getenv('DISCORD_TOKEN')
    
    if not TOKEN:
        print("❌ 请在 .env 文件中设置 DISCORD_TOKEN")
        exit(1)
    
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"机器人启动失败: {e}")
