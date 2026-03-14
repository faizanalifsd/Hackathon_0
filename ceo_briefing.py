"""
ceo_briefing.py – Weekly Business Audit + Monday Morning CEO Briefing (Gold Tier Feature 4)

Runs every Sunday at 10 PM via Windows Task Scheduler.
Scans all Vault activity from the past 7 days and emails a structured briefing
to the configured CEO_EMAIL address.

Usage:
    uv run python ceo_briefing.py              # generate + email briefing now
    uv run python ceo_briefing.py --dry-run    # print briefing without sending

Setup:
    Add to .env:
        CEO_EMAIL=your@email.com
    Ensure Gmail OAuth is authorized (credentials.json / token.json present).
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
VAULT_ROOT = BASE_DIR / "Vault"
LOG_FILE = BASE_DIR / "ceo_briefing.log"

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
log = logging.getLogger("ceo-briefing")


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def _count_files_in(folder: Path, days: int = 7) -> list[dict]:
    """Return list of {name, modified} for .md files modified in last N days."""
    if not folder.exists():
        return []
    cutoff = datetime.now() - timedelta(days=days)
    results = []
    for f in folder.glob("*.md"):
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime >= cutoff:
            results.append({"name": f.name, "modified": mtime.strftime("%Y-%m-%d %H:%M")})
    return sorted(results, key=lambda x: x["modified"], reverse=True)


def _read_recent_logs(days: int = 7) -> list[str]:
    """Read recent audit log entries from Vault/Logs/."""
    logs_dir = VAULT_ROOT / "Logs"
    if not logs_dir.exists():
        return []
    cutoff = datetime.now() - timedelta(days=days)
    lines = []
    for f in sorted(logs_dir.glob("*.md"), reverse=True)[:14]:  # last 2 weeks of files
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime >= cutoff:
            try:
                text = f.read_text(encoding="utf-8")
                for line in text.splitlines():
                    if line.strip() and not line.startswith("---") and not line.startswith("#"):
                        lines.append(line.strip())
            except Exception:
                pass
    return lines[-50:]  # last 50 log entries


def _read_needs_action_summaries() -> list[str]:
    """Return summaries of currently open Needs_Action items."""
    folder = VAULT_ROOT / "Needs_Action"
    if not folder.exists():
        return []
    summaries = []
    for f in sorted(folder.glob("*.md")):
        if f.name.startswith("CEO_BRIEFING_"):
            continue
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("summary:"):
                summaries.append(f"- {f.name}: {line.split(':', 1)[1].strip()}")
                break
        else:
            summaries.append(f"- {f.name}")
    return summaries


def collect_weekly_data() -> dict:
    """Collect all data needed for the CEO briefing."""
    done = _count_files_in(VAULT_ROOT / "Done")
    inbox = _count_files_in(VAULT_ROOT / "Inbox")
    pending = _count_files_in(VAULT_ROOT / "Pending_Approval")
    approved = _count_files_in(VAULT_ROOT / "Approved")
    log_entries = _read_recent_logs()
    open_items = _read_needs_action_summaries()

    # Count by category
    emails_handled = sum(1 for f in done if not f["name"].startswith(("PLAN_", "REPORT_", "whatsapp_", "LINKEDIN_", "FACEBOOK_", "INSTAGRAM_")))
    wa_handled = sum(1 for f in done if f["name"].startswith("whatsapp_") or "whatsapp" in f["name"].lower())
    plans_executed = sum(1 for f in done if f["name"].startswith("PLAN_"))
    social_posts = sum(1 for f in done if any(f["name"].startswith(p) for p in ("LINKEDIN_POST_", "FACEBOOK_POST_", "INSTAGRAM_POST_")))

    return {
        "week_start": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
        "week_end": datetime.now().strftime("%Y-%m-%d"),
        "done_count": len(done),
        "inbox_count": len(inbox),
        "pending_count": len(pending),
        "open_needs_action": len(open_items),
        "emails_handled": emails_handled,
        "wa_handled": wa_handled,
        "plans_executed": plans_executed,
        "social_posts": social_posts,
        "open_item_summaries": open_items,
        "recent_log_entries": log_entries[-20:],
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_briefing_text(data: dict) -> str:
    """Generate the CEO briefing markdown/email text from collected data."""
    from router import route_completion

    open_items_text = "\n".join(data["open_item_summaries"]) if data["open_item_summaries"] else "_None_"
    log_text = "\n".join(data["recent_log_entries"]) if data["recent_log_entries"] else "_No log entries_"

    system = """You are an AI Chief of Staff writing the Monday Morning CEO Briefing email.
