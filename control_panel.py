from __future__ import annotations

import io
import json
import traceback
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from flask import Flask, make_response, redirect, render_template_string, request, url_for

from capture_headers import capture_valid_headers
from config import load_settings
from monitor_core import AuthExpiredError, Notifier, fetch_course_map, run_monitor_once
from task_scheduler import (
    disable_windows_task,
    enable_windows_task,
    end_windows_task,
    install_windows_daily_task,
    query_windows_task_text,
    remove_windows_task,
    run_windows_task_now,
)


ENV_PATH = Path('.env')

CORE_KEYS = ['SCHOOL_ID', 'SCHOOL_PWD', 'UCLOUD_HOME_URL', 'USER_ID']
ONBOARDING_KEYS = ['SCHOOL_ID', 'SCHOOL_PWD', 'PLAYWRIGHT_HEADLESS']
CORE_REQUIRED_SETUP_KEYS = ['SCHOOL_ID', 'SCHOOL_PWD']

RUNTIME_KEYS = [
    'SCHOOL_LOGIN_URL',
    'PLAYWRIGHT_HEADLESS',
    'CAPTURE_WAIT_SECONDS',
    'API_BASE_URL',
    'API_UNDONE_ENDPOINT',
    'API_HOMEWORK_DETAIL_ENDPOINT',
    'PAGE_SIZE',
    'HEADER_FILE',
    'STATE_FILE',
    'REQUEST_TIMEOUT_SEC',
    'REQUEST_RETRIES',
    'REQUEST_RETRY_DELAY_SEC',
    'DISABLE_SYSTEM_PROXY',
    'AUTO_REFRESH_HEADERS_ON_401',
    'TERM_ID',
    'REMINDER_DAYS',
    'FETCH_HOMEWORK_CONTENT',
    'HOMEWORK_CONTENT_MAX_CHARS',
    'AUTHORIZATION',
    'BLADE_AUTH',
]

NOTIFY_KEYS = [
    'NOTIFY_CHANNELS',
    'NOTIFY_EVENTS',
    'NOTIFY_TITLE_PREFIX',
    'MARKDOWN_OUTPUT_FILE',
    'MARKDOWN_APPEND',
    'NOTIFY_WEBHOOK_URL',
    'WECHAT_WEBHOOK_URL',
    'PUSHPLUS_TOKEN',
    'PUSHPLUS_TOPIC',
    'PUSHPLUS_TEMPLATE',
    'SMTP_HOST',
    'SMTP_PORT',
    'SMTP_USE_SSL',
    'SMTP_STARTTLS',
    'SMTP_USERNAME',
    'SMTP_PASSWORD',
    'SMTP_FROM',
    'SMTP_TO',
]

TASK_PREF_KEYS = ['TASK_NAME', 'TASK_TIME', 'TASK_NO_CONSOLE']
EMAIL_DEFAULT_KEYS = {'SMTP_HOST', 'SMTP_PORT'}

QUICK_NOTIFY_KEYS = [
    'NOTIFY_CHANNELS',
    'NOTIFY_EVENTS',
    'REMINDER_DAYS',
    'NOTIFY_TITLE_PREFIX',
    'MARKDOWN_OUTPUT_FILE',
    'MARKDOWN_APPEND',
    'PUSHPLUS_TOKEN',
    'WECHAT_WEBHOOK_URL',
    'SMTP_HOST',
    'SMTP_PORT',
    'SMTP_USERNAME',
    'SMTP_PASSWORD',
    'SMTP_FROM',
    'SMTP_TO',
]

ORDERED_KEYS = CORE_KEYS + RUNTIME_KEYS + NOTIFY_KEYS
BOOL_KEYS = {
    'PLAYWRIGHT_HEADLESS',
    'DISABLE_SYSTEM_PROXY',
    'AUTO_REFRESH_HEADERS_ON_401',
    'FETCH_HOMEWORK_CONTENT',
    'MARKDOWN_APPEND',
    'SMTP_USE_SSL',
    'SMTP_STARTTLS',
    'TASK_NO_CONSOLE',
}
SENSITIVE_KEYS = {
    'SCHOOL_PWD',
    'AUTHORIZATION',
    'BLADE_AUTH',
    'PUSHPLUS_TOKEN',
    'SMTP_PASSWORD',
}

DEFAULTS = {
    'SCHOOL_ID': '',
    'SCHOOL_PWD': '',
    'UCLOUD_HOME_URL': '',
    'USER_ID': '',
    'SCHOOL_LOGIN_URL': 'https://auth.bupt.edu.cn/authserver/login?service=https://ucloud.bupt.edu.cn',
    'PLAYWRIGHT_HEADLESS': 'true',
    'CAPTURE_WAIT_SECONDS': '5',
    'API_BASE_URL': 'https://apiucloud.bupt.edu.cn',
    'API_UNDONE_ENDPOINT': '/ykt-site/site/student/undone',
    'API_HOMEWORK_DETAIL_ENDPOINT': '/ykt-site/work/detail',
    'PAGE_SIZE': '100',
    'HEADER_FILE': 'valid_headers.json',
    'STATE_FILE': 'homework_db.json',
    'REQUEST_TIMEOUT_SEC': '15',
    'REQUEST_RETRIES': '3',
    'REQUEST_RETRY_DELAY_SEC': '2',
    'DISABLE_SYSTEM_PROXY': 'false',
    'AUTO_REFRESH_HEADERS_ON_401': 'true',
    'TERM_ID': '',
    'REMINDER_DAYS': '2,1,0',
    'FETCH_HOMEWORK_CONTENT': 'true',
    'HOMEWORK_CONTENT_MAX_CHARS': '1200',
    'AUTHORIZATION': '',
    'BLADE_AUTH': '',
    'NOTIFY_CHANNELS': 'desktop,markdown',
    'NOTIFY_EVENTS': 'NEW,DUE',
    'NOTIFY_TITLE_PREFIX': '[Homework Monitor]',
    'MARKDOWN_OUTPUT_FILE': 'homework_reminders.md',
    'MARKDOWN_APPEND': 'true',
    'NOTIFY_WEBHOOK_URL': '',
    'WECHAT_WEBHOOK_URL': '',
    'PUSHPLUS_TOKEN': '',
    'PUSHPLUS_TOPIC': '',
    'PUSHPLUS_TEMPLATE': 'txt',
    'SMTP_HOST': 'smtp.qq.com',
    'SMTP_PORT': '465',
    'SMTP_USE_SSL': 'true',
    'SMTP_STARTTLS': 'false',
    'SMTP_USERNAME': '',
    'SMTP_PASSWORD': '',
    'SMTP_FROM': '',
    'SMTP_TO': '',
    'TASK_NAME': 'HomeworkMonitorDaily',
    'TASK_TIME': '19:00',
    'TASK_NO_CONSOLE': 'true',
}

