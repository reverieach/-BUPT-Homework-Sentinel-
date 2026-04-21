import argparse

from capture_headers import capture_valid_headers
from config import load_settings
from monitor_core import AuthExpiredError, Notifier, run_monitor_once
from task_scheduler import (
    disable_windows_task,
    enable_windows_task,
    end_windows_task,
    install_windows_daily_task,
    query_windows_task_text,
    remove_windows_task,
)


def run_monitor(*, dry_run: bool = False, auto_refresh_on_401: bool = True) -> None:
    try:
        run_monitor_once(dry_run=dry_run)
    except AuthExpiredError:
        if not auto_refresh_on_401:
            raise
        print("[warn] auth expired, refreshing headers once...")
        capture_valid_headers()
        run_monitor_once(dry_run=dry_run)


def show_windows_task(task_name: str) -> None:
    print(query_windows_task_text(task_name))


def test_desktop_notify() -> None:
    settings = load_settings()
    notifier = Notifier(settings)
    notifier._send_desktop(settings.notify_title_prefix, "Desktop notification test message.")
    print("[ok] desktop test notification triggered.")


def main() -> None:
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Homework monitor CLI.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run check without writing state file.",
    )
    parser.add_argument(
        "--no-auto-refresh-on-401",
        action="store_true",
        help="Disable auto header refresh when API returns 401/403.",
    )
    parser.add_argument(
        "--capture-headers",
        action="store_true",
        help="Capture and save latest auth headers, then exit.",
    )
    parser.add_argument(
        "--install-daily-task",
        action="store_true",
        help="Install Windows scheduled task to run monitor daily.",
    )
    parser.add_argument(
        "--remove-task",
        action="store_true",
        help="Remove Windows scheduled task by task name.",
    )
    parser.add_argument(
        "--show-task",
        action="store_true",
        help="Show Windows scheduled task details by task name.",
    )
    parser.add_argument(
        "--disable-task",
        action="store_true",
        help="Disable Windows scheduled task by task name.",
    )
    parser.add_argument(
        "--enable-task",
        action="store_true",
        help="Enable Windows scheduled task by task name.",
    )
    parser.add_argument(
        "--end-task",
        action="store_true",
        help="End current running instance of Windows scheduled task.",
    )
    parser.add_argument(
        "--task-name",
        default="HomeworkMonitorDaily",
        help="Task Scheduler name.",
    )
    parser.add_argument(
        "--task-time",
        default="19:00",
        help="Task run time in HH:MM (24h), for install command.",
    )
    parser.add_argument(
        "--task-show-console",
        action="store_true",
        help="Install task with python console window (default is hidden via pythonw).",
    )
    parser.add_argument(
        "--test-desktop-notify",
        action="store_true",
        help="Send one desktop notification test message.",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Start the local web control console.",
    )
    parser.add_argument(
        "--web-host",
        default="127.0.0.1",
        help="Web console host.",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=5000,
        help="Web console port.",
    )
    args = parser.parse_args()
    try:
        if args.install_daily_task:
            print(
                install_windows_daily_task(
                args.task_name,
                args.task_time,
                no_console=not args.task_show_console,
                )
            )
        elif args.remove_task:
            print(remove_windows_task(args.task_name))
        elif args.show_task:
            show_windows_task(args.task_name)
        elif args.disable_task:
            print(disable_windows_task(args.task_name))
        elif args.enable_task:
            print(enable_windows_task(args.task_name))
        elif args.end_task:
            print(end_windows_task(args.task_name))
        elif args.test_desktop_notify:
            test_desktop_notify()
        elif args.web:
            from control_panel import run_control_panel

            run_control_panel(host=args.web_host, port=args.web_port)
        elif args.capture_headers:
            capture_valid_headers()
        else:
            run_monitor(
                dry_run=args.dry_run,
                auto_refresh_on_401=(
                    settings.auto_refresh_headers_on_401 and not args.no_auto_refresh_on_401
                ),
            )
    except Exception as exc:
        print(f"[error] {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
