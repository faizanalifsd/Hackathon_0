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


def _detect_source(plan_name: str, plan_content: str) -> str:
    """Return 'whatsapp' if the plan originated from a WhatsApp message, else 'email'."""
    # Plan filename contains 'whatsapp' when it came from whatsapp_watcher
    if "whatsapp" in plan_name.lower():
        return "whatsapp"
    # Fallback: check plan content for source field
    for line in plan_content.splitlines():
        if "source: whatsapp" in line.lower():
            return "whatsapp"
    return "email"



def _send_whatsapp_reply(chat_name: str, message: str) -> bool:
    """
    Send a WhatsApp reply via the already-running watcher's browser (shared session).
    Enqueues the message and waits for the watcher loop to deliver it.
    """
    try:
        from whatsapp_watcher import send_whatsapp_message
        log.info("[WhatsApp] Queuing reply to '%s'...", chat_name)
        success = send_whatsapp_message(chat_name, message, timeout=90)
        if success:
            log.info("[WhatsApp] ✅ Reply sent to '%s'", chat_name)
        else:
            log.error("[WhatsApp] Reply to '%s' failed or timed out.", chat_name)
        return success
    except Exception as exc:
        log.error("[WhatsApp] Send reply failed: %s", exc)
        return False


def _get_original_task_chat(plan_name: str) -> str | None:
    """
    Given PLAN_whatsapp_*.md, find the original task file and return its `chat:` frontmatter value.
    Looks in Needs_Action/, Inbox/, and Done/.
    """
    task_name = plan_name.removeprefix("PLAN_")
    for folder in ["Needs_Action", "Inbox", "Done"]:
        task_path = VAULT_ROOT / folder / task_name
        if task_path.exists():
            for line in task_path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("chat:"):
                    return line.split(":", 1)[1].strip()
    return None


def _extract_reply_from_plan(plan_content: str) -> str:
    """
    Extract the exact reply message from the '## WhatsApp Reply' section of the plan.
    The user may have edited this message before approving — use it as-is.
    """
    lines = plan_content.splitlines()
    in_reply_section = False
    reply_lines = []

    for line in lines:
        if line.strip() == "## WhatsApp Reply":
            in_reply_section = True
            continue
        if in_reply_section:
            # Stop at next section header or decision block
            if line.startswith("##") or line.startswith("---"):
                break
            reply_lines.append(line)

    return "\n".join(reply_lines).strip()


def _execute_whatsapp_plan(plan_name: str, plan_content: str) -> tuple[bool, str]:
    """Execute a WhatsApp plan — read exact chat name from original task, generate reply, send."""
    # Step 1: Get exact chat name from the original task file (not Groq guess)
    chat_name = _get_original_task_chat(plan_name)
    if not chat_name:
        log.error("[Execute] Could not find original task file for %s", plan_name)
        return False, (
            "## Execution Report\n\n"
            f"Could not find original task file for `{plan_name}` to get chat name.\n\n"
            "**Status: BLOCKED**"
        )

    log.info("[Execute] WhatsApp plan — replying to chat: '%s'", chat_name)

    # Step 2: Read the exact reply message the user approved (from ## WhatsApp Reply section)
    message = _extract_reply_from_plan(plan_content)
    if not message:
        return False, (
            "## Execution Report\n\n"
            "No '## WhatsApp Reply' section found in plan.\n\n"
            "**Status: BLOCKED**"
        )

    log.info("[Execute] Sending exact reply from plan: %s", message[:80])

    # Step 3: Send via WhatsApp
    success = _send_whatsapp_reply(chat_name, message)
    if success:
        return True, (
            f"## Execution Report\n\n"
            f"| Step | Result |\n|------|--------|\n"
            f"| WhatsApp reply to '{chat_name}' | Sent |\n"
            f"| Message | {message[:100]} |\n"
            f"| Move plan → `Vault/Done/` | Done |\n\n"
            f"**Status: COMPLETE**"
        )
    else:
        return False, (
            f"## Execution Report\n\n"
            f"Failed to send WhatsApp reply to '{chat_name}'.\n\n"
            f"**Status: BLOCKED**"
        )


