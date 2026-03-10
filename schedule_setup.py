"""
schedule_setup.py – Windows Task Scheduler setup for Silver Tier.

Creates scheduled tasks for:
  1. Daily 8 AM Briefing  — runs reasoning_loop.py
  2. Hourly Gmail fetch   — runs gmail_watcher.py
  3. Approval watcher     — runs approval_watcher.py --daemon (on login)

Run as Administrator:
    uv run python schedule_setup.py --install
    uv run python schedule_setup.py --remove
    uv run python schedule_setup.py --status
"""

import argparse
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
UV = BASE_DIR / ".venv" / "Scripts" / "uv.exe"

# Fall back to system uv if venv uv not found
if not UV.exists():
    UV = "uv"

PYTHON_ARGS = f'run --project "{BASE_DIR}"'


def _schtasks(*args: str) -> tuple[int, str]:
    cmd = ["schtasks"] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, shell=False)
    return result.returncode, result.stdout + result.stderr


def install_tasks():
    tasks = [
        {
            "name": "AIEmployee_DailyBriefing",
            "description": "Daily 8 AM — AI Employee reasoning loop (Needs_Action → Plans)",
            "schedule": "DAILY",
            "time": "08:00",
            "command": str(UV),
            "args": f'{PYTHON_ARGS} python reasoning_loop.py',
        },
        {
            "name": "AIEmployee_GmailFetch",
            "description": "Hourly Gmail fetch → Vault/Inbox",
            "schedule": "HOURLY",
            "time": "00:00",
            "command": str(UV),
            "args": f'{PYTHON_ARGS} python gmail_watcher.py',
        },
        {
            "name": "AIEmployee_LinkedInPost",
            "description": "Daily 9 AM — Generate LinkedIn post draft from vault leads",
            "schedule": "DAILY",
            "time": "09:00",
            "command": str(UV),
            "args": f'{PYTHON_ARGS} python linkedin_poster.py --generate',
        },
    ]

    print("Installing scheduled tasks...")
    for task in tasks:
        rc, out = _schtasks(
            "/Create",
            "/F",  # overwrite if exists
            "/TN", task["name"],
            "/TR", f'"{task["command"]}" {task["args"]}',
            "/SC", task["schedule"],
            "/ST", task["time"],
            "/RL", "HIGHEST",
            "/D", "MON,TUE,WED,THU,FRI,SAT,SUN",
        )
        status = "OK" if rc == 0 else f"FAILED (code {rc})"
        print(f"  [{status}] {task['name']}")
        if rc != 0:
            print(f"         {out.strip()}")

    # Approval watcher as an on-logon task
    rc, out = _schtasks(
        "/Create", "/F",
        "/TN", "AIEmployee_ApprovalWatcher",
        "/TR", f'"{UV}" {PYTHON_ARGS} python approval_watcher.py --daemon',
        "/SC", "ONLOGON",
        "/RL", "HIGHEST",
    )
    status = "OK" if rc == 0 else f"FAILED (code {rc})"
    print(f"  [{status}] AIEmployee_ApprovalWatcher (on logon)")
    if rc != 0:
        print(f"         {out.strip()}")

    print("\nDone. To verify: uv run python schedule_setup.py --status")


def remove_tasks():
    task_names = [
        "AIEmployee_DailyBriefing",
        "AIEmployee_GmailFetch",
        "AIEmployee_LinkedInPost",
        "AIEmployee_ApprovalWatcher",
    ]
    print("Removing scheduled tasks...")
    for name in task_names:
        rc, out = _schtasks("/Delete", "/F", "/TN", name)
        status = "OK" if rc == 0 else f"NOT FOUND or FAILED"
        print(f"  [{status}] {name}")


def show_status():
    task_names = [
        "AIEmployee_DailyBriefing",
        "AIEmployee_GmailFetch",
        "AIEmployee_LinkedInPost",
        "AIEmployee_ApprovalWatcher",
    ]
    print("Scheduled task status:")
    for name in task_names:
        rc, out = _schtasks("/Query", "/TN", name, "/FO", "LIST")
        if rc == 0:
            # Extract Status line
            for line in out.splitlines():
                if "Status" in line or "Next Run" in line:
                    print(f"  {name}: {line.strip()}")
        else:
            print(f"  {name}: NOT INSTALLED")


def main():
    parser = argparse.ArgumentParser(description="Windows Task Scheduler setup for AI Employee")
    parser.add_argument("--install", action="store_true", help="Install all scheduled tasks")
    parser.add_argument("--remove", action="store_true", help="Remove all scheduled tasks")
    parser.add_argument("--status", action="store_true", help="Show status of all tasks")
    args = parser.parse_args()

    if args.install:
        install_tasks()
    elif args.remove:
        remove_tasks()
    elif args.status:
        show_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    if sys.platform != "win32":
        print("This script is for Windows only. On Mac/Linux, use cron instead.")
        sys.exit(1)
    main()