Be concise, executive-level, and structured. Use numbers. Flag risks clearly.
Output ONLY the email body (no subject line, no "Dear", just the content).
Max 300 words. Use bullet points."""

    user = f"""Weekly Activity Report ({data['week_start']} to {data['week_end']}):

COMPLETED THIS WEEK:
- Total items resolved: {data['done_count']}
- Emails handled: {data['emails_handled']}
- WhatsApp conversations resolved: {data['wa_handled']}
- Plans executed: {data['plans_executed']}
- Social media posts published: {data['social_posts']}

CURRENT STATUS:
- Open items in Needs_Action: {data['open_needs_action']}
- Items pending approval: {data['pending_count']}
- New inbox items: {data['inbox_count']}

OPEN ITEMS REQUIRING ATTENTION:
{open_items_text}

RECENT SYSTEM ACTIVITY:
{log_text}

Write a concise CEO briefing covering: week summary, key wins, open risks/blockers, and recommended actions."""

    result = route_completion(system, user)
    return result or _fallback_briefing(data)


def _fallback_briefing(data: dict) -> str:
    open_items = "\n".join(data["open_item_summaries"]) if data["open_item_summaries"] else "None"
    return f"""**Weekly AI Employee Report — {data['week_start']} to {data['week_end']}**

**Activity Summary:**
- Items completed: {data['done_count']}
- Emails handled: {data['emails_handled']}
- WhatsApp conversations resolved: {data['wa_handled']}
- Plans executed: {data['plans_executed']}
- Social posts published: {data['social_posts']}

**Current Backlog:**
- Open Needs_Action items: {data['open_needs_action']}
- Awaiting your approval: {data['pending_count']}

**Open Items:**
{open_items}

**Action Required:** Review Vault/Needs_Action/ and Vault/Pending_Approval/ for items requiring attention.
"""


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def send_ceo_briefing(briefing_text: str, data: dict, dry_run: bool = False) -> bool:
    """Email the briefing to CEO_EMAIL."""
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")

    ceo_email = os.environ.get("CEO_EMAIL", "")
    if not ceo_email:
        log.warning("CEO_EMAIL not set in .env — saving to Vault/Needs_Action/ instead")
        _save_briefing_to_vault(briefing_text, data)
        return True

    subject = f"[AI Employee] Monday Briefing — {data['week_end']}"

    if dry_run:
        print(f"\n{'='*60}")
        print(f"TO: {ceo_email}")
        print(f"SUBJECT: {subject}")
        print(f"{'='*60}")
        print(briefing_text)
        print(f"{'='*60}\n")
        return True

    try:
        from gmail_mcp_server import send_email
        result = send_email(ceo_email, subject, briefing_text)
        log.info("✅ CEO Briefing sent to %s (ID: %s)", ceo_email, result.get("message_id", "?"))
        return True
    except Exception as exc:
        log.error("Failed to send CEO Briefing email: %s", exc)
        _save_briefing_to_vault(briefing_text, data)
        return False


def _save_briefing_to_vault(briefing_text: str, data: dict) -> None:
    """Fallback: save briefing as a Needs_Action note."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"CEO_BRIEFING_{ts}.md"
    path = VAULT_ROOT / "Needs_Action" / fname
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""---
source: ceo_briefing
received: {datetime.now().strftime("%Y-%m-%d %H:%M")}
status: needs_action
priority: medium
tags: [briefing, weekly]
summary: "Weekly AI Employee briefing — {data['week_start']} to {data['week_end']}"
---

# Monday Morning CEO Briefing

{briefing_text}
"""
    path.write_text(content, encoding="utf-8")
    log.info("Briefing saved to Vault/Needs_Action/%s", fname)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Weekly CEO Briefing Generator")
    parser.add_argument("--dry-run", action="store_true",
                        help="Generate briefing and print it without sending email")
    args = parser.parse_args()

    log.info("Collecting weekly vault data...")
    data = collect_weekly_data()

    log.info("Generating briefing with AI router...")
    briefing_text = generate_briefing_text(data)

    success = send_ceo_briefing(briefing_text, data, dry_run=args.dry_run)
    if success:
        log.info("CEO Briefing complete.")
    else:
        log.error("CEO Briefing delivery failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
