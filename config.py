from __future__ import annotations

import os
import base64
import json
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"Environment variable {name} must be an integer, got: {raw!r}")


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


def _get_str(name: str, default: str = "") -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    text = raw.strip()
    return text if text else default


def _get_int_list(name: str, default: str) -> tuple[int, ...]:
    raw = os.getenv(name, default).strip()
    if not raw:
        return ()

    values: list[int] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            values.append(int(token))
        except ValueError:
            raise ValueError(f"Environment variable {name} must be a comma-separated int list, got: {raw!r}")
    return tuple(sorted(set(values), reverse=True))


def _get_str_list(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default).strip()
    if not raw:
        return ()

    values: list[str] = []
    for part in raw.split(","):
        token = part.strip()
        if token:
            values.append(token)
    return tuple(dict.fromkeys(values))


def _get_path(name: str, default: str) -> Path:
    raw = os.getenv(name, default).strip()
    p = Path(raw)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    undone_endpoint: str
    user_id: str
    page_size: int
    request_timeout_sec: int
    request_retries: int
    request_retry_delay_sec: int
    disable_system_proxy: bool
    auto_refresh_headers_on_401: bool
    header_file: Path
    state_file: Path
    reminder_days: tuple[int, ...]
    enable_console_notify: bool
    notify_channels: tuple[str, ...]
    notify_events: tuple[str, ...]
    notify_title_prefix: str
    notify_webhook_url: str
    wechat_webhook_url: str
    pushplus_token: str
    pushplus_topic: str
    pushplus_template: str
    markdown_output_file: Path
    markdown_append: bool
    smtp_host: str
    smtp_port: int
    smtp_use_ssl: bool
    smtp_starttls: bool
    smtp_username: str
    smtp_password: str
    smtp_from: str
    smtp_to: tuple[str, ...]
    playwright_headless: bool
    capture_wait_seconds: int
    login_url: str
    home_url: str
    school_id: str
    school_pwd: str
    authorization: str
    blade_auth: str
    course_list_endpoint: str
    course_work_endpoint: str
    homework_detail_endpoint: str
    course_map_file: Path
    term_id: str
    fetch_homework_content: bool
    homework_content_max_chars: int

    @property
    def undone_url(self) -> str:
        return f"{self.api_base_url.rstrip('/')}/{self.undone_endpoint.lstrip('/')}"


