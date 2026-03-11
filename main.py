"""
main.py – Single orchestrator for the AI Vault pipeline.

Runs all watchers in threads and chains each step automatically via
watchdog file-system events (no polling delays between steps).

Pipeline:
    gmail_watcher (every 2 min)
        → Inbox/          (watchdog → instant triage)
        → Needs_Action/   (watchdog → instant plan generation)
        → Plans/          (YOU open, edit, tick checkbox, save)
            ✅ Approve     → Approved/ → execution + email send → Done/
            ⏸ Pending     → Pending_Approval/ (hold for later)

Usage:
    uv run python main.py
"""

import logging
import sys
import threading
import time
import io
from datetime import datetime
from pathlib import Path

from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileMovedEvent
from watchdog.observers import Observer

from vault_io import VaultIO

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
LOG_FILE = BASE_DIR / "main.log"

_console = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(_console),
    ],
)
log = logging.getLogger("main")


# ---------------------------------------------------------------------------
# Step 1: Gmail poller thread
# ---------------------------------------------------------------------------

def _gmail_poll_loop(interval: int = 120):
    """Poll Gmail every `interval` seconds and write emails to Inbox/."""
    try:
        from gmail_watcher import get_gmail_service, fetch_and_save_emails
    except ImportError as e:
        log.error("gmail_watcher import failed: %s", e)
        return

    log.info("[Gmail] Authenticating...")
    try:
        service = get_gmail_service()
    except SystemExit:
        log.error("[Gmail] Auth failed — check credentials.json / token.json")
        return

    log.info("[Gmail] Polling every %ds for unread important emails.", interval)
    while True:
        try:
            count = fetch_and_save_emails(service)
            if count:
                log.info("[Gmail] Fetched %d email(s) → Inbox/", count)
        except Exception as exc:
            log.error("[Gmail] Poll error: %s", exc)
        time.sleep(interval)


# ---------------------------------------------------------------------------
# Step 2: Inbox watchdog → triage → Needs_Action
# ---------------------------------------------------------------------------

def _triage_file(path: Path, vault: VaultIO):
    """Run vault-triage on a new Inbox file via claude CLI."""
    import subprocess, shutil
    rel = path.relative_to(vault.root)
    log.info("[Triage] Processing: %s", path.name)

    # Find claude CLI
    claude = None
    for candidate in (["claude.cmd", "claude"] if sys.platform == "win32" else ["claude"]):
        found = shutil.which(candidate)
        if found:
            claude = found
            break
    if not claude:
        npm_path = Path.home() / "AppData/Roaming/npm/claude.cmd"
        if npm_path.exists():
            claude = str(npm_path)

    if claude:
        try:
            import os
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            result = subprocess.run(
                [claude, "--print",
                 f"Use the vault-triage skill to process this new inbox item: {rel}"],
                capture_output=True, text=True, timeout=120,
                cwd=str(BASE_DIR), env=env,
            )
            if result.returncode == 0:
                # Verify the file was actually moved out of Inbox
                if not path.exists():
                    log.info("[Triage] Done: %s", path.name)
                    return
                log.warning("[Triage] Claude exited 0 but file still in Inbox — running fallback")
            else:
                log.warning("[Triage] Claude exit %d: %s", result.returncode, result.stderr[:200])
        except Exception as exc:
            log.warning("[Triage] Claude error: %s", exc)

    # Fallback: classify via router then move to Needs_Action
    log.info("[Triage] Fallback: classifying %s via router → Needs_Action/", path.name)
    try:
        classification = {"priority": "medium", "summary": "Auto-triaged — review needed"}
        try:
            from router import classify_email
            raw = path.read_text(encoding="utf-8")
            classification = classify_email(raw)
            log.info("[Triage] Router classified: priority=%s summary=%s",
                     classification.get("priority"), classification.get("summary", "")[:60])
        except Exception as exc:
            log.warning("[Triage] Router classification failed: %s", exc)

        vault.move_to_needs_action(
            str(rel),
            summary=classification.get("summary", "Auto-triaged — review needed"),
            priority=classification.get("priority", "medium"),
        )
        vault.update_dashboard(
            recent_activity=f"- {datetime.now():%Y-%m-%d %H:%M} — Fallback triage: `{path.name}` → Needs_Action"
        )
    except Exception as exc:
        log.error("[Triage] Fallback failed: %s", exc)