FIELD_META = {
    'SCHOOL_ID': ('学号', '教务统一身份认证账号，通常就是学号。', '例如：2023xxxxxx'),
    'SCHOOL_PWD': ('密码', '教务统一身份认证密码，仅用于自动登录抓取请求头。', '输入登录密码'),
    'UCLOUD_HOME_URL': (
        '云平台首页 URL',
        '可留空。抓取请求头时会自动识别并写回带学生 roleId 的首页 URL。',
        '自动识别，或手动填 https://ucloud.bupt.edu.cn/uclass/#/student/homePage?roleId=...',
    ),
    'USER_ID': ('用户ID', '不是学号。可留空，系统会优先从 BLADE_AUTH / 已抓取请求头自动解析。', '可留空'),
    'SCHOOL_LOGIN_URL': ('登录地址', '默认即可，一般无需改动。', ''),
    'PLAYWRIGHT_HEADLESS': ('无头模式', 'true=后台无窗口；false=显示浏览器便于排查。', ''),
    'CAPTURE_WAIT_SECONDS': ('抓头等待秒数', '登录后等待 API 请求稳定发出所需时间。', '5'),
    'API_BASE_URL': ('API 根地址', '默认即可。', ''),
    'API_UNDONE_ENDPOINT': ('未完成作业接口路径', '默认即可。', ''),
    'API_HOMEWORK_DETAIL_ENDPOINT': ('作业详情接口路径', '用于抓取作业内容；若内容抓不到，可按实际网络请求修改。', '/ykt-site/work/detail'),
    'PAGE_SIZE': ('每次拉取数量', '接口一次拉取作业条目数。', '100'),
    'HEADER_FILE': ('请求头文件', '抓头结果保存路径。', 'valid_headers.json'),
    'STATE_FILE': ('状态文件', '作业去重与提醒状态保存路径。', 'homework_db.json'),
    'REQUEST_TIMEOUT_SEC': ('请求超时(秒)', '网络请求超时时间。', '15'),
    'REQUEST_RETRIES': ('请求重试次数', '请求失败时自动重试次数。', '3'),
    'REQUEST_RETRY_DELAY_SEC': ('重试间隔(秒)', '每次重试的间隔。', '2'),
    'DISABLE_SYSTEM_PROXY': ('禁用系统代理', '若代理导致请求失败，改为 true。', ''),
    'AUTO_REFRESH_HEADERS_ON_401': ('401自动抓头', '接口401/403时是否自动抓头并重试。', ''),
    'TERM_ID': ('学期ID', '用于只拉取本学期课程。可从 ucloud 课程页面的网络请求中获取 termId 参数；留空则自动检测当前学期。', ''),
    'REMINDER_DAYS': ('截止提醒天数', '逗号分隔，如 2,1,0 表示截止前2/1/当天提醒。', '2,1,0'),
    'FETCH_HOMEWORK_CONTENT': ('抓取作业内容', 'true=尝试从列表和详情接口提取作业内容。', ''),
    'HOMEWORK_CONTENT_MAX_CHARS': ('作业内容长度', '保存和推送的作业内容最大字符数，0 表示不截断。', '1200'),
    'AUTHORIZATION': ('Authorization', '可选：手动粘贴鉴权头。建议留空让系统自动抓。', ''),
    'BLADE_AUTH': ('Blade-Auth', '可选：手动粘贴鉴权 token。', ''),
    'NOTIFY_CHANNELS': (
        '通知渠道',
        '逗号分隔：console,desktop,markdown,wechat,pushplus,email,webhook',
        'desktop,markdown',
    ),
    'NOTIFY_EVENTS': ('通知事件', '逗号分隔：NEW,DUE。NEW=新作业，DUE=临近截止。', 'NEW,DUE'),
    'NOTIFY_TITLE_PREFIX': ('通知标题前缀', '每条提醒前附加的标题前缀。', '[Homework Monitor]'),
    'MARKDOWN_OUTPUT_FILE': ('Markdown输出文件', '启用 markdown 渠道时写入的文件名/路径。', 'homework_reminders.md'),
    'MARKDOWN_APPEND': ('Markdown追加模式', 'true=追加历史，false=每次覆盖。', ''),
    'NOTIFY_WEBHOOK_URL': ('通用Webhook', '任意支持 JSON POST 的 webhook 地址。', ''),
    'WECHAT_WEBHOOK_URL': ('企业微信机器人', '企业微信群机器人 webhook 地址。', ''),
    'PUSHPLUS_TOKEN': ('PushPlus Token', '更简单微信推送方案，去 pushplus.plus 获取 token。', ''),
    'PUSHPLUS_TOPIC': ('PushPlus Topic', '群组推送可选，不需要可留空。', ''),
    'PUSHPLUS_TEMPLATE': ('PushPlus 模板', '一般保持 txt。', 'txt'),
    'SMTP_HOST': ('Email SMTP主机', '默认已填 QQ 邮箱的 smtp.qq.com；其他邮箱请按 README 的“常见问题”修改对应 SMTP 地址。', 'smtp.qq.com'),
    'SMTP_PORT': ('Email SMTP端口', '默认已填 QQ 邮箱 SSL 端口 465；其他邮箱请按 README 的“常见问题”修改。', '465'),
    'SMTP_USE_SSL': ('SMTP 使用SSL', 'QQ 邮箱通常为 true；具体配置可查看 README 的“常见问题”。', ''),
    'SMTP_STARTTLS': ('SMTP STARTTLS', '使用 SSL 时一般为 false；具体配置可查看 README 的“常见问题”。', ''),
    'SMTP_USERNAME': ('SMTP 用户名', '填写你的邮箱地址；QQ 邮箱配置方法见 README 的“常见问题”。', 'your@qq.com'),
    'SMTP_PASSWORD': ('SMTP 授权码', 'QQ 邮箱这里填授权码而不是登录密码；具体说明见 README 的“常见问题”。', ''),
    'SMTP_FROM': ('发件人', '通常与 SMTP 用户名相同；详细配置见 README 的“常见问题”。', 'your@qq.com'),
    'SMTP_TO': ('收件人', '接收通知的邮箱，多个用英文逗号分隔；详细配置见 README 的“常见问题”。', 'a@qq.com,b@xx.com'),
    'TASK_NAME': ('任务名称', 'Windows 任务计划中的任务名。', 'HomeworkMonitorDaily'),
    'TASK_TIME': ('执行时间', '每天执行时间，24小时制 HH:MM。', '19:00'),
    'TASK_NO_CONSOLE': ('静默模式', 'true=完全静默不弹窗（推荐）。', ''),
}


