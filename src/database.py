#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库模块 - 用于智能去重
使用 SQLite 存储已转发视频的唯一标识符 (file_unique_id)
"""

import aiosqlite
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


class Database:
    """异步 SQLite 数据库管理器"""
    
    def __init__(self, db_path: str = "data/bot.db"):
        """
        初始化数据库
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        # 确保数据目录存在
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    async def init_db(self):
        """初始化数据库表结构"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS forwarded_videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_unique_id TEXT UNIQUE NOT NULL,
                    source_chat_id INTEGER NOT NULL,
                    target_chat_id INTEGER NOT NULL,
                    forwarded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 创建索引以加速查询
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_file_unique_id 
                ON forwarded_videos(file_unique_id)
            """)
            
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_forwarded_at 
                ON forwarded_videos(forwarded_at)
            """)
            
            await db.commit()
            logger.info("✓ 数据库初始化完成")
    
    async def is_duplicate(self, file_unique_id: str, expire_hours: int = 24) -> bool:
        """
        检查视频是否在指定时间内已转发过
        
        Args:
            file_unique_id: Telegram 文件唯一 ID
            expire_hours: 去重时效（小时），默认 24 小时
        
        Returns:
            True: 已转发过（重复）
            False: 未转发过（新视频）
        """
        cutoff_time = datetime.now() - timedelta(hours=expire_hours)
        
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT COUNT(*) FROM forwarded_videos 
                WHERE file_unique_id = ? AND forwarded_at > ?
                """,
                (file_unique_id, cutoff_time)
            ) as cursor:
                result = await cursor.fetchone()
                return result[0] > 0
    
    async def add_forwarded(self, file_unique_id: str, source_chat_id: int, target_chat_id: int):
        """
        记录已转发的视频
        
        Args:
            file_unique_id: Telegram 文件唯一 ID
            source_chat_id: 源群组 ID
            target_chat_id: 目标群组 ID
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO forwarded_videos 
                    (file_unique_id, source_chat_id, target_chat_id, forwarded_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (file_unique_id, source_chat_id, target_chat_id, datetime.now())
                )
                await db.commit()
        except Exception as e:
            logger.error(f"记录转发失败: {e}")
    
    async def cleanup_old_records(self, days: int = 30):
        """
        清理旧记录以节省空间
        
        Args:
            days: 保留天数，默认 30 天
        """
        cutoff_time = datetime.now() - timedelta(days=days)
        
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM forwarded_videos WHERE forwarded_at < ?",
                (cutoff_time,)
            )
            deleted_count = cursor.rowcount
            await db.commit()
            
            if deleted_count > 0:
                logger.info(f"✓ 清理了 {deleted_count} 条过期记录")
    
    async def get_stats(self) -> dict:
        """
        获取统计信息
        
        Returns:
            包含总转发数、今日转发数等统计数据的字典
        """
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        async with aiosqlite.connect(self.db_path) as db:
            # 总转发数
            async with db.execute("SELECT COUNT(*) FROM forwarded_videos") as cursor:
                total = (await cursor.fetchone())[0]
            
            # 今日转发数
            async with db.execute(
                "SELECT COUNT(*) FROM forwarded_videos WHERE forwarded_at > ?",
                (today_start,)
            ) as cursor:
                today = (await cursor.fetchone())[0]
            
            return {
                "total_forwarded": total,
                "today_forwarded": today
            }
