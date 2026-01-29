# Telegram 视频转发机器人

自动将源群组的视频转发到目标群组，支持无痕复制（不显示来源标签），源消息删除后目标消息依然保留。

## 功能特点

- **无痕转发**: 使用 `copyMessage` API，目标群不显示"转发自XXX"标签
- **独立消息**: 转发后的消息与源消息完全独立，源消息删除不影响目标消息
- **自动重试**: 智能处理 Telegram 限流，自动等待后重试
- **后台运行**: 使用 systemd 守护进程，开机自启，崩溃自动重启
- **资源占用极低**: 仅消耗几 KB 流量，不下载视频到服务器

## 前置准备

### 1. 获取 Bot Token
1. 在 Telegram 搜索 `@BotFather`
2. 发送 `/newbot` 创建机器人
3. 按提示设置名称和用户名
4. 复制获得的 Token (格式: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. 获取群组 Chat ID
方法一（推荐）: 使用 @userinfobot
1. 将 `@userinfobot` 拉入群组
2. 发送任意消息，机器人会回复群组 ID（格式: `-1001234567890`）

方法二: 使用 API
1. 将机器人拉入群组并发一条消息
2. 访问: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
3. 在返回 JSON 中找到 `chat` -> `id`

### 3. 设置机器人为管理员
**重要**: 必须在两个群组都将机器人设为管理员，否则无法转发消息。

需要的权限:
- 源群组: `读取消息` 权限
- 目标群组: `发送消息`、`发送视频` 权限

---

## Debian 服务器部署步骤

### 第一步: 上传文件到服务器

```bash
# 1. 在服务器上创建目录
mkdir -p /root/tgbotpass
cd /root/tgbotpass

# 2. 使用 scp 上传文件（在本地电脑执行）
scp bot.py requirements.txt .env.example video_bot.service root@YOUR_SERVER_IP:/root/tgbotpass/
```

或者使用 FTP 工具（如 WinSCP）上传这些文件。

### 第二步: 安装依赖

```bash
# SSH 登录到服务器后执行
cd /root/tgbotpass

# 安装 Python3 和 pip（如果尚未安装）
apt update
apt install python3 python3-pip python3-venv -y

# 创建虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip3 install -r requirements.txt
```

### 第三步: 配置机器人

```bash
# 复制配置模板
cp .env.example .env

# 编辑配置文件
nano .env
```

填写以下内容（删除 `your_` 前缀，填入实际值）:
```env
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
SOURCE_CHAT_ID=-1001234567890
TARGET_CHAT_ID=-1009876543210
```

按 `Ctrl+O` 保存，`Ctrl+X` 退出。

### 第四步: 测试运行

```bash
# 手动启动测试（查看是否有错误）
python3 bot.py
```

如果看到以下输出，说明启动成功:
```
✓ 配置验证通过
✓ 源群组: -1001234567890
✓ 目标群组: -1009876543210
============================================================
🤖 Telegram 视频转发机器人已启动
============================================================
等待新视频...
```

按 `Ctrl+C` 停止，准备配置为系统服务。

### 第五步: 配置 systemd 服务

```bash
# 1. 编辑服务文件，修改路径（如果使用虚拟环境）
nano video_bot.service
```

如果使用了虚拟环境，将这一行:
```
ExecStart=/usr/bin/python3 /root/tgbotpass/bot.py
```
改为:
```
ExecStart=/root/tgbotpass/venv/bin/python3 /root/tgbotpass/bot.py
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

### 第六步: 管理服务

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

---

## 常见问题

### Q1: 机器人不转发消息
**检查清单**:
1. 机器人是否在两个群组都是管理员？
2. `.env` 文件中的 Chat ID 是否正确（包括负号）？
3. 查看日志: `journalctl -u video_bot -n 100`

### Q2: 提示 "Unauthorized" 错误
- Bot Token 错误，重新从 @BotFather 获取

### Q3: 提示 "Chat not found" 错误
- Chat ID 错误，确保：
  - ID 前面有负号（群组 ID 通常是 `-100` 开头）
  - 机器人已被添加到该群组

### Q4: 转发速度很慢
- 这是 Telegram 限流，属于正常现象
- 机器人会自动等待并重试
- 不会漏发消息

### Q5: 如何只转发特定用户的视频？
编辑 `bot.py:119` 行，在过滤器中添加用户筛选:
```python
user_filter = filters.User(username="@specific_user")
application.add_handler(
    MessageHandler(source_filter & video_filter & user_filter, forward_video)
)
```

### Q6: 如何同时转发图片？
修改 `bot.py:119` 行:
```python
media_filter = filters.VIDEO | filters.VideoNote.ALL | filters.PHOTO
```

---

## 安全注意事项

1. **保护 .env 文件**: 不要将 `.env` 文件上传到公开的 Git 仓库
2. **定期检查日志**: `journalctl -u video_bot --since "1 hour ago"`
3. **遵守 Telegram 条款**: 不要转发版权内容或非法内容
4. **备份配置**: 定期备份 `.env` 文件

---

## 技术支持

如遇到问题:
1. 查看日志文件: `cat /root/tgbotpass/bot.log`
2. 查看系统日志: `journalctl -u video_bot -n 100`
3. 检查服务状态: `systemctl status video_bot`

---

## 文件说明

```
tgbotpass/
├── bot.py                # 核心程序
├── requirements.txt      # Python 依赖
├── .env.example         # 配置模板
├── .env                 # 实际配置（需手动创建）
├── video_bot.service    # systemd 服务文件
├── bot.log              # 运行日志（自动生成）
└── README.md            # 本文档
```

---

## 许可

本项目仅供学习交流使用，使用者需遵守 Telegram 服务条款。