def load_settings() -> Settings:
    load_dotenv(override=True)
    blade_auth = os.getenv("BLADE_AUTH", "").strip()
    user_id = os.getenv("USER_ID", "").strip()
    if not user_id and blade_auth:
        user_id = _infer_user_id_from_jwt(blade_auth)

    reminder_days = _get_int_list("REMINDER_DAYS", "2,1,0")
    if not reminder_days:
        reminder_days = (2,)

    notify_channels = _get_str_list("NOTIFY_CHANNELS", "")
    if not notify_channels:
        # Backward compatibility for old config:
        # if ENABLE_CONSOLE_NOTIFY=true, keep console notifications enabled by default.
        if _get_bool("ENABLE_CONSOLE_NOTIFY", True):
            notify_channels = ("console",)
        else:
            notify_channels = ()

    return Settings(
        api_base_url=_get_str("API_BASE_URL", "https://apiucloud.bupt.edu.cn"),
        undone_endpoint=_get_str("API_UNDONE_ENDPOINT", "/ykt-site/site/student/undone"),
        user_id=user_id,
        page_size=_get_int("PAGE_SIZE", 100),
        request_timeout_sec=_get_int("REQUEST_TIMEOUT_SEC", 15),
        request_retries=max(1, _get_int("REQUEST_RETRIES", 3)),
        request_retry_delay_sec=max(0, _get_int("REQUEST_RETRY_DELAY_SEC", 2)),
        disable_system_proxy=_get_bool("DISABLE_SYSTEM_PROXY", False),
        auto_refresh_headers_on_401=_get_bool("AUTO_REFRESH_HEADERS_ON_401", True),
        header_file=_get_path("HEADER_FILE", "valid_headers.json"),
        state_file=_get_path("STATE_FILE", "homework_db.json"),
        reminder_days=reminder_days,
        enable_console_notify=_get_bool("ENABLE_CONSOLE_NOTIFY", True),
        notify_channels=tuple(ch.lower() for ch in notify_channels),
        notify_events=tuple(e.upper() for e in _get_str_list("NOTIFY_EVENTS", "NEW,DUE")),
        notify_title_prefix=os.getenv("NOTIFY_TITLE_PREFIX", "[Homework Monitor]").strip(),
        notify_webhook_url=os.getenv("NOTIFY_WEBHOOK_URL", "").strip(),
        wechat_webhook_url=os.getenv("WECHAT_WEBHOOK_URL", "").strip(),
        pushplus_token=os.getenv("PUSHPLUS_TOKEN", "").strip(),
        pushplus_topic=os.getenv("PUSHPLUS_TOPIC", "").strip(),
        pushplus_template=os.getenv("PUSHPLUS_TEMPLATE", "txt").strip(),
        markdown_output_file=_get_path("MARKDOWN_OUTPUT_FILE", "homework_reminders.md"),
        markdown_append=_get_bool("MARKDOWN_APPEND", True),
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=_get_int("SMTP_PORT", 465),
        smtp_use_ssl=_get_bool("SMTP_USE_SSL", True),
        smtp_starttls=_get_bool("SMTP_STARTTLS", False),
        smtp_username=os.getenv("SMTP_USERNAME", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", "").strip(),
        smtp_from=os.getenv("SMTP_FROM", "").strip(),
        smtp_to=_get_str_list("SMTP_TO", ""),
        playwright_headless=_get_bool("PLAYWRIGHT_HEADLESS", True),
        capture_wait_seconds=max(1, _get_int("CAPTURE_WAIT_SECONDS", 5)),
        login_url=_get_str(
            "SCHOOL_LOGIN_URL",
            "https://auth.bupt.edu.cn/authserver/login?service=https://ucloud.bupt.edu.cn",
        ),
        home_url=_get_str(
            "UCLOUD_HOME_URL",
            "https://ucloud.bupt.edu.cn/uclass/#/student/homePage?roleId=1318863781576577025",
        ),
        school_id=os.getenv("SCHOOL_ID", "").strip(),
        school_pwd=os.getenv("SCHOOL_PWD", "").strip(),
        authorization=os.getenv("AUTHORIZATION", "").strip(),
        blade_auth=blade_auth,
        course_list_endpoint=_get_str(
            "API_COURSE_LIST_ENDPOINT",
            "/ykt-site/site/list/student/history",
        ),
        course_work_endpoint=_get_str(
            "API_COURSE_WORK_ENDPOINT",
            "/ykt-site/work/student/list",
        ),
        homework_detail_endpoint=_get_str(
            "API_HOMEWORK_DETAIL_ENDPOINT",
            "/ykt-site/work/detail",
        ),
        course_map_file=_get_path("COURSE_MAP_FILE", "course_map.json"),
        term_id=os.getenv("TERM_ID", "").strip(),
        fetch_homework_content=_get_bool("FETCH_HOMEWORK_CONTENT", True),
        homework_content_max_chars=max(0, _get_int("HOMEWORK_CONTENT_MAX_CHARS", 1200)),
    )


def _infer_user_id_from_jwt(token: str) -> str:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return ""
        payload = parts[1]
        padding = "=" * ((4 - len(payload) % 4) % 4)
        decoded = base64.urlsafe_b64decode(payload + padding).decode("utf-8")
        obj = json.loads(decoded)
        for key in ("user_id", "userId"):
            if key in obj and str(obj[key]).strip():
                return str(obj[key]).strip()
        return ""
    except Exception:
        return ""