class InboxHandler(FileSystemEventHandler):
    def __init__(self, vault: VaultIO):
        self.vault = vault
        self._seen: set = set()
        self._lock = threading.Lock()

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() == ".md" and not path.name.startswith("."):
            with self._lock:
                if path.name in self._seen:
                    return
                self._seen.add(path.name)
            threading.Thread(
                target=_triage_file, args=(path, self.vault), daemon=True
            ).start()


# ---------------------------------------------------------------------------
# Step 3: Needs_Action watchdog → plan generation → Pending_Approval
# ---------------------------------------------------------------------------

def _plan_file(path: Path, vault: VaultIO):
    """Generate a plan for a newly triaged Needs_Action item."""
    from reasoning_loop import _plan_exists, _generate_plan_via_router, _generate_plan_fallback, _parse_plan_frontmatter_approval

    task_name = path.name
    if _plan_exists(vault, task_name):
        log.info("[Plan] Plan already exists for %s — skipping.", task_name)
        return

    log.info("[Plan] Generating plan for: %s", task_name)
    try:
        task_content = path.read_text(encoding="utf-8")
    except Exception as exc:
        log.error("[Plan] Cannot read %s: %s", task_name, exc)
        return

    plan_content = _generate_plan_via_router(task_name, task_content)
    if not plan_content:
        log.warning("[Plan] Using fallback plan for %s", task_name)
        plan_content = _generate_plan_fallback(task_name, task_content)

    try:
        plan_path = vault.write_plan(task_name, plan_content)
        log.info("[Plan] Written → %s", plan_path.name)
    except Exception as exc:
        log.error("[Plan] Failed to write plan: %s", exc)
        return

    vault.log_action(
        action_type="plan_generated", actor="main",
        target=task_name, approval_status="auto", result="success",
        details=f"Plan written to {plan_path.name}",
    )

    log.info("[Plan] Plan written to Plans/ → open in Obsidian, tick a checkbox, save to route it")
    vault.update_dashboard(
        recent_activity=f"- {datetime.now():%Y-%m-%d %H:%M} — Plan generated: `{plan_path.name}`"
    )


class NeedsActionHandler(FileSystemEventHandler):
    def __init__(self, vault: VaultIO):
        self.vault = vault
        self._seen: set = set()
        self._lock = threading.Lock()

    def _handle(self, path: Path):
        if path.suffix.lower() == ".md" and not path.name.startswith("."):
            with self._lock:
                if path.name in self._seen:
                    return
                self._seen.add(path.name)
            threading.Thread(
                target=_plan_file, args=(path, self.vault), daemon=True
            ).start()

    def on_created(self, event):
        if not event.is_directory:
            self._handle(Path(event.src_path))

    def on_moved(self, event):
        if not event.is_directory:
            self._handle(Path(event.dest_path))


# ---------------------------------------------------------------------------
# Step 4: Plans watchdog → watches for user checkbox tick → Approved/ or Pending_Approval/
# ---------------------------------------------------------------------------

def _check_plan_decision(path: Path, vault: VaultIO):
    """
    Called when a Plans/ file is modified.
    Reads the file and routes based on which checkbox the user ticked:
      - [x] ✅ Approve  → Approved/  (triggers execution)
      - [x] ⏸ Pending Approval → Pending_Approval/
    """
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:
        log.error("[Plans] Cannot read %s: %s", path.name, exc)
        return

    approved = (
        "- [x] ✅ Approve" in content
        or "- [X] ✅ Approve" in content
        or "- [x] Approve" in content
        or "- [X] Approve" in content
    )
    pending = (
        "- [x] ⏸ Pending Approval" in content
        or "- [X] ⏸ Pending Approval" in content
        or "- [x] Pending Approval" in content
        or "- [X] Pending Approval" in content
    )

    if approved:
        try:
            vault.move_to_approved(f"Plans/{path.name}")
            log.info("[Plans] %s → Approved/ ← executing now", path.name)
            vault.log_action(
                action_type="plan_approved_by_user", actor="user",
                target=path.name, approval_status="approved", result="success",
            )
            vault.update_dashboard(
                recent_activity=f"- {datetime.now():%Y-%m-%d %H:%M} — Approved by user: `{path.name}`"
            )
        except Exception as exc:
            log.error("[Plans] Failed to move %s to Approved: %s", path.name, exc)

    elif pending:
        try:
            vault.move_to_pending_approval(f"Plans/{path.name}")
            log.info("[Plans] %s → Pending_Approval/ ← held for later", path.name)
            vault.log_action(
                action_type="plan_deferred_by_user", actor="user",
                target=path.name, approval_status="pending", result="success",
            )
            vault.update_dashboard(
                recent_activity=f"- {datetime.now():%Y-%m-%d %H:%M} — Deferred: `{path.name}`"
            )
        except Exception as exc:
            log.error("[Plans] Failed to move %s to Pending_Approval: %s", path.name, exc)


