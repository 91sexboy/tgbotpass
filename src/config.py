#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置加载模块
支持从 JSON 文件加载配置，并提供热重载功能
"""

import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class Config:
    """配置管理器"""
    
    def __init__(self, config_path: str = "config/config.json"):
        """
        初始化配置管理器
        
        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path
        self.data: Dict[str, Any] = {}
        self.load()
    
    def load(self):
        """从文件加载配置"""
        try:
            config_file = Path(self.config_path)
            
            if not config_file.exists():
                logger.error(f"配置文件不存在: {self.config_path}")
                logger.info("请复制 config/config.example.json 为 config/config.json 并填写配置")
                raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
            
            with open(config_file, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            
            # 验证必需字段
            self._validate()
            
            logger.info(f"✓ 配置加载成功: {self.config_path}")
        
        except json.JSONDecodeError as e:
            logger.error(f"配置文件格式错误: {e}")
            raise
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
            raise
    
    def _validate(self):
        """验证配置完整性"""
        required_fields = ["bot_token", "admin_user_id", "forwarding_rules"]
        
        for field in required_fields:
            if field not in self.data:
                raise ValueError(f"配置缺少必需字段: {field}")
        
        # 验证 bot_token
        if self.data["bot_token"] == "YOUR_BOT_TOKEN_HERE":
            raise ValueError("请在配置文件中填写真实的 bot_token")
        
        # 验证转发规则
        if not self.data["forwarding_rules"]:
            raise ValueError("至少需要配置一条转发规则")
        
        for idx, rule in enumerate(self.data["forwarding_rules"]):
            if "source_chat_id" not in rule:
                raise ValueError(f"转发规则 {idx} 缺少 source_chat_id")
            if "target_chat_ids" not in rule:
                raise ValueError(f"转发规则 {idx} 缺少 target_chat_ids")
    
    @property
    def bot_token(self) -> str:
        """获取 Bot Token"""
        return self.data["bot_token"]
    
    @property
    def admin_user_id(self) -> int:
        """获取管理员用户 ID"""
        return self.data["admin_user_id"]
    
    @property
    def forwarding_rules(self) -> List[Dict[str, Any]]:
        """获取转发规则列表"""
        return self.data.get("forwarding_rules", [])
    
    @property
    def deduplication_enabled(self) -> bool:
        """是否启用去重"""
        return self.data.get("features", {}).get("deduplication", {}).get("enabled", True)
    
    @property
    def deduplication_expire_hours(self) -> int:
        """去重时效（小时）"""
        return self.data.get("features", {}).get("deduplication", {}).get("expire_hours", 24)
    
    @property
    def admin_notifications_enabled(self) -> bool:
        """是否启用管理员通知"""
        return self.data.get("features", {}).get("admin_notifications", {}).get("enabled", True)
    
    @property
    def notify_on_start(self) -> bool:
        """是否在启动时通知管理员"""
        return self.data.get("features", {}).get("admin_notifications", {}).get("notify_on_start", True)
    
    @property
    def notify_on_error(self) -> bool:
        """是否在出错时通知管理员"""
        return self.data.get("features", {}).get("admin_notifications", {}).get("notify_on_error", True)
    
    def get_targets_for_source(self, source_chat_id: int) -> List[Dict[str, Any]]:
        """
        根据源群组 ID 获取所有匹配的转发规则
        
        Args:
            source_chat_id: 源群组 ID
        
        Returns:
            匹配的转发规则列表
        """
        return [
            rule for rule in self.forwarding_rules
            if rule["source_chat_id"] == source_chat_id and rule.get("enabled", True)
        ]
    
    def reload(self):
        """重新加载配置文件"""
        logger.info("正在重新加载配置...")
        self.load()
        logger.info("✓ 配置已重新加载")
    
    def save(self):
        """保存配置到文件（原子写入，防止文件损坏）"""
        temp_path = f"{self.config_path}.tmp"
        try:
            # 先写入临时文件
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            
            # 原子替换（确保文件完整性）
            os.replace(temp_path, self.config_path)
            logger.info(f"✓ 配置已安全保存: {self.config_path}")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            # 清理临时文件
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            raise
    
    def add_rule(self, source_chat_id: int, target_chat_id: int, source_title: str = None, target_title: str = None):
        """
        添加或更新转发规则
        
        Args:
            source_chat_id: 源群组 ID
            target_chat_id: 目标群组 ID
            source_title: 源群组名称（可选）
            target_title: 目标群组名称（可选）
        """
        # 先从磁盘重新加载，防止覆盖手动编辑
        self.load()
        
        # 检查是否已存在该源群组的规则
        found = False
        for rule in self.data.setdefault("forwarding_rules", []):
            if rule["source_chat_id"] == source_chat_id:
                # 更新源群组标题
                if source_title:
                    rule["source_chat_title"] = source_title

                if target_chat_id not in rule["target_chat_ids"]:
                    rule["target_chat_ids"].append(target_chat_id)
                    logger.info(f"已将目标 {target_chat_id} 添加到源 {source_chat_id} 的规则中")
                else:
                    logger.info(f"目标 {target_chat_id} 已存在于源 {source_chat_id} 的规则中")
                
                # 更新目标群组标题
                if target_title:
                    if "target_chat_titles" not in rule:
                        rule["target_chat_titles"] = {}
                    rule["target_chat_titles"][str(target_chat_id)] = target_title
                
                found = True
                break
        
        if not found:
            # 创建新规则
            new_rule = {
                "source_chat_id": source_chat_id,
                "source_chat_title": source_title or str(source_chat_id),
                "target_chat_ids": [target_chat_id],
                "target_chat_titles": {str(target_chat_id): target_title} if target_title else {},
                "keywords_blacklist": [],
                "enabled": True
            }
            self.data["forwarding_rules"].append(new_rule)
            logger.info(f"已创建新规则: 源 {source_chat_id} -> 目标 {target_chat_id}")
        
        self.save()
    
    def remove_rule(self, source_chat_id: int) -> bool:
        """
        删除源群组的转发规则
        
        Args:
            source_chat_id: 源群组 ID
        
        Returns:
            是否成功删除
        """
        # 先从磁盘重新加载，防止覆盖手动编辑
        self.load()
        
        original_count = len(self.data.get("forwarding_rules", []))
        self.data["forwarding_rules"] = [
            rule for rule in self.data.get("forwarding_rules", [])
            if rule["source_chat_id"] != source_chat_id
        ]
        
        if len(self.data["forwarding_rules"]) < original_count:
            self.save()
            logger.info(f"已删除源 {source_chat_id} 的转发规则")
            return True
        
        logger.warning(f"未找到源 {source_chat_id} 的转发规则")
        return False
