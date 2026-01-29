# Telegram 视频转发机器人 (企业级版本)

自动将源群组的视频转发到目标群组，支持无痕复制（不显示来源标签），源消息删除后目标消息依然保留。

## 核心特性

### 基础功能
- **纯净转发**: 使用 `copyMessage` API，绝对不添加任何标签或水印
- **独立消息**: 转发后的消息与源消息完全独立，源消息删除不影响目标消息
- **自动重试**: 智能处理 Telegram 限流，自动等待后重试
- **后台运行**: 使用 systemd 守护进程，开机自启，崩溃自动重启

### 高级功能
- **多对多转发**: 支持复杂的转发规则（群A → 群B+群C，群D → 群E）
- **智能去重**: 基于 SQLite 数据库，自动识别重复视频并跳过
- **关键词过滤**: 黑名单/白名单机制，自动拦截包含敏感词的视频
- **管理员通知**: 机器人启动、错误时自动私聊通知管理员
- **指令控制**: 支持 `/stats` (查看统计)、`/reload` (热重载配置)
- **资源占用极低**: 仅消耗几 KB 流量，不下载视频到服务器

---

## 前置准备

### 1. 获取 Bot Token
1. 在 Telegram 搜索 `@BotFather`
2. 发送 `/newbot` 创建机器人
3. 按提示设置名称和用户名
4. 复制获得的 Token (格式: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. 获取群组 Chat ID
**方法一（推荐）**: 使用 @userinfobot
1. 将 `@userinfobot` 拉入群组
2. 发送任意消息，机器人会回复群组 ID（格式: `-1001234567890`）

**方法二**: 使用 API
1. 将机器人拉入群组并发一条消息
2. 访问: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
3. 在返回 JSON 中找到 `chat` -> `id`

### 3. 获取管理员用户 ID
向 `@userinfobot` 私聊发送任意消息，它会回复您的用户 ID（纯数字，例如: `123456789`）

### 4. 设置机器人为管理员
**重要**: 必须在两个群组都将机器人设为管理员，否则无法转发消息。

需要的权限:
- 源群组: `读取消息` 权限
- 目标群组: `发送消息`、`发送视频` 权限

---

## Debian 服务器部署步骤

### 方式一: Git Clone 部署（推荐）

#### 第一步: 克隆仓库到服务器

```bash
# SSH 登录到服务器后执行

# 1. 安装 Git（如果尚未安装）
apt update
apt install git -y

# 2. 克隆仓库
cd /root
git clone https://github.com/YOUR_USERNAME/telegram-video-bot.git tgbotpass
cd tgbotpass
```

**注意**: 请将 `YOUR_USERNAME/telegram-video-bot` 替换为您的实际 GitHub 仓库地址。

#### 第二步: 安装依赖

```bash
# 安装 Python3 和 pip（如果尚未安装）
apt install python3 python3-pip python3-venv -y

# 创建虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip3 install -r requirements.txt
```

#### 第三步: 配置机器人

```bash
# 复制配置模板
cp config/config.example.json config/config.json

# 编辑配置文件
nano config/config.json
```

**配置文件说明**:

```json
{
  "bot_token": "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
  "admin_user_id": 123456789,
  "forwarding_rules": [
    {
      "source_chat_id": -1001234567890,
      "target_chat_ids": [-1009876543210],
      "keywords_blacklist": [],
      "enabled": true
    }
  ],
  "features": {
    "deduplication": {
      "enabled": true,
      "expire_hours": 24
    },
    "admin_notifications": {
      "enabled": true,
      "notify_on_start": true,
      "notify_on_error": true
    }
  }
}
```

**字段说明**:
- `bot_token`: 您的机器人 Token
- `admin_user_id`: 管理员的用户 ID（接收通知）
- `forwarding_rules`: 转发规则数组，可配置多条
  - `source_chat_id`: 源群组 ID
  - `target_chat_ids`: 目标群组 ID 列表（支持一对多）
  - `keywords_blacklist`: 黑名单关键词（包含则不转发）
  - `keywords_whitelist`: 白名单关键词（如果配置了白名单，则必须包含才转发）
  - `enabled`: 是否启用此规则
- `deduplication`: 去重配置
  - `enabled`: 是否启用智能去重
  - `expire_hours`: 去重时效（小时）
- `admin_notifications`: 管理员通知配置

按 `Ctrl+O` 保存，`Ctrl+X` 退出。

#### 第四步: 测试运行

```bash
# 手动启动测试（查看是否有错误）
python3 src/main.py
```

如果看到以下输出，说明启动成功:
```
✓ 配置加载成功: config/config.json
✓ 已加载 1 条转发规则
✓ 数据库初始化完成
============================================================
🤖 Telegram 视频转发机器人已启动
============================================================
```

按 `Ctrl+C` 停止，准备配置为系统服务。

#### 第五步: 配置 systemd 服务

```bash
# 1. 如果使用虚拟环境，需要编辑服务文件
nano video_bot.service
```

将这一行:
```
ExecStart=/usr/bin/python3 /root/tgbotpass/src/main.py
```
改为:
```
ExecStart=/root/tgbotpass/venv/bin/python3 /root/tgbotpass/src/main.py
```

```bash
# 2. 复制服务文件到系统目录
cp video_bot.service /etc/systemd/system/

# 3. 重新加载 systemd 配置
systemctl daemon-reload

# 4. 启动服务
systemctl start video_bot

# 5. 设置开机自启
systemctl enable video_bot

# 6. 查看运行状态
systemctl status video_bot
```

#### 第六步: 管理服务

```bash
# 查看实时日志
journalctl -u video_bot -f

# 重启服务
systemctl restart video_bot

# 停止服务
systemctl stop video_bot

# 查看详细日志（最近 50 行）
journalctl -u video_bot -n 50
```

#### 后续更新代码

当 GitHub 仓库有更新时，只需在服务器执行：

```bash
cd /root/tgbotpass
git pull
systemctl restart video_bot
```

---

### 方式二: SCP/FTP 上传部署（传统方式）

如果您不想使用 Git 或没有 GitHub 账号，可以使用传统的文件上传方式。

#### 第一步: 上传文件到服务器

```bash
# 1. 在服务器上创建目录
mkdir -p /root/tgbotpass
cd /root/tgbotpass

# 2. 使用 scp 上传整个项目（在本地电脑执行）
scp -r src/ config/ requirements.txt video_bot.service root@YOUR_SERVER_IP:/root/tgbotpass/
```

或者使用 FTP 工具（如 WinSCP）上传这些文件。

#### 第二步至第六步

与"方式一"的第二步至第六步完全相同，请参考上方步骤。

---

## 管理员指令

发送私聊消息给机器人（仅管理员可用）：

- `/stats` - 查看转发统计（总转发数、今日转发数）
- `/reload` - 热重载配置文件（无需重启服务）

---

## 常见问题

### Q1: 机器人不转发消息
**检查清单**:
1. 机器人是否在两个群组都是管理员？
2. `config/config.json` 中的 Chat ID 是否正确（包括负号）？
3. 转发规则的 `enabled` 是否为 `true`？
4. 查看日志: `journalctl -u video_bot -n 100`

### Q2: 提示 "Unauthorized" 错误
- Bot Token 错误，重新从 @BotFather 获取

### Q3: 提示 "Chat not found" 错误
- Chat ID 错误，确保：
  - ID 前面有负号（群组 ID 通常是 `-100` 开头）
  - 机器人已被添加到该群组

### Q4: 如何配置一对多转发？
编辑 `config/config.json`:
```json
{
  "source_chat_id": -1001111111111,
  "target_chat_ids": [-1002222222222, -1003333333333, -1004444444444],
  ...
}
```

### Q5: 如何配置多对多转发？
编辑 `config/config.json`，添加多条规则:
```json
"forwarding_rules": [
  {
    "source_chat_id": -1001111111111,
    "target_chat_ids": [-1002222222222],
    ...
  },
  {
    "source_chat_id": -1003333333333,
    "target_chat_ids": [-1004444444444, -1005555555555],
    ...
  }
]
```

### Q6: 去重是如何工作的？
机器人会记录每个视频的唯一标识符 (`file_unique_id`)，如果在设定时间内（默认 24 小时）检测到相同的视频，会自动跳过不转发。

即使源群有人重复发送视频，或者您重启了机器人，都不会导致重复转发。

### Q7: 如何关闭去重功能？
编辑 `config/config.json`，将 `deduplication.enabled` 设为 `false`:
```json
"features": {
  "deduplication": {
    "enabled": false
  }
}
```

然后发送 `/reload` 指令给机器人，或重启服务。

### Q8: 关键词过滤如何使用？
**黑名单模式**（可选）:
```json
"keywords_blacklist": ["关键词1", "关键词2"]
```
任何包含这些词的视频都不会被转发。

**白名单模式**（可选）:
```json
"keywords_whitelist": ["精选", "推荐"]
```
如果配置了白名单，只有包含白名单关键词的视频才会被转发。

**注意**: 
- 默认情况下两个列表都为空，机器人会转发所有视频
- 黑名单和白名单可以同时使用，必须同时满足两个条件才会转发

---

## 项目结构

```
tgbotpass/
├── src/
│   ├── __init__.py          # Python 包初始化
│   ├── main.py              # 程序入口
│   ├── config.py            # 配置加载器
│   ├── database.py          # SQLite 数据库（去重）
│   └── handlers.py          # 核心转发逻辑
├── config/
│   ├── config.example.json  # 配置模板
│   └── config.json          # 实际配置（需手动创建）
├── data/
│   └── bot.db               # SQLite 数据库（自动生成）
├── requirements.txt         # Python 依赖
├── video_bot.service        # systemd 服务文件
├── bot.log                  # 运行日志（自动生成）
├── bot.py.backup            # 旧版本备份
└── README.md                # 本文档
```

---

## 技术支持

如遇到问题:
1. 查看日志文件: `cat bot.log`
2. 查看系统日志: `journalctl -u video_bot -n 100`
3. 检查服务状态: `systemctl status video_bot`
4. 检查配置文件: `cat config/config.json`

---

## 版本历史

### v2.0.0 (企业级重构)
- 重构为模块化架构
- 新增多对多转发支持
- 新增智能去重功能（SQLite）
- 新增关键词过滤（黑名单/白名单）
- 新增管理员通知
- 新增 Telegram 指令控制
- 优化错误处理和日志记录

### v1.0.0 (基础版本)
- 基本的一对一视频转发
- 使用 .env 配置
- 单文件架构

---

## 许可

本项目仅供学习交流使用，使用者需遵守 Telegram 服务条款。
