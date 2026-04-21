# BUPT Homework Sentinel

北邮作业哨兵 —— 自动监控 ucloud 未完成作业，截止日期提醒，多渠道通知推送。

## 功能

- 自动拉取未完成作业列表，新作业去重提醒
- 截止日期提醒（默认剩余 2 / 1 / 0 天各提醒一次）
- 自动抓取作业内容（如详情接口可用，会一并写入通知与 Markdown 记录）
- 自动关联课程名（通过扫描选课列表匹配，支持自动检测当前学期）
- 401/403 自动重新抓取请求头并重试
- 多渠道通知：`console` / `desktop` / `markdown` / `wechat` / `pushplus` / `email` / `webhook`
- Windows 定时任务（完全静默，不弹窗）
- Web 控制台：首次安装向导 + 日常面板 + 高级设置

## 快速开始

> **注意**：建议将项目放在**纯英文路径**下（如 `D:\Projects\HomeworkSentinel`）。中文路径可能导致 Windows 定时任务的 VBS 启动器出现编码问题。

### 1. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 创建配置文件

```bash
cp .env.example .env
```

### 3. 启动控制台

```bash
python monitor.py --web
```

浏览器访问 `http://127.0.0.1:5000`，按页面引导完成配置。

### 4. 首次配置流程

1. 填写**学号**、**密码**
2. 点击「保存关键配置」
3. 点击「抓取请求头」（系统会自动登录、自动识别带学生 `roleId` 的首页 URL，并捕获鉴权信息）
4. 点击「试跑（dry-run）」验证是否正常
5. 设置定时任务时间，点击「安装/更新任务」

> 如有需要，也可以在高级设置里手动填写 `UCLOUD_HOME_URL`；但大多数情况下无需手动粘贴。

### 5. 日常使用

配置完成后，定时任务每天自动运行，无需手动操作。如需调整通知渠道或查看状态，打开控制台即可。

## 项目结构

| 文件 | 说明 |
|------|------|
| `monitor.py` | CLI 入口（运行、抓头、定时任务、启动控制台） |
| `control_panel.py` | Web 控制台（Flask） |
| `monitor_core.py` | 核心逻辑（API 请求、去重、提醒、通知、课程映射） |
| `capture_headers.py` | 自动登录并抓取请求头（Playwright） |
| `task_scheduler.py` | Windows 定时任务管理 |
| `config.py` | 配置读取（`.env`） |

## CLI 用法

```bash
# 运行一次检查
python monitor.py

# 试跑（不写入状态）
python monitor.py --dry-run

# 抓取请求头
python monitor.py --capture-headers

# 启动 Web 控制台
python monitor.py --web
python monitor.py --web --web-port 5050

# 定时任务管理
python monitor.py --install-daily-task --task-time 19:00
python monitor.py --show-task
python monitor.py --remove-task

# 测试桌面通知
python monitor.py --test-desktop-notify

```

## 定时任务（静默运行）

定时任务通过 `wscript.exe` + `pythonw.exe` 链式启动，全链路无窗口弹出：

```
Windows Task Scheduler → wscript.exe → .vbs → pythonw.exe → monitor.py
```

在控制台中勾选「静默模式」（默认开启），点击「安装/更新任务」即可。

## 通知渠道

在 `.env` 或控制台中配置 `NOTIFY_CHANNELS`（逗号分隔）：

| 渠道 | 说明 |
|------|------|
| `console` | 终端输出 |
| `desktop` | Windows 右下角气泡通知 |
| `markdown` | 写入本地 Markdown 文件 |
| `pushplus` | 微信推送（[pushplus.plus](https://www.pushplus.plus) 获取 token） |
| `wechat` | 企业微信群机器人 Webhook |
| `email` | SMTP 邮件（支持 QQ 邮箱等） |
| `webhook` | 任意 JSON POST Webhook |

### 通知内容说明

- `desktop`：只显示摘要，避免气泡通知过长
- `console` / `markdown` / `wechat` / `pushplus` / `email` / `webhook`：会附带抓取到的作业内容
- 若作业详情接口没有返回正文，则仍会正常提醒标题、课程和截止时间

## 课程名关联

系统会自动扫描你的选课列表，将作业与对应课程匹配。

- **自动检测学期**：无需配置，系统会自动识别当前学期
- **手动指定**：如需指定，在 `.env` 中设置 `TERM_ID`（可从 ucloud 课程页面 F12 网络请求中获取）
- **缓存**：课程映射缓存 1 天，每天首次运行时自动刷新；也可在控制台点击「刷新课程映射」手动刷新

## 常见问题

**Q: 提示 401/403 怎么办？**
点击「抓取请求头」重新获取鉴权信息。如已开启 `AUTO_REFRESH_HEADERS_ON_401=true`（默认），系统会自动处理。

**Q: 桌面通知不显示？**
检查 Windows 专注助手/勿扰模式是否关闭。可在控制台点击「测试桌面通知」验证。

**Q: 代理导致请求失败？**
设置 `DISABLE_SYSTEM_PROXY=true`。

**Q: 为什么通知里没有作业内容？**
先确认 `FETCH_HOMEWORK_CONTENT=true`。如果仍无内容，检查 `API_HOMEWORK_DETAIL_ENDPOINT` 是否与浏览器网络请求一致；当前北邮云平台常见值为 `/ykt-site/work/detail`。

**Q: 如何配置 QQ 邮箱通知？**

1. 登录 [QQ 邮箱网页版](https://mail.qq.com)
2. 进入**设置** → **账户** → 找到「POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV 服务」
3. 开启 **IMAP/SMTP 服务**，按提示用手机发短信验证
4. 验证通过后会生成一个 **16 位授权码**（不是 QQ 密码！），复制保存
5. 在 `.env` 或控制台中填写：
   ```
   NOTIFY_CHANNELS=email          # 加上 email
   SMTP_HOST=smtp.qq.com
   SMTP_PORT=465
   SMTP_USE_SSL=true
   SMTP_USERNAME=你的QQ号@qq.com
   SMTP_PASSWORD=上面获取的16位授权码
   SMTP_FROM=你的QQ号@qq.com
   SMTP_TO=你想接收提醒的收件邮箱@xx.com（可与发件邮箱相同）
   ```

> 控制台中 `SMTP_HOST` 和 `SMTP_PORT` 默认已填好 QQ 邮箱的 `smtp.qq.com` 和 `465`，通常无需手动填写。

> **注意**：`SMTP_PASSWORD` 填的是**授权码**而非 QQ 登录密码。授权码只显示一次，如果丢失需要重新生成。

**Q: 其他都正常，但是邮箱收不到提醒怎么办？**

1. 确定所有关于邮箱的信息都已准确无误填入，特别检查**授权码**和 `SMTP_HOST` 是否正确填写  
   （我舍友就是没填 `SMTP_HOST`，让我查了一晚上 bug）
2. 确定在 `NOTIFY_CHANNELS` 中已经加入了 `email`，并且用 `,` 正确分隔

**Q: 如何使用微信推送？**

微信可以直接关注“QQ邮箱提醒”，这样配置好邮件提醒后就可以在微信收到提醒，推荐这种方式。

如使用 PushPlus，需要前往 [pushplus.plus](https://www.pushplus.plus) 获取 token，可能会有相关费用，具体请查看网站说明。

觉得有用的话可以点个 star 支持一下！好的建议或者问题也欢迎提到 issue 里！

## License

MIT
