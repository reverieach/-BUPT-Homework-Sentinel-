from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Hide console window for subprocess calls on Windows.
_CREATE_NO_WINDOW = 0x0800_0000


def _ps_single_quote(value: str) -> str:
    return value.replace("'", "''")


def _run_silent(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with hidden window and captured output."""
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        creationflags=_CREATE_NO_WINDOW,
        **kwargs,
    )


def _check_result(proc: subprocess.CompletedProcess[str], ok_msg: str) -> str:
    if proc.returncode == 0:
        return ok_msg
    detail = (proc.stderr or proc.stdout or "").strip()
    return f"[error] command failed (exit {proc.returncode})\n{detail}"


def ensure_hidden_launcher(script_path: Path, python_exec: Path) -> Path:
    cwd = script_path.parent
    launcher = cwd / ".monitor_hidden_runner.vbs"
    content = [
        'Set shell = CreateObject("Wscript.Shell")',
        f'shell.CurrentDirectory = "{cwd}"',
        f'cmd = """" & "{python_exec}" & """ """ & "{script_path}" & """"',
        "shell.Run cmd, 0, False",
    ]
    launcher.write_text("\n".join(content) + "\n", encoding="utf-8")
    return launcher


def install_windows_daily_task(task_name: str, task_time: str, no_console: bool = True) -> str:
    script_path = (Path(__file__).parent / "monitor.py").resolve()
    cwd = script_path.parent
    python_exe = Path(sys.executable).resolve()
    pythonw_exe = python_exe.with_name("pythonw.exe")
    execute_path = pythonw_exe if (no_console and pythonw_exe.exists()) else python_exe
    launcher_path = ensure_hidden_launcher(script_path, execute_path)

    ps = f"""
$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction `
  -Execute 'wscript.exe' `
  -Argument '"{_ps_single_quote(str(launcher_path))}"' `
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
    proc = _run_silent(["powershell", "-NoProfile", "-Command", ps])
    return _check_result(proc, f"[ok] installed task: {task_name} at {task_time}, no_console={no_console}")


def remove_windows_task(task_name: str) -> str:
    proc = _run_silent(["schtasks", "/Delete", "/TN", task_name, "/F"])
    return _check_result(proc, f"[ok] removed task: {task_name}")


def disable_windows_task(task_name: str) -> str:
    proc = _run_silent(["schtasks", "/Change", "/TN", task_name, "/Disable"])
    return _check_result(proc, f"[ok] disabled task: {task_name}")


def enable_windows_task(task_name: str) -> str:
    proc = _run_silent(["schtasks", "/Change", "/TN", task_name, "/Enable"])
    return _check_result(proc, f"[ok] enabled task: {task_name}")


def end_windows_task(task_name: str) -> str:
    proc = _run_silent(["schtasks", "/End", "/TN", task_name])
    return _check_result(proc, f"[ok] ended running instance: {task_name}")


def run_windows_task_now(task_name: str) -> str:
    proc = _run_silent(["schtasks", "/Run", "/TN", task_name])
    return _check_result(proc, f"[ok] started task now: {task_name}")


def query_windows_task_text(task_name: str) -> str:
    proc = _run_silent(["schtasks", "/Query", "/TN", task_name, "/V", "/FO", "LIST"])
    if proc.returncode == 0:
        return proc.stdout
    detail = (proc.stderr or proc.stdout or "").strip()
    return f"[error] failed to query task (exit {proc.returncode})\n{detail}"
