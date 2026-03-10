"""
watcher.py – File-system Watcher for the Obsidian Vault Inbox.

Monitors Vault/Inbox/ for new .md files and automatically invokes
the vault-triage Agent Skill via Claude Code CLI.

Requirements:
    pip install watchdog

Usage:
    python watcher.py

The watcher will:
  1. Detect any new .md file dropped into Vault/Inbox/
  2. Log the event to watcher.log
  3. Invoke: claude --skill vault-triage --input <file_path>
     (or run the triage logic directly via vault_io if CLI not available)
"""

import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from watchdog.events import FileSystemEventHandler, FileCreatedEvent
from watchdog.observers import Observer

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VAULT_ROOT = Path(__file__).parent / "Vault"
INBOX_DIR = VAULT_ROOT / "Inbox"
LOG_FILE = Path(__file__).parent / "watcher.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("vault-watcher")


# ---------------------------------------------------------------------------
# Event handler
# ---------------------------------------------------------------------------

class InboxHandler(FileSystemEventHandler):
    """Handles file creation events inside Vault/Inbox."""

    def on_created(self, event: FileCreatedEvent):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() != ".md":
            log.debug("Ignoring non-.md file: %s", path.name)
            return

        log.info("New inbox item detected: %s", path.name)
        self._handle_new_item(path)

    def _handle_new_item(self, path: Path):
        """Trigger the vault-triage agent skill for the new file."""
        rel_path = path.relative_to(VAULT_ROOT)
        log.info("Triggering triage for: %s", rel_path)

        # Try to invoke Claude Code CLI with vault-triage skill
        try:
            import os
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            result = subprocess.run(
                [
                    "claude",
                    "--print",
                    f"Use the vault-triage skill to process this new inbox item: {rel_path}",
                ],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(Path(__file__).parent),
                env=env,
            )
            if result.returncode == 0:
                log.info("Triage complete for %s", path.name)
                log.debug("Claude output:\n%s", result.stdout)
            else:
                log.warning(
                    "Claude exited with code %d for %s\nstderr: %s",
                    result.returncode, path.name, result.stderr,
                )
                # Fallback: run basic triage directly
                self._fallback_triage(path, rel_path)

        except FileNotFoundError:
            log.warning("'claude' CLI not found — running fallback triage")
            self._fallback_triage(path, rel_path)
        except subprocess.TimeoutExpired:
            log.error("Triage timed out for %s", path.name)

    def _fallback_triage(self, path: Path, rel_path: Path):
        """
        Minimal fallback: stamp the file with received frontmatter and
        move it to Needs_Action so nothing is lost.
        """
        try:
            from vault_io import VaultIO
            v = VaultIO()
            dest = v.move_to_needs_action(
                str(rel_path),
                summary="Auto-triaged by watcher fallback — review needed",
                priority="medium",
            )
            v.update_dashboard(
                recent_activity=f"- {datetime.now():%Y-%m-%d %H:%M} — Fallback triage: `{path.name}` → Needs_Action"
            )
            log.info("Fallback triage: moved %s → %s", path.name, dest)
        except Exception as exc:
            log.error("Fallback triage failed for %s: %s", path.name, exc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Vault Watcher started.")
    log.info("Monitoring: %s", INBOX_DIR.resolve())

    handler = InboxHandler()
    observer = Observer()
    observer.schedule(handler, str(INBOX_DIR), recursive=False)
    observer.start()

    log.info("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Stopping watcher...")
        observer.stop()
    observer.join()
    log.info("Watcher stopped.")


if __name__ == "__main__":
    main()