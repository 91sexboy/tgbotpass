#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
消息处理模块
包含视频转发、关键词过滤、管理员通知等核心功能
"""

import logging
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import RetryAfter, TelegramError
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config
    from .database import Database

logger = logging.getLogger(__name__)


class MessageHandler:
    """消息处理器"""
    
    def __init__(self, config: 'Config', database: 'Database'):
        """
        初始化消息处理器
        
        Args:
            config: 配置管理器实例
            database: 数据库管理器实例
        """
        self.config = config
        self.db = database
    
    async def handle_video(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        处理视频消息的核心函数
        
        Args:
            update: Telegram 更新对象
            context: 上下文对象
        """
        try:
            message = update.message
            if not message or not message.video:
                return
            
            source_chat_id = message.chat_id
            video = message.video
            file_unique_id = video.file_unique_id
            
            logger.info(f"收到视频 - Chat ID: {source_chat_id}, Message ID: {message.message_id}")
            
            # 获取匹配的转发规则
            rules = self.config.get_targets_for_source(source_chat_id)
            
            if not rules:
                logger.debug(f"源群组 {source_chat_id} 没有配置转发规则")
                return
            
            for rule in rules:
                await self._process_rule(message, file_unique_id, rule, context)
        
        except Exception as e:
            logger.error(f"处理视频时发生错误: {e}", exc_info=True)
            await self._notify_admin(context, f"❌ 处理视频时发生错误\n\n错误信息: {str(e)}")
    
    async def _process_rule(self, message, file_unique_id: str, rule: dict, context: ContextTypes.DEFAULT_TYPE):
        """
        处理单条转发规则
        
        Args:
            message: Telegram 消息对象
            file_unique_id: 视频唯一 ID
            rule: 转发规则
            context: 上下文对象
        """
        # 1. 检查关键词黑名单
        if not self._check_keywords(message, rule):
            logger.info(f"视频因关键词过滤被拦截")
            return
        
        # 2. 检查是否重复
        if self.config.deduplication_enabled:
            if await self.db.is_duplicate(file_unique_id, self.config.deduplication_expire_hours):
                logger.info(f"视频已在 {self.config.deduplication_expire_hours} 小时内转发过，跳过")
                return
        
        # 3. 转发到所有目标群组
        for target_chat_id in rule["target_chat_ids"]:
            success = await self._forward_to_target(
                message, 
                target_chat_id, 
                context
            )
            
            # 4. 记录已转发
            if success and self.config.deduplication_enabled:
                await self.db.add_forwarded(file_unique_id, message.chat_id, target_chat_id)
    
    def _check_keywords(self, message, rule: dict) -> bool:
        """
        检查关键词过滤
        
        Args:
            message: Telegram 消息对象
            rule: 转发规则
        
        Returns:
            True: 通过检查
            False: 被过滤
        """
        caption = message.caption or ""
        
        # 黑名单检查
        blacklist = rule.get("keywords_blacklist", [])
        for keyword in blacklist:
            if keyword.lower() in caption.lower():
                logger.info(f"视频标题包含黑名单关键词: {keyword}")
                return False
        
        # 白名单检查（如果配置了白名单，则必须包含白名单关键词）
        whitelist = rule.get("keywords_whitelist", [])
        if whitelist:
            found = any(keyword.lower() in caption.lower() for keyword in whitelist)
            if not found:
                logger.info(f"视频标题不包含白名单关键词")
                return False
        
        return True
    
    async def _forward_to_target(
        self, 
        message, 
        target_chat_id: int, 
        context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """
        转发视频到目标群组（纯净模式，不添加任何标签）
        
        Args:
            message: 源消息对象
            target_chat_id: 目标群组 ID
            context: 上下文对象
        
        Returns:
            转发是否成功
        """
        try:
            # 使用 copy_message 实现无痕转发
            await context.bot.copy_message(
                chat_id=target_chat_id,
                from_chat_id=message.chat_id,
                message_id=message.message_id,
                caption=message.caption,  # 保留原始描述，不添加任何内容
                caption_entities=message.caption_entities  # 保留格式
            )
            
            logger.info(f"✓ 视频转发成功 - 目标: {target_chat_id}, 源消息ID: {message.message_id}")
            return True
        
        except RetryAfter as e:
            # Telegram 限流处理
            wait_seconds = e.retry_after
            logger.warning(f"⚠ 触发 Telegram 限流，等待 {wait_seconds} 秒后重试...")
            await asyncio.sleep(wait_seconds)
            
            # 重试一次
            try:
                await context.bot.copy_message(
                    chat_id=target_chat_id,
                    from_chat_id=message.chat_id,
                    message_id=message.message_id,
                    caption=message.caption,
                    caption_entities=message.caption_entities
                )
                logger.info(f"✓ 重试成功 - 目标: {target_chat_id}")
                return True
            except Exception as retry_error:
                logger.error(f"✗ 重试失败: {retry_error}")
                await self._notify_admin(context, f"⚠ 转发重试失败\n目标: {target_chat_id}\n错误: {retry_error}")
                return False
        
        except TelegramError as e:
            logger.error(f"✗ Telegram API 错误: {e}")
            await self._notify_admin(context, f"❌ Telegram API 错误\n目标: {target_chat_id}\n错误: {e}")
            return False
        
        except Exception as e:
            logger.error(f"✗ 转发失败: {e}", exc_info=True)
            await self._notify_admin(context, f"❌ 转发失败\n目标: {target_chat_id}\n错误: {e}")
            return False
    
    async def _notify_admin(self, context: ContextTypes.DEFAULT_TYPE, message: str):
        """
        向管理员发送通知
        
        Args:
            context: 上下文对象
            message: 通知内容
        """
        if not self.config.notify_on_error or not self.config.admin_notifications_enabled:
            return
        
        try:
            await context.bot.send_message(
                chat_id=self.config.admin_user_id,
                text=message
            )
        except Exception as e:
            logger.error(f"发送管理员通知失败: {e}")
    
    async def handle_command_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        处理 /stats 命令 - 显示统计信息
        """
        if update.effective_user.id != self.config.admin_user_id:
            return
        
        try:
            stats = await self.db.get_stats()
            
            message = (
                f"📊 机器人统计\n\n"
                f"总转发数: {stats['total_forwarded']}\n"
                f"今日转发数: {stats['today_forwarded']}\n"
            )
            
            await update.message.reply_text(message)
        
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            await update.message.reply_text(f"❌ 获取统计信息失败: {e}")
    
    async def handle_command_reload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        处理 /reload 命令 - 重新加载配置
        """
        if update.effective_user.id != self.config.admin_user_id:
            return
        
        try:
            self.config.reload()
            await update.message.reply_text("✓ 配置已重新加载")
        
        except Exception as e:
            logger.error(f"重新加载配置失败: {e}")
            await update.message.reply_text(f"❌ 重新加载配置失败: {e}")
    
    async def send_startup_notification(self, context: ContextTypes.DEFAULT_TYPE):
        """向管理员发送启动通知"""
        if not self.config.notify_on_start or not self.config.admin_notifications_enabled:
            return
        
        try:
            rules_count = len(self.config.forwarding_rules)
            message = (
                f"🤖 机器人已启动\n\n"
                f"转发规则数: {rules_count}\n"
                f"去重功能: {'✓ 已启用' if self.config.deduplication_enabled else '✗ 已禁用'}\n"
            )
            
            await context.bot.send_message(
                chat_id=self.config.admin_user_id,
                text=message
            )
        except Exception as e:
            logger.error(f"发送启动通知失败: {e}")