def _extract_email_fields(plan_content: str) -> dict | None:
    """
    Extract email fields (to, subject, body) from the '## Email Reply' section of a plan.
    The user may have edited this section before approving — use it as-is.
    Returns dict or None if no email reply section found.
    """
    lines = plan_content.splitlines()
    in_section = False
    section_lines = []

    for line in lines:
        if line.strip() == "## Email Reply":
            in_section = True
            continue
        if in_section:
            if line.startswith("## ") or line.strip() == "---":
                break
            section_lines.append(line)

    if not section_lines:
        return None

    try:
        to = subject = ""
        body_lines = []
        in_body = False
        for line in section_lines:
            stripped = line.strip()
            if stripped.startswith("TO:"):
                to = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("SUBJECT:"):
                subject = stripped.split(":", 1)[1].strip()
            elif stripped == "BODY:":
                in_body = True
            elif stripped == "END":
                in_body = False
            elif in_body:
                body_lines.append(line)
        body = "\n".join(body_lines).strip()
        if subject and body:
            return {"to": to, "subject": subject, "body": body}
    except Exception as exc:
        log.error("Email extraction from plan failed: %s", exc)
    return None


def _get_original_task_sender(plan_name: str) -> str | None:
    """
    Read the sender's email from the original task file.
    Checks `from:` frontmatter first, then scans the body for email addresses.
    Returns a valid email address (containing @) or None.
    """
    import re
    EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")

    task_name = plan_name.removeprefix("PLAN_")
    for folder in ["Needs_Action", "Inbox", "Done"]:
        task_path = VAULT_ROOT / folder / task_name
        if not task_path.exists():
            continue
        content = task_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip().lower()
            # Check from: and from_name: frontmatter fields
            if stripped.startswith("from:") or stripped.startswith("from_name:"):
                raw = line.split(":", 1)[1].strip()
                # Prefer email in angle brackets
                match = re.search(r"<([^>]+@[^>]+)>", raw)
                if match:
                    return match.group(1).strip()
                # Direct email with @ sign
                match = EMAIL_RE.search(raw)
                if match:
                    return match.group(0)
        # Last resort: scan entire file for first email address
        match = EMAIL_RE.search(content)
        if match:
            found = match.group(0)
            log.info("[Sender] Extracted email from body: %s", found)
            return found
    return None


def _execute_plan(plan_name: str, plan_content: str) -> tuple[bool, str]:
    """
    Execute an approved plan — routes to WhatsApp reply or email based on source.
    Returns (success, report_markdown).
    """
    source = _detect_source(plan_name, plan_content)
    if source == "whatsapp":
        return _execute_whatsapp_plan(plan_name, plan_content)

    # Email path
    from gmail_mcp_server import send_email

    log.info("[Execute] Reading email reply from plan...")
    fields = _extract_email_fields(plan_content)

    if not fields:
        return True, (
            "## Execution Report\n\n"
            "No outgoing email found in plan.\n\n"
            "**Status: COMPLETE**"
        )

    # Always override TO with the actual sender from the original task file
    real_sender = _get_original_task_sender(plan_name)
    if real_sender:
        if fields["to"] != real_sender:
            log.info("[Execute] Correcting TO: plan said '%s' → real sender '%s'",
                     fields["to"], real_sender)
        fields["to"] = real_sender
    else:
        log.warning("[Execute] Could not resolve real sender — using plan's TO: %s", fields["to"])

    # Safety gate: block send if TO doesn't look like a valid email
    if "@" not in fields.get("to", ""):
        log.error("[Execute] TO '%s' is not a valid email address — aborting send.", fields["to"])
        return False, (
            f"## Execution Report\n\n"
            f"Could not determine a valid recipient email address (got: `{fields['to']}`).\n\n"
            f"**Action Required:** Edit the `## Email Reply` section in the plan, "
            f"set `TO:` to the correct email address, and move to `Approved/` again.\n\n"
            f"**Status: BLOCKED**"
        )

    log.info("[Execute] Sending to %s — %s", fields["to"], fields["subject"])
    try:
        result = send_email(fields["to"], fields["subject"], fields["body"])
        msg_id = result.get("message_id", "unknown")
        log.info("[Execute] ✅ Email sent — Gmail ID: %s", msg_id)
        return True, (
            f"## Execution Report\n\n"
            f"| Step | Result |\n|------|--------|\n"
            f"| Send reply to {fields['to']} | Sent (ID: `{msg_id}`) |\n"
            f"| Subject | {fields['subject']} |\n"
            f"| Move plan → `Vault/Done/` | Done |\n\n"
            f"**Status: COMPLETE**"
        )
    except Exception as exc:
        log.error("[Execute] Send failed: %s", exc)
        return False, f"## Execution Report\n\nFailed to send email: {exc}\n\n**Status: BLOCKED**"


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

    # Execute: Groq extracts email fields → Gmail API sends directly
    success, output = _execute_plan(plan_name, plan_content)
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


