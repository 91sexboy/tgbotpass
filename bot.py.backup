#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 视频转发机器人
功能: 将源群组的视频自动复制到目标群组（无来源标签，独立消息）
"""

import os
import sys
import logging
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import RetryAfter, TelegramError

# 加载环境变量
load_dotenv()

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

# 从环境变量读取配置
BOT_TOKEN = os.getenv('BOT_TOKEN')
SOURCE_CHAT_ID = os.getenv('SOURCE_CHAT_ID')
TARGET_CHAT_ID = os.getenv('TARGET_CHAT_ID')

# 配置验证
def validate_config():
    """验证配置是否完整"""
    if not BOT_TOKEN:
        logger.error("错误: 未找到 BOT_TOKEN，请在 .env 文件中配置")
        sys.exit(1)
    if not SOURCE_CHAT_ID:
        logger.error("错误: 未找到 SOURCE_CHAT_ID，请在 .env 文件中配置")
        sys.exit(1)
    if not TARGET_CHAT_ID:
        logger.error("错误: 未找到 TARGET_CHAT_ID，请在 .env 文件中配置")
        sys.exit(1)
    
    logger.info("✓ 配置验证通过")
    logger.info(f"✓ 源群组: {SOURCE_CHAT_ID}")
    logger.info(f"✓ 目标群组: {TARGET_CHAT_ID}")


async def forward_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理视频消息的核心函数
    当源群组发送视频时，自动复制到目标群组
    """
    try:
        message = update.message
        
        # 记录收到的消息
        logger.info(f"收到视频 - Chat ID: {message.chat_id}, Message ID: {message.message_id}")
        
        # 使用 copy_message 实现无痕转发（不显示来源）
        await context.bot.copy_message(
            chat_id=TARGET_CHAT_ID,
            from_chat_id=message.chat_id,
            message_id=message.message_id,
            caption=message.caption,  # 保留原始描述文字
            caption_entities=message.caption_entities  # 保留格式（加粗/链接等）
        )
        
        logger.info(f"✓ 视频转发成功 - 源消息ID: {message.message_id}")
    
    except RetryAfter as e:
        # Telegram 限流处理
        wait_seconds = e.retry_after
        logger.warning(f"⚠ 触发 Telegram 限流，等待 {wait_seconds} 秒后重试...")
        await asyncio.sleep(wait_seconds)
        
        # 递归重试
        try:
            await context.bot.copy_message(
                chat_id=TARGET_CHAT_ID,
                from_chat_id=message.chat_id,
                message_id=message.message_id,
                caption=message.caption,
                caption_entities=message.caption_entities
            )
            logger.info(f"✓ 重试成功 - 源消息ID: {message.message_id}")
        except Exception as retry_error:
            logger.error(f"✗ 重试失败: {retry_error}")
    
    except TelegramError as e:
        logger.error(f"✗ Telegram API 错误: {e}")
    
    except Exception as e:
        logger.error(f"✗ 未知错误: {e}", exc_info=True)


async def post_init(application: Application):
    """机器人启动后的初始化工作"""
    logger.info("=" * 60)
    logger.info("🤖 Telegram 视频转发机器人已启动")
    logger.info("=" * 60)
    logger.info(f"监听群组: {SOURCE_CHAT_ID}")
    logger.info(f"转发目标: {TARGET_CHAT_ID}")
    logger.info("等待新视频...")
    logger.info("=" * 60)


def main():
    """主函数"""
    # 验证配置
    validate_config()
    
    # 创建应用
    application = Application.builder().token(BOT_TOKEN).build()
    
    # 注册启动回调
    application.post_init = post_init
    
    # 创建过滤器: 只监听源群组的视频和视频笔记
    source_filter = filters.Chat(chat_id=int(SOURCE_CHAT_ID))
    video_filter = filters.VIDEO | filters.VideoNote.ALL
    
    # 注册消息处理器
    application.add_handler(
        MessageHandler(source_filter & video_filter, forward_video)
    )
    
    # 启动机器人（长轮询模式，适合服务器部署）
    logger.info("正在启动机器人...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True  # 启动时忽略旧消息（防止重复转发）
    )


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n👋 机器人已手动停止")
    except Exception as e:
        logger.critical(f"💥 致命错误: {e}", exc_info=True)
        sys.exit(1)
