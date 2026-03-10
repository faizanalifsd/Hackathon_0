"""
approval_watcher.py – HITL Approval Watcher (Approved/ -> Execute -> Done/)

Monitors Vault/Approved/ for plan files that have been approved by the human.
For each approved plan it:
  1. Reads the plan and determines what actions to execute
  2. Invokes Claude (via CLI) to execute the plan steps
  3. Logs the execution result
  4. Moves the task item and plan to Done/

This is the enforcement point for Human-in-the-Loop (HITL):
  NOTHING executes without the file first landing in Vault/Approved/.

Usage:
    uv run python approval_watcher.py           # process all approved items once
    uv run python approval_watcher.py --daemon  # watch continuously (watchdog)

Workflow:
    Plans/PLAN_task.md
        ↓ (reasoning_loop.py — if approval needed)
    Pending_Approval/PLAN_task.md
        ↓ (YOU move/copy here after review)
    Approved/PLAN_task.md
        ↓ (this script)
    Done/PLAN_task.md  +  Done/task.md
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileMovedEvent
from watchdog.observers import Observer

from vault_io import VaultIO

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
VAULT_ROOT = BASE_DIR / "Vault"
APPROVED_DIR = VAULT_ROOT / "Approved"
LOG_FILE = BASE_DIR / "approval_watcher.log"

import io
_console = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(_console),
    ],
)
log = logging.getLogger("approval-watcher")


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _find_claude_cmd() -> list[str]:
    """Return the correct claude CLI command for the current platform."""
    import shutil
    if sys.platform == "win32":
        for candidate in ["claude.cmd", "claude"]:
            path = shutil.which(candidate)
            if path:
                return [path]
        npm_claude = Path.home() / "AppData/Roaming/npm/claude.cmd"
        if npm_claude.exists():
            return [str(npm_claude)]
    else:
        path = shutil.which("claude")
        if path:
            return [path]
    return []


def _execute_plan_via_claude(plan_name: str, plan_content: str) -> tuple[bool, str]:
    """
    Ask Claude to execute the steps in an approved plan.
    Returns (success: bool, output: str).
    """
    prompt = f"""You are an AI Employee. The human has APPROVED the following plan.
Execute ALL steps in the plan, including sending emails.

You have access to the gmail_send MCP tool. Use it to send any email replies described in the plan.
Extract the recipient (to), subject, and body from the plan steps and call gmail_send directly.

APPROVED PLAN ({plan_name}):
{plan_content}

After executing, respond with:
## Execution Report
### Completed Steps
- list what you did (including emails sent with recipient + subject)

### Remaining Human Actions
- list anything that truly cannot be automated (e.g. physical actions, payments)

### Status
COMPLETE | PARTIAL | BLOCKED
"""
    claude_cmd = _find_claude_cmd()
    if not claude_cmd:
        return False, "'claude' CLI not found"
    try:
        # Unset CLAUDECODE so claude CLI can run outside an active session
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        result = subprocess.run(
            claude_cmd + ["--print", "--dangerously-skip-permissions", prompt],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(BASE_DIR),
            env=env,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip()
    except FileNotFoundError:
        return False, "'claude' CLI not found"
    except subprocess.TimeoutExpired:
        return False, "Claude execution timed out"


def _find_task_file(vault: VaultIO, plan_name: str) -> str | None:
    """
    Given PLAN_task.md, find the matching task.md in Needs_Action or Inbox.
    Returns relative path or None.
    """
    # Strip PLAN_ prefix and .md suffix
    task_name = plan_name.removeprefix("PLAN_")
    for folder in ["Needs_Action", "Inbox"]:
        rel = f"{folder}/{task_name}"
        full = vault.root / rel
        if full.exists():
            return rel
    return None


def process_approved_plan(vault: VaultIO, plan_path: Path) -> None:
    """Process a single approved plan file."""
    plan_name = plan_path.name
    log.info("Processing approved plan: %s", plan_name)

    try:
        plan_content = plan_path.read_text(encoding="utf-8")
    except Exception as exc:
        log.error("Cannot read %s: %s", plan_name, exc)
        return

    # Execute via Claude
    success, output = _execute_plan_via_claude(plan_name, plan_content)
    result_str = "success" if success else "failed"
    log.info("Execution %s for %s", result_str, plan_name)

    # Write execution report as a note alongside the plan
    report_path = vault.root / "Done" / f"REPORT_{plan_name}"
    report_content = f"""---
