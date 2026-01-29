#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 视频转发机器人 - 主程序
支持多群组、智能去重、关键词过滤、管理员通知
"""

import sys
import logging
import asyncio
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
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


async def post_init(application: Application):
    """机器人启动后的初始化工作"""
    logger.info("=" * 60)
    logger.info("🤖 Telegram 视频转发机器人已启动")
    logger.info("=" * 60)
    
    # 获取 handler 实例
    handler = application.bot_data.get('handler')
    if handler:
        await handler.send_startup_notification(application.bot)
    
    # 清理旧数据库记录
    db = application.bot_data.get('database')
    if db:
        await db.cleanup_old_records(days=30)


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
        
        # 6. 收集所有需要监听的源群组
        source_chat_ids = list(set([
            rule["source_chat_id"] 
            for rule in config.forwarding_rules 
            if rule.get("enabled", True)
        ]))
        
        logger.info(f"监听源群组: {source_chat_ids}")
        
        # 7. 注册视频消息处理器
        for source_chat_id in source_chat_ids:
            source_filter = filters.Chat(chat_id=source_chat_id)
            video_filter = filters.VIDEO | filters.VideoNote.ALL
            
            application.add_handler(
                MessageHandler(source_filter & video_filter, handler.handle_video)
            )
        
        # 8. 注册管理员指令
        application.add_handler(CommandHandler("stats", handler.handle_command_stats))
        application.add_handler(CommandHandler("reload", handler.handle_command_reload))
        
        # 9. 异步初始化数据库
        async def init_database():
            await database.init_db()
        
        # 运行数据库初始化
        import asyncio
        asyncio.get_event_loop().run_until_complete(init_database())
        
        # 10. 启动机器人
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
