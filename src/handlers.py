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
from telegram.error import RetryAfter, TelegramError, BadRequest
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
        self.is_migrating = False
    
    async def handle_video(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        处理视频消息的核心函数（包括普通视频、视频笔记和视频文件）
        
        Args:
            update: Telegram 更新对象
            context: 上下文对象
        """
        try:
            message = update.message
            if not message:
                return
            
            source_chat_id = message.chat_id
            
            # 识别视频类型并获取 file_unique_id
            file_unique_id = None
            video_type = None
            
            if message.video:
                # 普通视频
                file_unique_id = message.video.file_unique_id
                video_type = "video"
            elif message.video_note:
                # 视频笔记（圆圈视频）
                file_unique_id = message.video_note.file_unique_id
                video_type = "video_note"
            elif message.document and message.document.mime_type and message.document.mime_type.startswith('video/'):
                # 以文件形式发送的视频
                file_unique_id = message.document.file_unique_id
                video_type = "video_file"
            else:
                # 不是视频相关的消息，忽略
                return
            
            logger.info(f"收到{video_type} - Chat ID: {source_chat_id}, Message ID: {message.message_id}")
            
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

    def _is_admin(self, update: Update) -> bool:
        user = update.effective_user
        return bool(user and user.id == self.config.admin_user_id)

    def _parse_int(self, value: str):
        try:
            return int(value)
        except Exception:
            return None

    async def handle_command_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        处理 /list 命令 - 显示全部转发规则
        """
        if not self._is_admin(update):
            return

        rules = self.config.forwarding_rules
        if not rules:
            await update.message.reply_text("⚠ 当前没有配置任何转发规则")
            return

        lines = ["📋 当前转发规则:"]
        for idx, rule in enumerate(rules, start=1):
            source_id = rule.get("source_chat_id")
            source_title = rule.get("source_chat_title") or str(source_id)
            target_ids = rule.get("target_chat_ids", [])
            target_titles = rule.get("target_chat_titles", {}) or {}

            targets_display = []
            for target_id in target_ids:
                title = target_titles.get(str(target_id)) or str(target_id)
                targets_display.append(f"{title} ({target_id})")

            lines.append(f"{idx}. {source_title} ({source_id}) -> {', '.join(targets_display)}")

        await update.message.reply_text("\n".join(lines))

    async def handle_command_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        处理 /add 命令 - 动态添加转发规则
        用法: /add <source_chat_id> <target_chat_id>
        """
        if not self._is_admin(update):
            return

        if not context.args or len(context.args) != 2:
            await update.message.reply_text("用法: /add <源群组ID> <目标群组ID>")
            return

        source_id = self._parse_int(context.args[0])
        target_id = self._parse_int(context.args[1])

        if source_id is None or target_id is None:
            await update.message.reply_text("❌ 参数必须是数字（群组ID）")
            return

        try:
            source_chat = await context.bot.get_chat(source_id)
            target_chat = await context.bot.get_chat(target_id)
        except TelegramError as e:
            await update.message.reply_text(
                f"❌ 无法访问指定群组/频道，请确认机器人已加入并具有权限\n错误: {e}"
            )
            return

        try:
            source_title = getattr(source_chat, "title", None) or str(source_id)
            target_title = getattr(target_chat, "title", None) or str(target_id)
            self.config.add_rule(source_id, target_id, source_title, target_title)
            await update.message.reply_text(
                f"✓ 已添加/更新规则: {source_title} ({source_id}) -> {target_title} ({target_id})"
            )
        except Exception as e:
            logger.error(f"添加规则失败: {e}")
            await update.message.reply_text(f"❌ 添加规则失败: {e}")

    async def handle_command_del(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        处理 /del 命令 - 删除源群组规则
        用法: /del <source_chat_id>
        """
        if not self._is_admin(update):
            return

        if not context.args or len(context.args) != 1:
            await update.message.reply_text("用法: /del <源群组ID>")
            return

        source_id = self._parse_int(context.args[0])
        if source_id is None:
            await update.message.reply_text("❌ 参数必须是数字（群组ID）")
            return

        try:
            removed = self.config.remove_rule(source_id)
            if removed:
                await update.message.reply_text(f"✓ 已删除源群组 {source_id} 的转发规则")
            else:
                await update.message.reply_text(f"⚠ 未找到源群组 {source_id} 的规则")
        except Exception as e:
            logger.error(f"删除规则失败: {e}")
            await update.message.reply_text(f"❌ 删除规则失败: {e}")

    async def handle_command_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        处理 /stop 命令 - 停止当前迁移任务
        """
        if not self._is_admin(update):
            return

        if self.is_migrating:
            self.is_migrating = False
            await update.message.reply_text("🛑 正在停止迁移任务...（当前消息处理完后生效）")
        else:
            await update.message.reply_text("⚠ 当前没有正在进行的迁移任务")

    async def handle_command_migrate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        处理 /migrate 命令 - 盲盒遍历频道历史视频
        用法: /migrate <source_id> <target_id> <start_id> <end_id>
        """
        if not self._is_admin(update):
            return

        if self.is_migrating:
            await update.message.reply_text("⚠ 已有迁移任务正在运行，请先 /stop 终止")
            return

        if not context.args or len(context.args) != 4:
            await update.message.reply_text(
                "用法: /migrate <源频道ID> <目标频道ID> <起始消息ID> <结束消息ID>"
            )
            return

        source_id = self._parse_int(context.args[0])
        target_id = self._parse_int(context.args[1])
        start_id = self._parse_int(context.args[2])
        end_id = self._parse_int(context.args[3])

        if None in (source_id, target_id, start_id, end_id):
            await update.message.reply_text("❌ 所有参数必须是数字")
            return

        if start_id <= 0 or end_id <= 0 or start_id > end_id:
            await update.message.reply_text("❌ 起始/结束消息ID不合法")
            return

        admin_chat_id = self.config.admin_user_id
        total = 0
        forwarded = 0
        skipped = 0
        missing = 0

        self.is_migrating = True

        status_message = await update.message.reply_text(
            f"🚀 开始迁移历史视频\n源: {source_id}\n目标: {target_id}\n范围: {start_id} -> {end_id}"
        )

        try:
            for message_id in range(start_id, end_id + 1):
                if not self.is_migrating:
                    try:
                        await status_message.edit_text("🛑 迁移任务已停止")
                    except Exception:
                        await update.message.reply_text("🛑 迁移任务已停止")
                    break
                total += 1

            try:
                forwarded_message = await context.bot.forward_message(
                    chat_id=admin_chat_id,
                    from_chat_id=source_id,
                    message_id=message_id
                )
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after)
                continue
            except BadRequest as e:
                if "message to forward not found" in str(e).lower():
                    missing += 1
                    continue
                logger.error(f"转发失败: {e}")
                skipped += 1
                continue
            except TelegramError as e:
                logger.error(f"转发失败: {e}")
                skipped += 1
                continue

            try:
                file_unique_id = None
                if forwarded_message.video:
                    file_unique_id = forwarded_message.video.file_unique_id
                elif forwarded_message.video_note:
                    file_unique_id = forwarded_message.video_note.file_unique_id
                elif forwarded_message.document and forwarded_message.document.mime_type and forwarded_message.document.mime_type.startswith('video/'):
                    file_unique_id = forwarded_message.document.file_unique_id

                if file_unique_id:
                    if self.config.deduplication_enabled:
                        if await self.db.is_duplicate(file_unique_id, self.config.deduplication_expire_hours):
                            skipped += 1
                        else:
                            await context.bot.copy_message(
                                chat_id=target_id,
                                from_chat_id=source_id,
                                message_id=message_id
                            )
                            await self.db.add_forwarded(file_unique_id, source_id, target_id)
                            forwarded += 1
                    else:
                        await context.bot.copy_message(
                            chat_id=target_id,
                            from_chat_id=source_id,
                            message_id=message_id
                        )
                        forwarded += 1
                else:
                    skipped += 1

            except RetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except TelegramError as e:
                logger.error(f"迁移消息失败: {e}")
                skipped += 1
            finally:
                try:
                    await context.bot.delete_message(chat_id=admin_chat_id, message_id=forwarded_message.message_id)
                except Exception:
                    pass

            if total % 50 == 0:
                try:
                    await status_message.edit_text(
                        f"进度: {message_id}/{end_id} | 已转发: {forwarded} | 跳过: {skipped} | 丢失: {missing}"
                    )
                except Exception:
                    await update.message.reply_text(
                        f"进度: {message_id}/{end_id} | 已转发: {forwarded} | 跳过: {skipped} | 丢失: {missing}"
                    )

                await asyncio.sleep(0.4)
        finally:
            self.is_migrating = False
    
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
