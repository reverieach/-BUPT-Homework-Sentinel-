from __future__ import annotations

import json
import math
import time
import base64
import smtplib
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import requests

from config import Settings, load_settings


class AuthExpiredError(RuntimeError):
    pass


def _now_local() -> datetime:
    return datetime.now().astimezone()


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None

        if text.isdigit():
            return _parse_datetime(int(text))

        iso_guess = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(iso_guess)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_now_local().tzinfo)
            return parsed.astimezone()
        except ValueError:
            pass

        patterns = (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d",
            "%Y/%m/%d",
        )
        for pattern in patterns:
            try:
                parsed = datetime.strptime(text, pattern)
                return parsed.replace(tzinfo=_now_local().tzinfo)
            except ValueError:
                continue

    return None


def _extract_deadline(item: dict[str, Any]) -> datetime | None:
    keys = (
        "deadline",
        "endTime",
        "activityEndTime",
        "activityDeadline",
        "dueDate",
        "expireTime",
    )
    for key in keys:
        if key in item:
            parsed = _parse_datetime(item.get(key))
            if parsed:
                return parsed
    return None


def _pick_str(item: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _format_deadline(dt: datetime | None) -> str:
    if not dt:
        return "unknown"
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


@dataclass
class MonitorState:
    known_assignments: dict[str, dict[str, Any]] = field(default_factory=dict)
    reminder_log: dict[str, list[int]] = field(default_factory=dict)
    last_check: str = ""


@dataclass(frozen=True)
class NotificationEvent:
    event_type: str  # NEW / DUE
    message: str


def _empty_state() -> MonitorState:
    return MonitorState()


def load_state(path: Path) -> MonitorState:
    if not path.exists():
        return _empty_state()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_state()

    if isinstance(raw, list):
        # Backward-compatible migration for old [activityId, ...] format.
        known = {str(aid): {"migrated": True} for aid in raw}
        return MonitorState(known_assignments=known)

    if not isinstance(raw, dict):
        return _empty_state()

    known = raw.get("known_assignments", {})
    reminder_log = raw.get("reminder_log", {})
    last_check = str(raw.get("last_check", "")).strip()

    if not isinstance(known, dict):
        known = {}
    if not isinstance(reminder_log, dict):
        reminder_log = {}

    normalized_known: dict[str, dict[str, Any]] = {}
    for key, value in known.items():
        key_text = str(key)
        if isinstance(value, dict):
            normalized_known[key_text] = value
        else:
            normalized_known[key_text] = {"raw": str(value)}

    normalized_reminders: dict[str, list[int]] = {}
    for key, value in reminder_log.items():
        if not isinstance(value, list):
            continue
        days: list[int] = []
        for each in value:
            try:
                days.append(int(each))
            except Exception:
                continue
        normalized_reminders[str(key)] = sorted(set(days), reverse=True)

    return MonitorState(
        known_assignments=normalized_known,
        reminder_log=normalized_reminders,
        last_check=last_check,
    )


def save_state(path: Path, state: MonitorState) -> None:
    payload = {
        "known_assignments": state.known_assignments,
        "reminder_log": state.reminder_log,
        "last_check": state.last_check,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _load_headers(settings: Settings) -> dict[str, str]:
    headers: dict[str, str] = {}

    if settings.header_file.exists():
        try:
            raw = json.loads(settings.header_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key, value in raw.items():
                    if isinstance(key, str) and isinstance(value, str):
                        headers[key] = value
        except Exception:
            pass

    if settings.authorization:
        headers["authorization"] = settings.authorization
    if settings.blade_auth:
        headers["blade-auth"] = settings.blade_auth

    lowered = {key.lower() for key in headers.keys()}
    if "authorization" not in lowered and "blade-auth" not in lowered:
        raise FileNotFoundError(
            f"No valid auth headers found. Configure AUTHORIZATION/BLADE_AUTH in .env "
            f"or capture headers to {settings.header_file}"
        )

    return headers


def _get_header_case_insensitive(headers: dict[str, str], target_key: str) -> str:
    low = target_key.lower()
    for key, value in headers.items():
        if key.lower() == low:
            return value
    return ""


def _infer_user_id_from_headers_or_token(settings: Settings, headers: dict[str, str]) -> str:
    if settings.user_id:
        return settings.user_id

    blade_auth = settings.blade_auth or _get_header_case_insensitive(headers, "blade-auth")
    if not blade_auth:
        return ""

    try:
        parts = blade_auth.split(".")
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


def fetch_undone_list(settings: Settings) -> list[dict[str, Any]]:
    headers = _load_headers(settings)
    user_id = _infer_user_id_from_headers_or_token(settings, headers)
    if not user_id:
        raise ValueError(
            "USER_ID is empty and cannot be inferred from BLADE_AUTH. "
            "Set USER_ID in .env or provide valid blade-auth token."
        )

    params = {"userId": user_id, "size": settings.page_size}

    session = requests.Session()
    if settings.disable_system_proxy:
        session.trust_env = False

    last_error: Exception | None = None
    for attempt in range(1, settings.request_retries + 1):
        try:
            response = session.get(
                settings.undone_url,
                headers=headers,
                params=params,
                timeout=settings.request_timeout_sec,
            )

            if response.status_code in (401, 403):
                raise AuthExpiredError(
                    f"Auth failed with status code {response.status_code}. "
                    "Auth headers may have expired."
                )
            response.raise_for_status()

            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("API payload is not a JSON object.")

            data = payload.get("data", {})
            if not isinstance(data, dict):
                raise ValueError("API payload field `data` is invalid.")

            undone_list = data.get("undoneList", [])
            if not isinstance(undone_list, list):
                raise ValueError("API payload field `undoneList` is not a list.")

            return [item for item in undone_list if isinstance(item, dict)]
        except AuthExpiredError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < settings.request_retries:
                time.sleep(settings.request_retry_delay_sec)

    if last_error is None:
        raise RuntimeError("Unknown error while fetching undone assignments.")
    raise RuntimeError(f"Failed to fetch undone assignments: {last_error}") from last_error


def _new_assignment_message(item: dict[str, Any], deadline: datetime | None) -> str:
    title = _pick_str(item, "activityName", "name", "title", default="Untitled")
    course = _pick_str(item, "courseName", "className", "course", default="Unknown Course")
    return f"[NEW] {course} | {title} | Due: {_format_deadline(deadline)}"


def _deadline_message(item: dict[str, Any], deadline: datetime, days_left: int) -> str:
    title = _pick_str(item, "activityName", "name", "title", default="Untitled")
    course = _pick_str(item, "courseName", "className", "course", default="Unknown Course")
    return f"[DUE] {days_left} day(s) left | {course} | {title} | Due: {_format_deadline(deadline)}"


def _assignment_id(item: dict[str, Any]) -> str:
    return _pick_str(item, "activityId", "id", "homeworkId")


def analyze_assignments(
    undone_list: list[dict[str, Any]],
    state: MonitorState,
    settings: Settings,
    now: datetime | None = None,
) -> list[NotificationEvent]:
    current = now or _now_local()
    events: list[NotificationEvent] = []

    for item in undone_list:
        aid = _assignment_id(item)
        if not aid:
            continue

        deadline = _extract_deadline(item)
        known_info = state.known_assignments.get(aid)

        if known_info is None:
            state.known_assignments[aid] = {
                "name": _pick_str(item, "activityName", "name", "title"),
                "course": _pick_str(item, "courseName", "className", "course"),
                "first_seen": current.isoformat(),
                "deadline": deadline.isoformat() if deadline else "",
            }
            events.append(
                NotificationEvent(
                    event_type="NEW",
                    message=_new_assignment_message(item, deadline),
                )
            )
        else:
            if not isinstance(known_info, dict):
                known_info = {"raw": str(known_info)}
                state.known_assignments[aid] = known_info
            if deadline:
                known_info["deadline"] = deadline.isoformat()

        if not deadline:
            continue

        seconds_left = (deadline - current).total_seconds()
        if seconds_left < 0:
            continue

        days_left = math.ceil(seconds_left / 86400.0)
        if days_left not in settings.reminder_days:
            continue

        history = state.reminder_log.setdefault(aid, [])
        if days_left in history:
            continue

        history.append(days_left)
        history[:] = sorted(set(history), reverse=True)
        events.append(
            NotificationEvent(
                event_type="DUE",
                message=_deadline_message(item, deadline, days_left),
            )
        )

    state.last_check = current.isoformat()
    return events


class Notifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        if self.settings.disable_system_proxy:
            self.session.trust_env = False

    def _send_webhook(self, message: str) -> None:
        if not self.settings.notify_webhook_url:
            return
        try:
            self.session.post(
                self.settings.notify_webhook_url,
                json={"text": message},
                timeout=self.settings.request_timeout_sec,
            )
        except Exception as exc:
            print(f"[warn] webhook send failed: {exc}")

    def _send_wechat(self, message: str) -> None:
        if not self.settings.wechat_webhook_url:
            return
        payload = {"msgtype": "text", "text": {"content": message}}
        try:
            self.session.post(
                self.settings.wechat_webhook_url,
                json=payload,
                timeout=self.settings.request_timeout_sec,
            )
        except Exception as exc:
            print(f"[warn] wechat send failed: {exc}")

    def _send_pushplus(self, title: str, message: str) -> None:
        if not self.settings.pushplus_token:
            return
        payload: dict[str, Any] = {
            "token": self.settings.pushplus_token,
            "title": title,
            "content": message,
            "template": self.settings.pushplus_template or "txt",
        }
        if self.settings.pushplus_topic:
            payload["topic"] = self.settings.pushplus_topic
        try:
            self.session.post(
                "https://www.pushplus.plus/send",
                json=payload,
                timeout=self.settings.request_timeout_sec,
            )
        except Exception as exc:
            print(f"[warn] pushplus send failed: {exc}")

    def _send_email(self, subject: str, message: str) -> None:
        if not self.settings.smtp_host or not self.settings.smtp_to:
            return

        from_addr = self.settings.smtp_from or self.settings.smtp_username
        if not from_addr:
            print("[warn] email skipped: SMTP_FROM/SMTP_USERNAME is empty.")
            return

        email = EmailMessage()
        email["Subject"] = subject
        email["From"] = from_addr
        email["To"] = ", ".join(self.settings.smtp_to)
        email.set_content(message)

        try:
            if self.settings.smtp_use_ssl:
                server = smtplib.SMTP_SSL(
                    self.settings.smtp_host,
                    self.settings.smtp_port,
                    timeout=self.settings.request_timeout_sec,
                )
            else:
                server = smtplib.SMTP(
                    self.settings.smtp_host,
                    self.settings.smtp_port,
                    timeout=self.settings.request_timeout_sec,
                )

            with server:
                if not self.settings.smtp_use_ssl and self.settings.smtp_starttls:
                    server.starttls()
                if self.settings.smtp_username:
                    server.login(self.settings.smtp_username, self.settings.smtp_password)
                server.send_message(email)
        except Exception as exc:
            print(f"[warn] email send failed: {exc}")

    def _send_desktop(self, title: str, message: str) -> None:
        def _ps_quote(text: str) -> str:
            return text.replace("'", "''")

        script = (
            "$ErrorActionPreference='Stop';"
            "Add-Type -AssemblyName System.Windows.Forms;"
            "Add-Type -AssemblyName System.Drawing;"
            "$notify = New-Object System.Windows.Forms.NotifyIcon;"
            "$notify.Icon = [System.Drawing.SystemIcons]::Information;"
            f"$notify.BalloonTipTitle = '{_ps_quote(title)}';"
            f"$notify.BalloonTipText = '{_ps_quote(message)}';"
            "$notify.Visible = $true;"
            "$notify.ShowBalloonTip(5000);"
            "Start-Sleep -Seconds 6;"
            "$notify.Dispose();"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            print(f"[warn] desktop notify failed: {exc}")

    def _write_markdown(self, rows: list[str]) -> None:
        if not rows:
            return
        path = self.settings.markdown_output_file
        path.parent.mkdir(parents=True, exist_ok=True)
        now = _now_local().strftime("%Y-%m-%d %H:%M:%S %z")
        lines = [f"## Run At {now}", ""]
        for row in rows:
            lines.append(f"- {row}")
        lines.append("")
        block = "\n".join(lines)

        if self.settings.markdown_append and path.exists():
            with path.open("a", encoding="utf-8") as f:
                f.write("\n" + block)
        else:
            with path.open("w", encoding="utf-8") as f:
                f.write("# Homework Reminders\n\n" + block)

    def send_many(self, events: list[NotificationEvent]) -> None:
        event_allow = set(e.upper() for e in self.settings.notify_events)
        channels = set(ch.lower() for ch in self.settings.notify_channels)
        selected_rows: list[str] = []

        for event in events:
            if event_allow and event.event_type.upper() not in event_allow:
                continue

            message = f"{self.settings.notify_title_prefix} {event.message}".strip()
            selected_rows.append(message)
            if self.settings.enable_console_notify and "console" in channels:
                print(message)
            if "webhook" in channels:
                self._send_webhook(message)
            if "wechat" in channels:
                self._send_wechat(message)
            if "pushplus" in channels:
                subject = f"{self.settings.notify_title_prefix} {event.event_type}".strip()
                self._send_pushplus(subject, message)
            if "email" in channels:
                subject = f"{self.settings.notify_title_prefix} {event.event_type}".strip()
                self._send_email(subject, message)
            if "desktop" in channels:
                self._send_desktop(self.settings.notify_title_prefix, event.message)

        if "markdown" in channels:
            self._write_markdown(selected_rows)


def run_monitor_once(*, dry_run: bool = False) -> list[str]:
    settings = load_settings()
    state = load_state(settings.state_file)
    undone_list = fetch_undone_list(settings)
    events = analyze_assignments(undone_list, state, settings)

    if events:
        Notifier(settings).send_many(events)
    else:
        print("[ok] no new assignments and no due reminders in this run.")

    if not dry_run:
        save_state(settings.state_file, state)

    return [e.message for e in events]