def process_approved_social_post(vault: VaultIO, post_path: Path) -> None:
    """Process a single approved social media post file (Facebook/Instagram/LinkedIn)."""
    name = post_path.name
    log.info("Processing approved social post: %s", name)
    try:
        if name.startswith("FACEBOOK_POST_"):
            from facebook_mcp_server import publish_approved_facebook_posts
            count = publish_approved_facebook_posts()
            log.info("[Facebook] Published %d post(s).", count)
        elif name.startswith("INSTAGRAM_POST_"):
            from instagram_mcp_server import publish_approved_instagram_posts
            count = publish_approved_instagram_posts()
            log.info("[Instagram] Published %d post(s).", count)
        elif name.startswith("LINKEDIN_POST_"):
            from vault_io import VaultIO as _VaultIO
            from linkedin_poster import publish_approved_posts
            count = publish_approved_posts(vault)
            log.info("[LinkedIn] Published %d post(s).", count)
        vault.log_action(
            action_type="social_post_published",
            actor="approval_watcher",
            target=name,
            approval_status="approved",
            result="success",
        )
    except Exception as exc:
        log.error("Social post publish failed for %s: %s", name, exc)
        vault.log_action(
            action_type="social_post_published",
            actor="approval_watcher",
            target=name,
            approval_status="approved",
            result="failed",
            details=str(exc),
        )


def process_all_approved(vault: VaultIO) -> int:
    """Process all PLAN_*.md and social post files currently in Approved/. Returns count processed."""
    APPROVED_DIR.mkdir(parents=True, exist_ok=True)

    # Plans (WhatsApp / email)
    plans = list(APPROVED_DIR.glob("PLAN_*.md"))
    for plan_path in plans:
        process_approved_plan(vault, plan_path)

    # Social media posts
    social_patterns = ["FACEBOOK_POST_*.md", "INSTAGRAM_POST_*.md", "LINKEDIN_POST_*.md"]
    social_posts = []
    for pat in social_patterns:
        social_posts.extend(APPROVED_DIR.glob(pat))
    for post_path in social_posts:
        process_approved_social_post(vault, post_path)

    total = len(plans) + len(social_posts)
    if total == 0:
        log.info("No approved items to process.")
    return total


# ---------------------------------------------------------------------------
# Watchdog handler (daemon mode)
# ---------------------------------------------------------------------------

class ApprovedHandler(FileSystemEventHandler):
    def __init__(self, vault: VaultIO):
        self.vault = vault

    def _handle(self, path: Path):
        if path.suffix.lower() != ".md" or path.parent != APPROVED_DIR:
            return
        name = path.name
        time.sleep(1)  # ensure file is fully written
        if name.startswith("PLAN_"):
            log.info("New approved plan detected: %s", name)
            process_approved_plan(self.vault, path)
        elif any(name.startswith(p) for p in ("FACEBOOK_POST_", "INSTAGRAM_POST_", "LINKEDIN_POST_")):
            log.info("New approved social post detected: %s", name)
            process_approved_social_post(self.vault, path)

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
