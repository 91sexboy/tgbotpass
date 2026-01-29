#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 视频转发机器人 - 主程序
支持多群组、智能去重、关键词过滤、管理员通知、动态规则管理、历史迁移
"""

import sys
import logging
import asyncio
import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    filters,
)

from src.config import Config
from src.database import Database
from src.handlers import MessageHandler as Handler

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        RotatingFileHandler('bot.log', maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


async def cleanup_job(context):
    db = context.application.bot_data.get('database')
    if db:
        await db.cleanup_old_records(days=30)


async def post_init(application: Application):
    """机器人启动后的初始化工作"""
    logger.info("=" * 60)
    logger.info("🤖 Telegram 视频转发机器人已启动 (v2.2.0)")
    logger.info("=" * 60)
    
    # 获取 handler 实例
    handler = application.bot_data.get('handler')
    if handler:
        await handler.send_startup_notification(application.bot)
    
    # 清理旧数据库记录
    db = application.bot_data.get('database')
    if db:
        await db.cleanup_old_records(days=30)

    # 定时清理数据库（每天凌晨 4 点）
    if application.job_queue:
        application.job_queue.run_daily(
            cleanup_job,
            time=datetime.time(hour=4, minute=0, second=0)
        )


def main():
    """主函数"""
    try:
        # 1. 加载配置
        logger.info("正在加载配置...")
        config = Config("config/config.json")
        logger.info(f"✓ 已加载 {len(config.forwarding_rules)} 条转发规则")
        
        # 2. 初始化数据库
        logger.info("正在初始化数据库...")
        database = Database("data/bot.db")
        
        # 3. 创建消息处理器
        handler = Handler(config, database)
        
        # 4. 创建 Telegram 应用
        application = Application.builder().token(config.bot_token).build()
        
        # 存储实例到 bot_data（供 post_init 使用）
        application.bot_data['handler'] = handler
        application.bot_data['database'] = database
        
        # 5. 注册启动回调
        application.post_init = post_init
        
        # 6. 注册全局视频消息处理器（支持动态规则变更，无需重启）
        video_filter = filters.VIDEO | filters.VideoNote.ALL | filters.Document.VIDEO
        application.add_handler(
            MessageHandler(video_filter, handler.handle_video)
        )
        logger.info("✓ 已启用全局视频监听模式（支持动态规则）")
        
        # 7. 注册管理员指令
        application.add_handler(CommandHandler("stats", handler.handle_command_stats))
        application.add_handler(CommandHandler("reload", handler.handle_command_reload))
        application.add_handler(CommandHandler("add", handler.handle_command_add))
        application.add_handler(CommandHandler("del", handler.handle_command_del))
        application.add_handler(CommandHandler("list", handler.handle_command_list))
        application.add_handler(CommandHandler("stop", handler.handle_command_stop))
        application.add_handler(CommandHandler("migrate", handler.handle_command_migrate))
        
        # 8. 异步初始化数据库
        async def init_database():
            await database.init_db()
        
        # 运行数据库初始化
        import asyncio
        asyncio.get_event_loop().run_until_complete(init_database())
        
        # 9. 启动机器人
        logger.info("正在启动机器人...")
        logger.info("=" * 60)
        
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True  # 启动时忽略旧消息
        )
    
    except FileNotFoundError as e:
        logger.error(f"文件未找到: {e}")
        logger.info("请复制 config/config.example.json 为 config/config.json 并填写配置")
        sys.exit(1)
    
    except ValueError as e:
        logger.error(f"配置错误: {e}")
        sys.exit(1)
    
    except KeyboardInterrupt:
        logger.info("\n👋 机器人已手动停止")
    
    except Exception as e:
        logger.critical(f"💥 致命错误: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
