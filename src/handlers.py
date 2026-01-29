#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
消息处理模块
包含视频转发、关键词过滤、管理员通知等核心功能
"""

import asyncio
import logging
import os
import signal
from typing import TYPE_CHECKING

from telegram import Update
from telegram.error import RetryAfter, TelegramError
from telegram.ext import ContextTypes

if TYPE_CHECKING:
    from .config import Config
    from .database import Database

logger = logging.getLogger(__name__)


class MessageHandler:
    """消息处理器"""

    def __init__(self, config: "Config", database: "Database"):
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
            elif (
                message.document
                and message.document.mime_type
                and message.document.mime_type.startswith("video/")
            ):
                # 以文件形式发送的视频
                file_unique_id = message.document.file_unique_id
                video_type = "video_file"
            else:
                # 不是视频相关的消息，忽略
                return

            logger.info(
                f"收到{video_type} - Chat ID: {source_chat_id}, Message ID: {message.message_id}"
            )

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

    async def _process_rule(
        self, message, file_unique_id: str, rule: dict, context: ContextTypes.DEFAULT_TYPE
    ):
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
            logger.info("视频因关键词过滤被拦截")
            return

        # 2. 检查是否重复
        if self.config.deduplication_enabled:
            if await self.db.is_duplicate(
                file_unique_id, self.config.deduplication_expire_hours
            ):
                logger.info(
                    f"视频已在 {self.config.deduplication_expire_hours} 小时内转发过，跳过"
                )
                return

        # 3. 转发到所有目标群组
        for target_chat_id in rule["target_chat_ids"]:
            success = await self._forward_to_target(message, target_chat_id, context)

            # 4. 记录已转发
            if success and self.config.deduplication_enabled:
                await self.db.add_forwarded(
                    file_unique_id, message.chat_id, target_chat_id
                )

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
                logger.info("视频标题不包含白名单关键词")
                return False

        return True

    async def _forward_to_target(
        self, message, target_chat_id: int, context: ContextTypes.DEFAULT_TYPE
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
                caption=message.caption,
                caption_entities=message.caption_entities,
            )

            logger.info(
                f"✓ 视频转发成功 - 目标: {target_chat_id}, 源消息ID: {message.message_id}"
            )
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
                    caption_entities=message.caption_entities,
                )
                logger.info(f"✓ 重试成功 - 目标: {target_chat_id}")
                return True
            except Exception as retry_error:
                logger.error(f"✗ 重试失败: {retry_error}")
                await self._notify_admin(
                    context,
                    f"⚠ 转发重试失败\n目标: {target_chat_id}\n错误: {retry_error}",
                )
                return False

        except TelegramError as e:
            logger.error(f"✗ Telegram API 错误: {e}")
            await self._notify_admin(
                context, f"❌ Telegram API 错误\n目标: {target_chat_id}\n错误: {e}"
            )
            return False

        except Exception as e:
            logger.error(f"✗ 转发失败: {e}", exc_info=True)
            await self._notify_admin(
                context, f"❌ 转发失败\n目标: {target_chat_id}\n错误: {e}"
            )
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
                text=message,
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
                "📊 机器人统计\n\n"
                f"总转发数: {stats['total_forwarded']}\n"
                f"今日转发数: {stats['today_forwarded']}\n"
            )

            await update.message.reply_text(message)

        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            await update.message.reply_text(f"❌ 获取统计信息失败: {e}")

    def _is_admin(self, update: Update) -> bool:
        user = update.effective_user
        if not user or user.id != self.config.admin_user_id:
            logger.warning(
                f"非管理员尝试使用命令: ID {user.id if user else 'Unknown'}"
            )
            return False
        return True

    async def handle_command_reload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /reload 命令 - 重载配置"""
        if not self._is_admin(update):
            return

        try:
            self.config.reload()
            await update.message.reply_text("✅ 配置已成功重载")
            logger.info("管理员手动重载配置")
        except Exception as e:
            await update.message.reply_text(f"❌ 重载失败: {e}")

    async def handle_command_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /add 命令 - 添加转发规则"""
        if not self._is_admin(update):
            return

        args = context.args
        if len(args) < 2:
            await update.message.reply_text("❌ 用法: /add <源群ID> <目标群ID>")
            return

        try:
            source_id = int(args[0])
            target_id = int(args[1])

            source_title = None
            target_title = None

            try:
                source_chat = await context.bot.get_chat(source_id)
                source_title = source_chat.title or str(source_id)
            except Exception:
                source_title = str(source_id)

            try:
                target_chat = await context.bot.get_chat(target_id)
                target_title = target_chat.title or str(target_id)
            except Exception:
                target_title = str(target_id)

            self.config.add_rule(source_id, target_id, source_title, target_title)
            await update.message.reply_text(
                f"✅ 已添加规则: {source_title} ({source_id}) -> {target_title} ({target_id})"
            )
        except ValueError:
            await update.message.reply_text("❌ ID必须是整数")
        except Exception as e:
            await update.message.reply_text(f"❌ 添加失败: {e}")

    async def handle_command_del(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /del 命令 - 删除转发规则"""
        if not self._is_admin(update):
            return

        args = context.args
        if len(args) < 1:
            await update.message.reply_text("❌ 用法: /del <源群ID>")
            return

        try:
            source_id = int(args[0])

            if self.config.remove_rule(source_id):
                await update.message.reply_text(f"✅ 已删除源 {source_id} 的规则")
            else:
                await update.message.reply_text("❌ 未找到对应规则")
        except ValueError:
            await update.message.reply_text("❌ ID必须是整数")
        except Exception as e:
            await update.message.reply_text(f"❌ 删除失败: {e}")

    async def handle_command_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /list 命令 - 列出所有规则"""
        if not self._is_admin(update):
            return

        rules = self.config.forwarding_rules
        if not rules:
            await update.message.reply_text("📭 当前没有转发规则")
            return

        msg_lines = ["📋 当前转发规则:"]
        for idx, rule in enumerate(rules, start=1):
            source = rule.get("source_chat_title") or rule["source_chat_id"]
            source_id = rule["source_chat_id"]
            target_ids = rule["target_chat_ids"]
            target_titles = rule.get("target_chat_titles", {})
            targets_display = []
            for target_id in target_ids:
                target_name = target_titles.get(str(target_id)) or str(target_id)
                targets_display.append(f"{target_name} ({target_id})")
            msg_lines.append(
                f"{idx}. {source} ({source_id}) -> {', '.join(targets_display)}"
            )

        await update.message.reply_text("\n".join(msg_lines))

    async def handle_command_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /stop 命令 - 停止迁移或机器人"""
        if not self._is_admin(update):
            return

        if self.is_migrating:
            self.is_migrating = False
            await update.message.reply_text("🛑 已请求停止迁移任务")
            return

        await update.message.reply_text("👋 机器人正在停止...")
        logger.info("管理员发送停止指令")
        os.kill(os.getpid(), signal.SIGINT)

    async def send_startup_notification(self, bot):
        """发送启动通知给管理员"""
        if not self.config.admin_notifications_enabled or not self.config.notify_on_start:
            return
        try:
            await bot.send_message(
                chat_id=self.config.admin_user_id,
                text="🚀 机器人已启动 (v2.2.1)\n✅ 等待接收消息...",
            )
        except Exception as e:
            logger.error(f"发送启动通知失败: {e}")

    async def handle_command_migrate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        处理 /migrate 命令 - 历史消息迁移
        用法: /migrate <源群ID> <目标群ID> <起始消息ID> <结束消息ID>
        """
        if not self._is_admin(update):
            return

        if self.is_migrating:
            await update.message.reply_text("⚠️ 正在进行迁移任务，请等待完成后再试")
            return

        args = context.args
        if len(args) < 4:
            await update.message.reply_text(
                "❌ 用法: /migrate <源ID> <目标ID> <起始ID> <结束ID>\n"
                "例如: /migrate -100123 -100456 100 200"
            )
            return

        try:
            source_chat_id = int(args[0])
            target_chat_id = int(args[1])
            start_id = int(args[2])
            end_id = int(args[3])
        except ValueError:
            await update.message.reply_text("❌ ID必须是整数")
            return

        if start_id > end_id:
            start_id, end_id = end_id, start_id

        status_msg = await update.message.reply_text(
            f"🚀 开始迁移...\n源: {source_chat_id}\n目标: {target_chat_id}\n"
            f"范围: {start_id} - {end_id}"
        )

        self.is_migrating = True
        success = 0
        failed = 0
        skipped = 0

        current_id = start_id
        try:
            while current_id <= end_id:
                if not self.is_migrating:
                    break

                try:
                    await context.bot.copy_message(
                        chat_id=target_chat_id,
                        from_chat_id=source_chat_id,
                        message_id=current_id,
                    )
                    success += 1
                except BadRequest as e:
                    # 常见情况: 消息不存在、不是媒体等，跳过
                    skipped += 1
                    logger.debug(f"跳过消息 {current_id}: {e}")
                except RetryAfter as e:
                    await asyncio.sleep(e.retry_after)
                    continue
                except TelegramError as e:
                    failed += 1
                    logger.warning(f"迁移失败 {current_id}: {e}")

                if (current_id - start_id + 1) % 20 == 0:
                    await status_msg.edit_text(
                        f"🚀 迁移进行中...\n"
                        f"源: {source_chat_id}\n目标: {target_chat_id}\n"
                        f"进度: {current_id}/{end_id}\n"
                        f"成功: {success}, 跳过: {skipped}, 失败: {failed}"
                    )

                current_id += 1

        finally:
            self.is_migrating = False
            await status_msg.edit_text(
                f"✅ 迁移完成\n"
                f"成功: {success}, 跳过: {skipped}, 失败: {failed}"
            )
