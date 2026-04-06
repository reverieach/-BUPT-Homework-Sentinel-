# 北邮作业通知系统 (BUPT Homework Sentinel)

## 功能
- 拉取未完成作业列表
- 新作业提醒（去重）
- 截止日期提醒（默认在剩余 2/1/0 天各提醒一次）
- 401/403 自动抓头一次并重试一次
- 支持多通道通知：`console` / `desktop` / `markdown` / `wechat` / `pushplus` / `email` / `webhook`
- 支持 Windows 定时任务一键安装（每天固定时间运行）

## 目录说明
- `monitor.py`：统一入口（运行、抓头、安装/管理定时任务）
- `monitor_core.py`：核心逻辑（请求、去重、提醒、通知、状态存储）
- `capture_headers.py`：自动登录并抓取请求头
- `config.py`：`.env` 配置读取与校验

## 环境准备
1. 安装依赖
```bash
pip install -r requirements.txt
playwright install chromium
```
2. 配置.env文件
```bash
cp .env.example .env
```

## 核心配置说明

### 1) `USER_ID` 是什么
- 这是接口 `.../undone?userId=xxx` 的 `userId`（不是学号）
- 获取方式：浏览器 F12 -> Network -> 找 `undone` 请求 -> 复制 `userId`
- 建议留空：程序会尝试从 JWT 自动解析（优先 `.env` 的 `BLADE_AUTH`，其次 `valid_headers.json` 的 `blade-auth`）

### 2) `UCLOUD_HOME_URL` 如何填
- 需要你手动填自己的学生首页完整 URL
- 操作：登录 ucloud -> 打开自己的云平台作业页面 -> 复制地址栏完整 URL 到 `.env`

### 3) 统一通知接口（可自由组合）
- `NOTIFY_CHANNELS`：选择渠道，逗号分隔
  - 可选：`console,desktop,markdown,wechat,pushplus,email,webhook`
- `NOTIFY_EVENTS`：选择事件
  - 可选：`NEW,DUE`
- `REMINDER_DAYS`：`DUE` 触发阈值（在DDL前 `2,1,0`天发送通知）

#### 本地通知 + 本地 md 文件
```env
NOTIFY_CHANNELS=desktop,markdown
NOTIFY_EVENTS=NEW,DUE
MARKDOWN_OUTPUT_FILE=homework_reminders.md
MARKDOWN_APPEND=true
```
说明：
- `desktop`：Windows 右下角通知（托盘气泡）
- `markdown`：在当前运行目录输出/追加 `homework_reminders.md`

## QQ 邮箱 SMTP 配置
先在 QQ 邮箱网页开启 SMTP 并获取“授权码”（不是登录密码）。

`.env` 示例：
```env
NOTIFY_CHANNELS=console,email
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USE_SSL=true
SMTP_STARTTLS=false
SMTP_USERNAME=你的QQ邮箱@qq.com
SMTP_PASSWORD=QQ邮箱SMTP授权码
SMTP_FROM=你的QQ邮箱@qq.com
SMTP_TO=接收人1@qq.com,接收人2@qq.com
```

## 微信推送（更简单，不用企业微信群）
推荐 `pushplus`：微信扫码登录后拿 token 即可。

`.env` 示例：
```env
NOTIFY_CHANNELS=console,pushplus
PUSHPLUS_TOKEN=你的token
PUSHPLUS_TEMPLATE=txt
PUSHPLUS_TOPIC=
```

说明：
- 官网：`https://www.pushplus.plus`
- 只填 `PUSHPLUS_TOKEN` 就能单人微信接收
- `PUSHPLUS_TOPIC` 留空即可（用于群组场景时再配置）

## 企业微信机器人（需自己配置）
```env
NOTIFY_CHANNELS=console,wechat
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key
```

## 运行
- 抓请求头：
```bash
python monitor.py --capture-headers
```
- 运行一次监控：
```bash
python monitor.py
```
- 试跑（不写状态文件）：
```bash
python monitor.py --dry-run
```
- 测试桌面通知（排查右下角是否可显示）：
```bash
python monitor.py --test-desktop-notify
```

## 设置时间自动运行（Windows）
安装（默认无控制台窗口运行，使用 `pythonw`）：
```bash
python monitor.py --install-daily-task --task-time 19:00 --task-name HomeworkMonitorDaily
```

如需安装成“显示控制台”模式：
```bash
python monitor.py --install-daily-task --task-time 19:00 --task-name HomeworkMonitorDaily --task-show-console
```

### 关机/重启/休眠后是否继续运行
当前安装逻辑包含：
- `StartWhenAvailable`：如果 19:00 时机器关机，开机后会尽快补跑一次
- `WakeToRun`：机器休眠时，系统允许的情况下会被唤醒执行

注意：
- 彻底关机期间不会运行；只能在下次开机后补跑
- 休眠唤醒依赖主板与电源计划是否允许定时唤醒

### 定时任务管理与停止
查看任务：
```bash
python monitor.py --show-task --task-name HomeworkMonitorDaily
```
禁用任务（停止后续自动运行，保留任务）：
```bash
python monitor.py --disable-task --task-name HomeworkMonitorDaily
```
启用任务：
```bash
python monitor.py --enable-task --task-name HomeworkMonitorDaily
```
结束当前正在运行的一次任务：
```bash
python monitor.py --end-task --task-name HomeworkMonitorDaily
```
删除任务：
```bash
python monitor.py --remove-task --task-name HomeworkMonitorDaily
```

## 常见问题
- 401/403：token 过期，执行 `python monitor.py --capture-headers`
- 其他问题可以提在issue或者email：baozixuan@bupt.edu.cn
- 抓头失败：设置 `PLAYWRIGHT_HEADLESS=false` 观察页面流程
- 右下角通知没显示：
  1. 先运行 `python monitor.py --test-desktop-notify`
  2. 确认 `NOTIFY_CHANNELS` 包含 `desktop`
  3. 检查系统“专注助手/勿扰模式”是否屏蔽通知