TEMPLATE = r"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>BUPT Homework Sentinel</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    :root {
      --bg: #f0f4f8;
      --card: #ffffff;
      --text: #1a2332;
      --sub: #5a6b80;
      --muted: #8896a7;
      --line: #e2e8f0;
      --brand: #2563eb;
      --brand-light: #dbeafe;
      --green: #16a34a;
      --green-light: #dcfce7;
      --amber: #d97706;
      --amber-light: #fef3c7;
      --red: #dc2626;
      --red-light: #fee2e2;
      --shadow-sm: 0 1px 3px rgba(0,0,0,0.06);
      --shadow: 0 4px 16px rgba(0,0,0,0.08);
      --shadow-lg: 0 12px 32px rgba(0,0,0,0.12);
      --radius: 12px;
      --radius-sm: 8px;
    }
    * { box-sizing: border-box; margin: 0; }
    body {
      color: var(--text);
      font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      min-height: 100vh;
      line-height: 1.5;
    }

    /* ---- Header ---- */
    .header {
      background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 50%, #16a34a 100%);
      color: #fff;
      padding: 28px 0 20px;
      margin-bottom: 24px;
    }
    .header-inner {
      max-width: 1180px; margin: 0 auto; padding: 0 20px;
      display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;
    }
    .header h1 { font-size: 22px; font-weight: 700; letter-spacing: 0.3px; }
    .header h1 span { opacity: 0.7; font-weight: 400; font-size: 14px; margin-left: 8px; }
    .header-badges { display: flex; gap: 8px; flex-wrap: wrap; }
    .badge {
      display: inline-flex; align-items: center; gap: 5px;
      background: rgba(255,255,255,0.15); backdrop-filter: blur(4px);
      border: 1px solid rgba(255,255,255,0.25);
      padding: 4px 12px; border-radius: 20px;
      font-size: 12px; font-weight: 500;
    }
    .badge .dot {
      width: 7px; height: 7px; border-radius: 50%;
      display: inline-block;
    }
    .dot-green { background: #4ade80; box-shadow: 0 0 6px #4ade80; }
    .dot-amber { background: #fbbf24; box-shadow: 0 0 6px #fbbf24; }
    .dot-red { background: #f87171; box-shadow: 0 0 6px #f87171; }

    /* ---- Layout ---- */
    .wrap { max-width: 1180px; margin: 0 auto; padding: 0 20px 48px; }

    .status-bar {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px; margin-bottom: 20px;
    }
    .stat-card {
      background: var(--card); border: 1px solid var(--line); border-radius: var(--radius-sm);
      padding: 14px 16px; box-shadow: var(--shadow-sm);
      display: flex; align-items: center; gap: 12px;
    }
    .stat-icon {
      width: 40px; height: 40px; border-radius: 10px;
      display: flex; align-items: center; justify-content: center;
      font-size: 18px; flex-shrink: 0;
    }
    .stat-icon.blue { background: var(--brand-light); color: var(--brand); }
    .stat-icon.green { background: var(--green-light); color: var(--green); }
    .stat-icon.amber { background: var(--amber-light); color: var(--amber); }
    .stat-label { font-size: 12px; color: var(--muted); }
    .stat-value { font-size: 15px; font-weight: 600; }

    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 20px;
      box-shadow: var(--shadow-sm);
      transition: box-shadow 0.2s;
    }
    .card:hover { box-shadow: var(--shadow); }
    .card h2 {
      font-size: 16px; font-weight: 700; margin-bottom: 4px;
      display: flex; align-items: center; gap: 8px;
    }
    .card h2 .icon { font-size: 18px; }
    .card-desc { color: var(--sub); font-size: 13px; margin-bottom: 14px; }

    /* ---- Setup wizard ---- */
    .wizard {
      background: linear-gradient(135deg, #eff6ff, #f0fdf4);
      border: 1px solid #bfdbfe;
      border-radius: var(--radius);
      padding: 20px;
      margin-bottom: 16px;
    }
    .wizard h2 { font-size: 16px; font-weight: 700; margin-bottom: 8px; }
    .steps { display: grid; gap: 6px; }
    .step {
      font-size: 13px; color: var(--sub);
      display: flex; align-items: center; gap: 8px;
    }
    .step-badge {
      font-size: 11px; font-weight: 700; padding: 2px 8px;
      border-radius: 4px; flex-shrink: 0;
    }
    .step-done { background: var(--green-light); color: var(--green); }
    .step-todo { background: var(--amber-light); color: var(--amber); }

    /* ---- Form fields ---- */
    .field-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 14px; }
    .field { display: flex; flex-direction: column; gap: 4px; }
    .label-row { display: flex; align-items: center; gap: 6px; }
    label { font-size: 13px; font-weight: 600; color: var(--text); }
    .help-btn {
      width: 18px; height: 18px; border-radius: 50%;
      border: 1px solid var(--line); background: #f8fafc; color: var(--sub);
      font-size: 11px; line-height: 16px; cursor: pointer; padding: 0;
      transition: all 0.15s;
    }
    .help-btn:hover { background: var(--brand-light); color: var(--brand); border-color: var(--brand); }
    .help-box {
      display: none;
      border-left: 3px solid var(--brand);
      background: #f8fafc;
      color: var(--sub);
      padding: 6px 10px;
      border-radius: 0 6px 6px 0;
      font-size: 12px;
      line-height: 1.5;
    }
    .help-box.show { display: block; }

    input, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      padding: 8px 12px;
      font-size: 13px;
      background: #fff;
      color: var(--text);
      transition: border-color 0.15s, box-shadow 0.15s;
    }
    input:focus, select:focus {
      outline: none;
      border-color: var(--brand);
      box-shadow: 0 0 0 3px rgba(37,99,235,0.12);
    }

    /* ---- Buttons ---- */
    .btns { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .btn-group-label {
      width: 100%; font-size: 11px; font-weight: 600;
      color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px;
      margin-top: 6px; margin-bottom: -2px;
    }
    button, .btn {
      border: 0; border-radius: var(--radius-sm); padding: 8px 16px;
      color: #fff; cursor: pointer; font-weight: 600; font-size: 13px;
      display: inline-flex; align-items: center; gap: 6px;
      transition: opacity 0.15s, transform 0.1s;
    }
    button:hover { opacity: 0.9; }
    button:active { transform: scale(0.97); }
    .btn-primary { background: var(--brand); }
    .btn-green { background: var(--green); }
    .btn-gray { background: #64748b; }
    .btn-amber { background: var(--amber); }
    .btn-red { background: var(--red); }

    /* ---- Advanced section ---- */
    details.advanced { margin-top: 16px; }
    details.advanced > summary {
      cursor: pointer; list-style: none;
      font-weight: 700; color: var(--text);
      padding: 12px 16px;
      display: flex; align-items: center; gap: 8px;
    }
    details.advanced > summary::-webkit-details-marker { display: none; }
    details.advanced > summary::before {
      content: '\25B6'; font-size: 10px;
      transition: transform 0.2s;
    }
    details.advanced[open] > summary::before {
      transform: rotate(90deg);
    }

    /* ---- Log output ---- */
    .log-wrap { margin-top: 16px; }
    .log-header {
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 8px;
    }
    .log-header h2 { margin: 0; }
    .copy-btn {
      background: #334155; color: #94a3b8; border: 1px solid #475569;
      border-radius: 6px; padding: 4px 10px; font-size: 11px;
      cursor: pointer; transition: all 0.15s;
    }
    .copy-btn:hover { color: #e2e8f0; background: #475569; }
    .log {
      min-height: 100px; max-height: 400px; overflow-y: auto;
      white-space: pre-wrap; word-break: break-word;
      background: #0f172a;
      color: #cbd5e1;
      border-radius: var(--radius);
      padding: 14px 16px;
      font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
      font-size: 12.5px;
      line-height: 1.6;
      border: 1px solid #1e293b;
    }

    /* ---- Toast ---- */
    .toast-container {
      position: fixed; top: 20px; right: 20px; z-index: 9999;
      display: flex; flex-direction: column; gap: 8px;
    }
    .toast {
      padding: 12px 20px; border-radius: var(--radius-sm);
      color: #fff; font-size: 13px; font-weight: 500;
      box-shadow: var(--shadow-lg);
      animation: toastIn 0.3s ease, toastOut 0.3s ease 3.5s forwards;
      max-width: 360px;
    }
    .toast-ok { background: var(--green); }
    .toast-warn { background: var(--amber); }
    .toast-err { background: var(--red); }
    .toast-info { background: var(--brand); }
    @keyframes toastIn { from { opacity:0; transform: translateX(40px); } to { opacity:1; transform: translateX(0); } }
    @keyframes toastOut { from { opacity:1; } to { opacity:0; transform: translateY(-10px); } }

    /* ---- Confirm dialog ---- */
    .overlay {
      display: none; position: fixed; inset: 0; z-index: 10000;
      background: rgba(0,0,0,0.4); backdrop-filter: blur(2px);
      align-items: center; justify-content: center;
    }
    .overlay.show { display: flex; }
    .dialog {
      background: #fff; border-radius: var(--radius); padding: 24px;
      box-shadow: var(--shadow-lg); max-width: 380px; width: 90%;
      text-align: center;
    }
    .dialog h3 { margin-bottom: 8px; font-size: 16px; }
    .dialog p { color: var(--sub); font-size: 13px; margin-bottom: 18px; }
    .dialog-btns { display: flex; gap: 10px; justify-content: center; }
    .dialog-btns button { min-width: 80px; justify-content: center; }

    /* ---- Section title ---- */
    .section-title {
      font-size: 14px; color: var(--sub); font-weight: 700;
      margin: 16px 0 10px; padding-bottom: 6px;
      border-bottom: 1px solid var(--line);
    }
    .full { grid-column: 1 / -1; }

    /* ---- Footer ---- */
    .footer {
      margin-top: 32px; padding-top: 16px;
      border-top: 1px solid var(--line);
      text-align: center; color: var(--muted); font-size: 12px;
    }

    /* ---- Responsive ---- */
    @media (max-width: 860px) {
      .grid-2 { grid-template-columns: 1fr; }
      .field-grid { grid-template-columns: 1fr; }
      .header-inner { flex-direction: column; align-items: flex-start; }
    }
  </style>
</head>
<body>
<div class="toast-container" id="toasts"></div>

<div class="overlay" id="confirmOverlay">
  <div class="dialog">
    <h3 id="confirmTitle">确认操作</h3>
    <p id="confirmMsg">确定要执行此操作吗？</p>
    <div class="dialog-btns">
      <button class="btn-gray" onclick="closeConfirm()">取消</button>
      <button class="btn-red" id="confirmOk">确定</button>
    </div>
  </div>
</div>

<div class="header">
  <div class="header-inner">
    <h1>BUPT Homework Sentinel <span>控制台</span></h1>
    <div class="header-badges">
      <span class="badge">
        <span class="dot {% if first_run %}dot-amber{% else %}dot-green{% endif %}"></span>
        {% if first_run %}首次安装{% else %}运行中{% endif %}
      </span>
      <span class="badge">{{ task_name }} @ {{ task_time }}</span>
    </div>
  </div>
</div>

<div class="wrap">

  <!-- Status bar -->
  <div class="status-bar">
    <div class="stat-card">
      <div class="stat-icon blue">&#128218;</div>
      <div>
        <div class="stat-label">已追踪作业</div>
        <div class="stat-value">{{ hw_count }} 项</div>
      </div>
    </div>
    <div class="stat-card">
      <div class="stat-icon green">&#128273;</div>
      <div>
        <div class="stat-label">请求头状态</div>
        <div class="stat-value">{{ header_status }}</div>
      </div>
    </div>
    <div class="stat-card">
      <div class="stat-icon amber">&#128340;</div>
      <div>
        <div class="stat-label">上次检查</div>
        <div class="stat-value">{{ last_check or '从未运行' }}</div>
      </div>
    </div>
  </div>

  {% if first_run %}
  <div class="wizard">
    <h2>首次安装向导</h2>
    <p class="card-desc">请按顺序完成以下步骤，确保首次运行成功。</p>
    <div class="steps">
      {% for s in setup_statuses %}
      <div class="step">
        <span class="step-badge {% if s.done %}step-done{% else %}step-todo{% endif %}">
          {% if s.done %}OK{% else %}TODO{% endif %}
        </span>
        {{ s.label }}
      </div>
      {% endfor %}
    </div>
  </div>

  <form class="card" method="post" action="/save_env" style="margin-bottom: 16px;">
    <input type="hidden" name="scope" value="onboarding" />
    <h2><span class="icon">&#9881;</span> 关键配置（首次必填）</h2>
    <p class="card-desc">先填写学号和密码；带学生 roleId 的云平台首页 URL 会在抓取请求头时自动识别。</p>
    <div class="field-grid">
      {% for f in onboarding_fields %}
      <div class="field {% if f.full %}full{% endif %}">
        <div class="label-row">
          <label for="{{f.dom_id}}">{{f.label}}</label>
          <button type="button" class="help-btn" data-help="help-{{f.dom_id}}">?</button>
        </div>
        <div class="help-box" id="help-{{f.dom_id}}">{{f.help}}</div>
        {% if f.is_bool %}
        <select id="{{f.dom_id}}" name="{{f.key}}">
          <option value="true" {% if f.value.lower()=='true' %}selected{% endif %}>true</option>
          <option value="false" {% if f.value.lower()=='false' %}selected{% endif %}>false</option>
        </select>
        {% else %}
        <input id="{{f.dom_id}}" name="{{f.key}}" value="{{f.value}}" placeholder="{{f.placeholder}}" type="{{f.input_type}}" />
        {% endif %}
      </div>
      {% endfor %}
    </div>
    <div class="btns">
      <button class="btn-green" type="submit">保存关键配置</button>
    </div>
  </form>
  {% endif %}

  <div class="grid-2">
    <!-- Notify settings -->
    <form class="card" method="post" action="/save_env">
      <input type="hidden" name="scope" value="quick_notify" />
      <h2><span class="icon">&#128276;</span> 通知设置</h2>
      <p class="card-desc">渠道、事件、提醒天数、推送参数等日常最常调整的项目。</p>
      <div class="field-grid">
        {% for f in quick_notify_fields %}
        <div class="field {% if f.full %}full{% endif %}">
          <div class="label-row">
            <label for="{{f.dom_id}}">{{f.label}}</label>
            <button type="button" class="help-btn" data-help="help-{{f.dom_id}}">?</button>
          </div>
          <div class="help-box" id="help-{{f.dom_id}}">{{f.help}}</div>
          {% if f.is_bool %}
          <select id="{{f.dom_id}}" name="{{f.key}}">
            <option value="true" {% if f.value.lower()=='true' %}selected{% endif %}>true</option>
            <option value="false" {% if f.value.lower()=='false' %}selected{% endif %}>false</option>
          </select>
          {% else %}
          <input id="{{f.dom_id}}" name="{{f.key}}" value="{{f.value}}" placeholder="{{f.placeholder}}" type="{{f.input_type}}" />
          {% endif %}
        </div>
        {% endfor %}
      </div>
      <div class="btns">
        <button type="submit" class="btn-green">保存通知设置</button>
      </div>
    </form>

    <!-- Task scheduler -->
    <form class="card" method="post" action="/actions">
      <h2><span class="icon">&#9200;</span> 定时任务</h2>
      <p class="card-desc">建议开启静默模式，避免每天运行时弹出命令行窗口。</p>
      <div class="field-grid">
        {% for f in task_fields %}
        <div class="field {% if f.full %}full{% endif %}">
          <div class="label-row">
            <label for="{{f.dom_id}}">{{f.label}}</label>
            <button type="button" class="help-btn" data-help="help-{{f.dom_id}}">?</button>
          </div>
          <div class="help-box" id="help-{{f.dom_id}}">{{f.help}}</div>
          {% if f.is_bool %}
          <select id="{{f.dom_id}}" name="{{f.key}}">
            <option value="true" {% if f.value.lower()=='true' %}selected{% endif %}>true</option>
            <option value="false" {% if f.value.lower()=='false' %}selected{% endif %}>false</option>
          </select>
          {% else %}
          <input id="{{f.dom_id}}" name="{{f.key}}" value="{{f.value}}" placeholder="{{f.placeholder}}" {% if f.key=='TASK_TIME' %}type="time"{% else %}type="{{f.input_type}}"{% endif %} />
          {% endif %}
        </div>
        {% endfor %}
      </div>
      <div class="btns">
        <button name="action" value="save_task_pref" class="btn-green">保存偏好</button>
        <button name="action" value="install_task" class="btn-primary">安装/更新任务</button>
        <button name="action" value="run_task_now" class="btn-gray">立即触发</button>
      </div>
      <div class="btns">
        <span class="btn-group-label">管理</span>
        <button name="action" value="show_task" class="btn-gray">查看详情</button>
        <button name="action" value="enable_task" class="btn-gray">启用</button>
        <button name="action" value="disable_task" class="btn-amber" onclick="return confirmAction(event, '禁用任务', '确定禁用定时任务？禁用后将不会自动运行。')">禁用</button>
        <button name="action" value="end_task" class="btn-amber">终止运行</button>
        <button name="action" value="remove_task" class="btn-red" onclick="return confirmAction(event, '删除任务', '确定删除定时任务？删除后需要重新安装。')">删除</button>
      </div>
    </form>
  </div>

  <!-- Quick actions -->
  <form class="card" method="post" action="/actions" style="margin-top: 16px;">
    <h2><span class="icon">&#9889;</span> 快捷操作</h2>
    <p class="card-desc">手动抓取请求头、运行检查或测试通知。</p>
    <div class="btns">
      <button name="action" value="capture_headers" class="btn-primary">抓取请求头</button>
      <button name="action" value="run_now" class="btn-green">立即运行一次</button>
      <button name="action" value="dry_run" class="btn-gray">试跑（dry-run）</button>
      <button name="action" value="test_desktop" class="btn-gray">测试桌面通知</button>
      <button name="action" value="refresh_course_map" class="btn-primary">刷新课程映射</button>
    </div>
  </form>

  <!-- Advanced settings -->
  <details class="card advanced" {% if first_run %}open{% endif %}>
    <summary>高级设置 / 个人信息（点击展开）</summary>
    <form method="post" action="/save_env">
      <input type="hidden" name="scope" value="advanced" />
      <div class="section-title">账号与系统配置</div>
      <div class="field-grid">
        {% for f in advanced_fields %}
        <div class="field {% if f.full %}full{% endif %}">
          <div class="label-row">
            <label for="{{f.dom_id}}">{{f.label}}</label>
            <button type="button" class="help-btn" data-help="help-{{f.dom_id}}">?</button>
          </div>
          <div class="help-box" id="help-{{f.dom_id}}">{{f.help}}</div>
          {% if f.is_bool %}
          <select id="{{f.dom_id}}" name="{{f.key}}">
            <option value="true" {% if f.value.lower()=='true' %}selected{% endif %}>true</option>
            <option value="false" {% if f.value.lower()=='false' %}selected{% endif %}>false</option>
          </select>
          {% else %}
          <input id="{{f.dom_id}}" name="{{f.key}}" value="{{f.value}}" placeholder="{{f.placeholder}}" type="{{f.input_type}}" />
          {% endif %}
        </div>
        {% endfor %}
      </div>
      <div class="btns">
        <button type="submit" class="btn-green">保存高级设置</button>
      </div>
    </form>
  </details>

  <!-- Log output -->
  <div class="log-wrap">
    <div class="log-header">
      <h2><span class="icon">&#128187;</span> 执行输出</h2>
      <button class="copy-btn" onclick="copyLog()" type="button">复制</button>
    </div>
    <div class="log" id="logBox">{{ message or '暂无输出。执行操作后结果会显示在这里。' }}</div>
  </div>

  <div class="footer">
    BUPT Homework Sentinel &middot; Python {{ py_version }}
  </div>
</div>

<script>
(function(){
  /* Help toggles */
  document.querySelectorAll('.help-btn').forEach(function(btn){
    btn.addEventListener('click', function(e){
      e.preventDefault();
      var box = document.getElementById(btn.getAttribute('data-help'));
      if(box) box.classList.toggle('show');
    });
  });

  /* Toast from cookie */
  var m = document.cookie.match(/(?:^|;\s*)flash_msg=([^;]*)/);
  if(m){
    var raw = decodeURIComponent(m[1]);
    document.cookie = 'flash_msg=; path=/; max-age=0';
    if(raw) showToast(raw);
  }

  /* Auto-scroll log */
  var log = document.getElementById('logBox');
  if(log) log.scrollTop = log.scrollHeight;

  /* Syntax highlight log */
  if(log && log.textContent.trim() !== '暂无输出。执行操作后结果会显示在这里。'){
    var html = log.innerHTML;
    html = html.replace(/\[ok\]/gi, '<span style="color:#4ade80;font-weight:700">[ok]</span>');
    html = html.replace(/\[warn\]/gi, '<span style="color:#fbbf24;font-weight:700">[warn]</span>');
    html = html.replace(/\[error\]/gi, '<span style="color:#f87171;font-weight:700">[error]</span>');
    html = html.replace(/\[captured\]/gi, '<span style="color:#38bdf8;font-weight:700">[captured]</span>');
    html = html.replace(/\[step\]/gi, '<span style="color:#a78bfa;font-weight:700">[step]</span>');
    html = html.replace(/\[config\]/gi, '<span style="color:#94a3b8;font-weight:700">[config]</span>');
    log.innerHTML = html;
  }
})();

function copyLog(){
  var log = document.getElementById('logBox');
  if(!log) return;
  navigator.clipboard.writeText(log.textContent).then(function(){
    showToast('[ok] 已复制到剪贴板');
  });
}

function showToast(text){
  var c = document.getElementById('toasts');
  var t = document.createElement('div');
  var cls = 'toast-info';
  if(text.indexOf('[ok]') >= 0) cls = 'toast-ok';
  else if(text.indexOf('[warn]') >= 0) cls = 'toast-warn';
  else if(text.indexOf('[error]') >= 0) cls = 'toast-err';
  t.className = 'toast ' + cls;
  t.textContent = text;
  c.appendChild(t);
  setTimeout(function(){ t.remove(); }, 4000);
}

/* Confirm dialog for dangerous actions */
var pendingForm = null;
var pendingBtn = null;

function confirmAction(e, title, msg){
  e.preventDefault();
  pendingForm = e.target.closest('form');
  pendingBtn = e.target;
  document.getElementById('confirmTitle').textContent = title;
  document.getElementById('confirmMsg').textContent = msg;
  document.getElementById('confirmOverlay').classList.add('show');
  return false;
}

function closeConfirm(){
  document.getElementById('confirmOverlay').classList.remove('show');
  pendingForm = null;
  pendingBtn = null;
}

document.getElementById('confirmOk').addEventListener('click', function(){
  if(pendingForm && pendingBtn){
    var input = document.createElement('input');
    input.type = 'hidden';
    input.name = pendingBtn.name;
    input.value = pendingBtn.value;
    pendingForm.appendChild(input);
    pendingForm.submit();
  }
  closeConfirm();
});
</script>
</body>
</html>
"""


def _load_env_values() -> dict[str, str]:
    values = dict(DEFAULTS)
    if not ENV_PATH.exists():
        return values
    text = ENV_PATH.read_text(encoding='utf-8')
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if key:
            values[key] = value.strip()

    for key in EMAIL_DEFAULT_KEYS:
        if not values.get(key, '').strip():
            values[key] = DEFAULTS[key]
    return values


def _write_env_values(values: dict[str, str]) -> None:
    lines: list[str] = []
    lines.append('# 北邮作业通知系统 (BUPT Homework Sentinel)')
    lines.append('# 控制台会维护此文件')
    lines.append('')

    lines.append('# ==========================')
    lines.append('# 必填核心配置（先填这里）')
    lines.append('# ==========================')
    for key in CORE_KEYS:
        lines.append(f'{key}={values.get(key, "")}')
    lines.append('')

    lines.append('# ==========================')
    lines.append('# 推荐基础配置（一般保持默认）')
    lines.append('# ==========================')
    for key in RUNTIME_KEYS:
        lines.append(f'{key}={values.get(key, "")}')
    lines.append('')

    lines.append('# ==========================')
    lines.append('# 可选通知功能')
    lines.append('# ==========================')
    for key in NOTIFY_KEYS:
        lines.append(f'{key}={values.get(key, "")}')
    lines.append('')

    lines.append('# ==========================')
    lines.append('# 控制台偏好（可选）')
    lines.append('# ==========================')
    for key in TASK_PREF_KEYS:
        lines.append(f'{key}={values.get(key, DEFAULTS.get(key, ""))}')
    lines.append('')

    ENV_PATH.write_text('\n'.join(lines), encoding='utf-8')


def _run_with_capture(fn: Callable[[], object]) -> str:
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            result = fn()
        output = buffer.getvalue().strip()
        if isinstance(result, str) and result:
            return (output + '\n' + result).strip()
        return output or '[ok]'
    except Exception:
        output = buffer.getvalue().strip()
        trace = traceback.format_exc()
        return (output + '\n' + trace).strip()


def _run_monitor_with_auto_refresh(dry_run: bool) -> None:
    settings = load_settings()
    try:
        run_monitor_once(dry_run=dry_run)
    except AuthExpiredError:
        if not settings.auto_refresh_headers_on_401:
            raise
        print('[warn] auth expired, refreshing headers once...')
        capture_valid_headers()
        run_monitor_once(dry_run=dry_run)


def _is_first_run(values: dict[str, str]) -> bool:
    return any(not values.get(k, '').strip() for k in CORE_REQUIRED_SETUP_KEYS)


def _mask(text: str) -> str:
    if not text:
        return '(未填写)'
    if len(text) <= 4:
        return '*' * len(text)
    return text[:2] + '*' * (len(text) - 4) + text[-2:]


def _resolve_path(path_text: str) -> Path:
    p = Path(path_text)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


def _field_meta(key: str) -> tuple[str, str, str]:
    if key in FIELD_META:
        return FIELD_META[key]
    return key, '该配置项暂无说明。', ''


def _build_fields(values: dict[str, str], keys: list[str], prefix: str) -> list[dict[str, str | bool]]:
    out: list[dict[str, str | bool]] = []
    for key in keys:
        label, help_text, placeholder = _field_meta(key)
        out.append(
            {
                'key': key,
                'dom_id': f'{prefix}_{key}',
                'label': label,
                'help': help_text,
                'placeholder': placeholder,
                'value': values.get(key, ''),
                'is_bool': key in BOOL_KEYS,
                'input_type': 'password' if key in SENSITIVE_KEYS else 'text',
                'full': key in {'UCLOUD_HOME_URL', 'NOTIFY_CHANNELS', 'SMTP_TO', 'NOTIFY_WEBHOOK_URL', 'WECHAT_WEBHOOK_URL'},
            }
        )
    return out


def _setup_statuses(values: dict[str, str]) -> list[dict[str, str | bool]]:
    header_file = _resolve_path(values.get('HEADER_FILE', DEFAULTS['HEADER_FILE']))
    return [
        {'label': '填写学号（SCHOOL_ID）', 'done': bool(values.get('SCHOOL_ID', '').strip())},
        {'label': '填写密码（SCHOOL_PWD）', 'done': bool(values.get('SCHOOL_PWD', '').strip())},
        {'label': '学生首页URL自动识别（UCLOUD_HOME_URL 可留空）', 'done': True},
        {'label': '已抓取请求头（valid_headers.json）', 'done': header_file.exists()},
    ]


def _get_status_info(values: dict[str, str]) -> dict[str, str | int]:
    """Gather live status info for the dashboard."""
    info: dict[str, str | int] = {'hw_count': 0, 'header_status': '未找到', 'last_check': ''}

    state_file = _resolve_path(values.get('STATE_FILE', DEFAULTS['STATE_FILE']))
    if state_file.exists():
        try:
            raw = json.loads(state_file.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                known = raw.get('known_assignments', {})
                info['hw_count'] = len(known) if isinstance(known, dict) else 0
                last = raw.get('last_check', '')
                if last:
                    dt = datetime.fromisoformat(str(last))
                    info['last_check'] = dt.strftime('%m-%d %H:%M')
        except Exception:
            pass

    header_file = _resolve_path(values.get('HEADER_FILE', DEFAULTS['HEADER_FILE']))
    if header_file.exists():
        try:
            mtime = datetime.fromtimestamp(header_file.stat().st_mtime)
            info['header_status'] = f'有效 ({mtime.strftime("%m-%d %H:%M")})'
        except Exception:
            info['header_status'] = '有效'
    else:
        info['header_status'] = '未抓取'

    return info


def _apply_form_values(values: dict[str, str], keys: list[str]) -> dict[str, str]:
    for key in keys:
        if key in request.form:
            value = request.form.get(key, '').strip()
            if key in EMAIL_DEFAULT_KEYS and not value:
                value = DEFAULTS[key]
            values[key] = value
    return values


def _set_flash(response, message: str):
    """Set a flash message cookie for the next request."""
    import urllib.parse
    response.set_cookie('flash_msg', urllib.parse.quote(message), max_age=10, path='/')
    return response


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get('/')
    def index():
        values = _load_env_values()
        first_run = _is_first_run(values)
        status_info = _get_status_info(values)
        import sys
        return render_template_string(
            TEMPLATE,
            values=values,
            first_run=first_run,
            setup_statuses=_setup_statuses(values),
            onboarding_fields=_build_fields(values, ONBOARDING_KEYS, 'onb'),
            quick_notify_fields=_build_fields(values, QUICK_NOTIFY_KEYS, 'quick'),
            task_fields=_build_fields(values, TASK_PREF_KEYS, 'task'),
            advanced_fields=_build_fields(values, CORE_KEYS + RUNTIME_KEYS + NOTIFY_KEYS, 'adv'),
            task_name=values.get('TASK_NAME', DEFAULTS['TASK_NAME']),
            task_time=values.get('TASK_TIME', DEFAULTS['TASK_TIME']),
            message=request.args.get('message', ''),
            hw_count=status_info['hw_count'],
            header_status=status_info['header_status'],
            last_check=status_info['last_check'],
            py_version=f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}',
        )

    @app.post('/save_env')
    def save_env():
        values = _load_env_values()
        scope = request.form.get('scope', 'advanced').strip()

        if scope == 'onboarding':
            keys = ONBOARDING_KEYS
        elif scope == 'quick_notify':
            keys = QUICK_NOTIFY_KEYS
        elif scope == 'task':
            keys = TASK_PREF_KEYS
        else:
            keys = CORE_KEYS + RUNTIME_KEYS + NOTIFY_KEYS

        values = _apply_form_values(values, keys)
        _write_env_values(values)
        resp = make_response(redirect(url_for('index', message='[ok] 配置已保存')))
        _set_flash(resp, '[ok] 配置已保存')
        return resp

    @app.post('/actions')
    def actions():
        values = _load_env_values()
        action = request.form.get('action', '').strip()

        values = _apply_form_values(values, TASK_PREF_KEYS)
        _write_env_values(values)

        task_name = values.get('TASK_NAME', DEFAULTS['TASK_NAME']).strip() or DEFAULTS['TASK_NAME']
        task_time = values.get('TASK_TIME', DEFAULTS['TASK_TIME']).strip() or DEFAULTS['TASK_TIME']
        no_console = values.get('TASK_NO_CONSOLE', DEFAULTS['TASK_NO_CONSOLE']).lower() == 'true'

        def do_action() -> object:
            if action == 'capture_headers':
                return capture_valid_headers()
            if action == 'run_now':
                _run_monitor_with_auto_refresh(dry_run=False)
                return '[ok] monitor run completed.'
            if action == 'dry_run':
                _run_monitor_with_auto_refresh(dry_run=True)
                return '[ok] dry run completed.'
            if action == 'test_desktop':
                settings = load_settings()
                Notifier(settings)._send_desktop(settings.notify_title_prefix, 'Desktop notification test message.')
                return '[ok] desktop test notification triggered.'
            if action == 'refresh_course_map':
                settings = load_settings()
                if settings.course_map_file.exists():
                    settings.course_map_file.unlink()
                try:
                    mapping = fetch_course_map(settings)
                except AuthExpiredError:
                    if not settings.auto_refresh_headers_on_401:
                        raise
                    print('[warn] auth expired, refreshing headers...')
                    capture_valid_headers()
                    mapping = fetch_course_map(settings)
                return f'[ok] course map refreshed: {len(mapping)} entries'
            if action == 'save_task_pref':
                return '[ok] task preference saved.'
            if action == 'install_task':
                return install_windows_daily_task(task_name, task_time, no_console=no_console)
            if action == 'run_task_now':
                return run_windows_task_now(task_name)
            if action == 'show_task':
                return query_windows_task_text(task_name)
            if action == 'enable_task':
                return enable_windows_task(task_name)
            if action == 'disable_task':
                return disable_windows_task(task_name)
            if action == 'end_task':
                return end_windows_task(task_name)
            if action == 'remove_task':
                return remove_windows_task(task_name)
            return f'[warn] unknown action: {action}'

        message = _run_with_capture(do_action)
        resp = make_response(redirect(url_for('index', message=message)))
        _set_flash(resp, message[:120])
        return resp

    return app


def run_control_panel(host: str = '127.0.0.1', port: int = 5000) -> None:
    app = create_app()
    app.run(host=host, port=port, debug=False)