class PlansHandler(FileSystemEventHandler):
    """Watch Plans/ for user checkbox modifications and route accordingly."""

    def __init__(self, vault: VaultIO):
        self.vault = vault
        self._debounce: dict = {}  # path → last-processed timestamp
        self._lock = threading.Lock()

    def _handle_modified(self, path: Path):
        if not (path.suffix.lower() == ".md" and path.name.startswith("PLAN_")):
            return
        now = time.time()
        with self._lock:
            last = self._debounce.get(str(path), 0)
            if now - last < 2.0:  # 2-second debounce — watchdog fires multiple events per save
                return
            self._debounce[str(path)] = now
        threading.Thread(
            target=_check_plan_decision, args=(path, self.vault), daemon=True
        ).start()

    def on_modified(self, event):
        if not event.is_directory:
            self._handle_modified(Path(event.src_path))


# ---------------------------------------------------------------------------
# Step 5: Approved watchdog → execute plan → send email → Done
# ---------------------------------------------------------------------------

class ApprovedHandler(FileSystemEventHandler):
    def __init__(self, vault: VaultIO):
        self.vault = vault

    def _handle(self, path: Path):
        if path.name.startswith("PLAN_") and path.suffix.lower() == ".md":
            time.sleep(1)  # ensure file is fully written
            threading.Thread(
                target=self._execute, args=(path,), daemon=True
            ).start()

    def on_created(self, event):
        if not event.is_directory:
            self._handle(Path(event.src_path))

    def on_moved(self, event):
        if not event.is_directory:
            self._handle(Path(event.dest_path))

    def _execute(self, plan_path: Path):
        from approval_watcher import process_approved_plan
        log.info("[Execute] Approved plan detected: %s", plan_path.name)
        process_approved_plan(self.vault, plan_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    vault = VaultIO()

    # Ensure all folders exist
    for folder in ["Inbox", "Needs_Action", "Plans", "Pending_Approval", "Approved", "Done"]:
        (vault.root / folder).mkdir(parents=True, exist_ok=True)

    log.info("=" * 60)
    log.info("AI Vault Pipeline starting...")
    log.info("=" * 60)

    observer = Observer()

    # Watch Inbox/ → triage
    observer.schedule(InboxHandler(vault), str(vault.root / "Inbox"), recursive=False)
    log.info("[Inbox]      Watching Vault/Inbox/ → auto-triage on new email")

    # Watch Needs_Action/ → plan
    observer.schedule(NeedsActionHandler(vault), str(vault.root / "Needs_Action"), recursive=False)
    log.info("[NeedsAction] Watching Vault/Needs_Action/ → auto-plan on new item")

    # Watch Plans/ → detect user checkbox tick → route to Approved/ or Pending_Approval/
    observer.schedule(PlansHandler(vault), str(vault.root / "Plans"), recursive=False)
    log.info("[Plans]      Watching Vault/Plans/ → routes on checkbox tick (✅ Approve / ⏸ Pending)")

    # Watch Approved/ → execute
    observer.schedule(ApprovedHandler(vault), str(vault.root / "Approved"), recursive=False)
    log.info("[Approved]   Watching Vault/Approved/ → auto-execute on approval")

    observer.start()

    # Gmail poller in background thread
    gmail_thread = threading.Thread(
        target=_gmail_poll_loop, args=(120,), daemon=True, name="gmail-poller"
    )
    gmail_thread.start()
    log.info("[Gmail]      Polling Gmail every 2 min for unread important emails")

    log.info("")
    log.info("Pipeline ready. Your only job:")
    log.info("  1. Open a PLAN_*.md in Vault/Plans/ (Obsidian)")
    log.info("  2. Edit if needed, then tick one checkbox:")
    log.info("       - [x] ✅ Approve  → executes immediately (sends email)")
    log.info("       - [x] ⏸ Pending Approval  → holds in Pending_Approval/ for later")
    log.info("  3. Save the file — pipeline routes it automatically.")
    log.info("")
    log.info("Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Shutting down...")
        observer.stop()

    observer.join()
    log.info("Pipeline stopped.")


if __name__ == "__main__":
    main()
