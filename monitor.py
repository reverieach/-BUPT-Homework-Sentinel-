import argparse
import subprocess
import sys
from pathlib import Path

from capture_headers import capture_valid_headers
from config import load_settings
from monitor_core import AuthExpiredError, Notifier, run_monitor_once


def _ps_single_quote(value: str) -> str:
    return value.replace("'", "''")


def run_monitor(*, dry_run: bool = False, auto_refresh_on_401: bool = True) -> None:
    try:
        run_monitor_once(dry_run=dry_run)
    except AuthExpiredError:
        if not auto_refresh_on_401:
            raise
        print("[warn] auth expired, refreshing headers once...")
        capture_valid_headers()
        run_monitor_once(dry_run=dry_run)


def install_windows_daily_task(task_name: str, task_time: str, no_console: bool = True) -> None:
    script_path = Path(__file__).resolve()
    cwd = script_path.parent
    python_exe = Path(sys.executable).resolve()
    pythonw_exe = python_exe.with_name("pythonw.exe")
    execute_path = pythonw_exe if (no_console and pythonw_exe.exists()) else python_exe
    ps = f"""
$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction `
  -Execute '{_ps_single_quote(str(execute_path))}' `
  -Argument '"{_ps_single_quote(str(script_path))}"' `
  -WorkingDirectory '{_ps_single_quote(str(cwd))}'
$trigger = New-ScheduledTaskTrigger -Daily -At '{_ps_single_quote(task_time)}'
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -WakeToRun `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries
Register-ScheduledTask `
  -TaskName '{_ps_single_quote(task_name)}' `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Description 'Homework monitor daily task' `
  -Force | Out-Null
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    print(f"[ok] installed task: {task_name} at {task_time}, no_console={no_console}")


def remove_windows_task(task_name: str) -> None:
    cmd = ["schtasks", "/Delete", "/TN", task_name, "/F"]
    subprocess.run(cmd, check=True)
    print(f"[ok] removed task: {task_name}")


def disable_windows_task(task_name: str) -> None:
    cmd = ["schtasks", "/Change", "/TN", task_name, "/Disable"]
    subprocess.run(cmd, check=True)
    print(f"[ok] disabled task: {task_name}")


def enable_windows_task(task_name: str) -> None:
    cmd = ["schtasks", "/Change", "/TN", task_name, "/Enable"]
    subprocess.run(cmd, check=True)
    print(f"[ok] enabled task: {task_name}")


def end_windows_task(task_name: str) -> None:
    cmd = ["schtasks", "/End", "/TN", task_name]
    subprocess.run(cmd, check=True)
    print(f"[ok] ended running instance: {task_name}")


def show_windows_task(task_name: str) -> None:
    cmd = ["schtasks", "/Query", "/TN", task_name, "/V", "/FO", "LIST"]
    subprocess.run(cmd, check=True)


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

    args = parser.parse_args()
    try:
        if args.install_daily_task:
            install_windows_daily_task(
                args.task_name,
                args.task_time,
                no_console=not args.task_show_console,
            )
        elif args.remove_task:
            remove_windows_task(args.task_name)
        elif args.show_task:
            show_windows_task(args.task_name)
        elif args.disable_task:
            disable_windows_task(args.task_name)
        elif args.enable_task:
            enable_windows_task(args.task_name)
        elif args.end_task:
            end_windows_task(args.task_name)
        elif args.test_desktop_notify:
            test_desktop_notify()
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