type: execution_report
plan: {plan_name}
executed_at: {datetime.now().strftime("%Y-%m-%d %H:%M")}
result: {result_str}
---

# Execution Report: {plan_name}

{output}
"""
    try:
        report_path.write_text(report_content, encoding="utf-8")
    except Exception as exc:
        log.error("Failed to write report: %s", exc)

    # Move approved plan -> Done (Claude may have already moved it during execution)
    rel_plan = f"Approved/{plan_name}"
    if (vault.root / rel_plan).exists():
        try:
            vault.move_to_done(rel_plan, summary=f"Executed on {datetime.now():%Y-%m-%d %H:%M}")
            log.info("Moved plan -> Done/%s", plan_name)
        except Exception as exc:
            log.error("Failed to move plan to Done: %s", exc)
    else:
        log.info("Plan already moved to Done by Claude during execution — skipping.")

    # Move original task -> Done (if found)
    task_rel = _find_task_file(vault, plan_name)
    if task_rel:
        try:
            vault.move_to_done(task_rel, summary="Completed via approved plan")
            log.info("Moved task -> Done/%s", Path(task_rel).name)
        except Exception as exc:
            log.error("Failed to move task to Done: %s", exc)
    else:
        log.info("No matching task file found for %s — skipping task move.", plan_name)

    # Audit log
    vault.log_action(
        action_type="plan_executed",
        actor="approval_watcher",
        target=plan_name,
        approval_status="approved",
        result=result_str,
        details=output[:500] if output else "",
    )

    # Update dashboard
    vault.update_dashboard(
        recent_activity=f"- {datetime.now():%Y-%m-%d %H:%M} — Executed approved plan: `{plan_name}` -> {result_str}"
    )


def process_all_approved(vault: VaultIO) -> int:
    """Process all PLAN_*.md files currently in Approved/. Returns count processed."""
    APPROVED_DIR.mkdir(parents=True, exist_ok=True)
    items = list(APPROVED_DIR.glob("PLAN_*.md"))
    if not items:
        log.info("No approved items to process.")
        return 0
    for plan_path in items:
        process_approved_plan(vault, plan_path)
    return len(items)


# ---------------------------------------------------------------------------
# Watchdog handler (daemon mode)
# ---------------------------------------------------------------------------

class ApprovedHandler(FileSystemEventHandler):
    def __init__(self, vault: VaultIO):
        self.vault = vault

    def _handle(self, path: Path):
        if path.name.startswith("PLAN_") and path.suffix.lower() == ".md" and path.parent == APPROVED_DIR:
            log.info("New approved item detected: %s", path.name)
            # Small delay to ensure file is fully written
            time.sleep(1)
            process_approved_plan(self.vault, path)

    def on_created(self, event):
        if not event.is_directory:
            self._handle(Path(event.src_path))

    def on_moved(self, event):
        if not event.is_directory:
            self._handle(Path(event.dest_path))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="HITL Approval Watcher")
    parser.add_argument("--daemon", action="store_true",
                        help="Watch Approved/ folder continuously via watchdog")
    args = parser.parse_args()

    vault = VaultIO()
    APPROVED_DIR.mkdir(parents=True, exist_ok=True)

    log.info("Approval Watcher started.")

    if args.daemon:
        # First, process any items already waiting
        n = process_all_approved(vault)
        log.info("Processed %d pre-existing approved item(s).", n)

        # Then watch for new ones
        handler = ApprovedHandler(vault)
        observer = Observer()
        observer.schedule(handler, str(APPROVED_DIR), recursive=False)
        observer.start()
        log.info("Watching Vault/Approved/ for new approvals. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("Stopping approval watcher...")
            observer.stop()
        observer.join()
        log.info("Approval Watcher stopped.")
    else:
        n = process_all_approved(vault)
        log.info("Done. Processed %d approved item(s).", n)


if __name__ == "__main__":
    main()
