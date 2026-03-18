"""
proactive_engine.py – Proactive Intelligence Engine (Platinum Tier Feature 3)

Instead of only reacting to incoming messages, this engine proactively scans
the vault and generates suggestions:
  - Items in Needs_Action/ aging past 48 hours (unanswered)
  - Emails sent but no follow-up detected after 3 days
  - Recurring task patterns (LLM-detected from logs)
  - Weekly content gap (no LinkedIn post this week?)

Suggestions are written as PROACTIVE_*.md files to Vault/Needs_Action/.
The existing NeedsActionHandler in main.py picks them up automatically.

Usage:
    uv run python proactive_engine.py           # run one scan
    uv run python proactive_engine.py --daemon  # run every 6 hours

Schedule:
    Windows Task Scheduler: every 6 hours via schedule_setup.py
"""

import json
import logging
import os
import sys
import time
import io
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
VAULT_ROOT = BASE_DIR / "Vault"
LOG_FILE = BASE_DIR / "proactive_engine.log"

AGING_THRESHOLD_HOURS = 48
FOLLOWUP_THRESHOLD_DAYS = 3
SCAN_INTERVAL_HOURS = 6

_console = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(_console),
    ],
)
log = logging.getLogger("proactive-engine")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_suggestion(suggestion_type: str, title: str, body: str) -> Path:
    """Write a proactive suggestion to Vault/Needs_Action/."""
    from vault_io import VaultIO
    vault = VaultIO()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_title = "".join(c if c.isalnum() or c in "_-" else "_" for c in title[:40])
    filename = f"PROACTIVE_{suggestion_type}_{ts}_{safe_title}.md"

    content = f"""---
source: proactive_engine
received: {datetime.now().strftime("%Y-%m-%d %H:%M")}
status: needs_action
priority: low
type: {suggestion_type}
tags: [proactive, ai_suggestion]
summary: "{title}"
---

# Proactive Suggestion: {title}

{body}

---
## Your Decision

- [ ] ✅ Approve — act on this suggestion
- [ ] ⏸ Pending Approval — hold for later
"""
    dest = vault.needs_action / filename
    dest.write_text(content, encoding="utf-8")
    vault.log_action(
        action_type="proactive_suggestion",
        actor="proactive_engine",
        target=filename,
        approval_status="pending",
        result="success",
        details=title,
    )
    log.info("[Proactive] Suggestion written: %s", filename)
    return dest


# ---------------------------------------------------------------------------
# Check 1: Aging items in Needs_Action
# ---------------------------------------------------------------------------

def _check_aging_items() -> int:
    """Flag Needs_Action items older than AGING_THRESHOLD_HOURS."""
    folder = VAULT_ROOT / "Needs_Action"
    if not folder.exists():
        return 0

    cutoff = datetime.now() - timedelta(hours=AGING_THRESHOLD_HOURS)
    aging = []
    for f in folder.glob("*.md"):
        if f.name.startswith(("PROACTIVE_", "CEO_BRIEFING_", "BLOCKED_")):
            continue
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime < cutoff:
            age_h = int((datetime.now() - mtime).total_seconds() / 3600)
            aging.append((f.name, age_h))

    if not aging:
        return 0

    items_list = "\n".join(f"- `{name}` (waiting {hrs}h)" for name, hrs in aging[:10])
    body = f"""## Aging Items Detected

The following items in `Needs_Action/` have been waiting over {AGING_THRESHOLD_HOURS} hours
without a plan being generated or action taken:

{items_list}

## Suggested Action

Review each item and either:
1. Generate a plan manually (open the file, assess, create a plan)
2. Mark as done if no action is needed
3. Delete if no longer relevant

These items may be blocking important communication or tasks.
"""
    _write_suggestion(
        "aging_items",
        f"{len(aging)} item(s) aging in Needs_Action",
        body,
    )
    return 1


# ---------------------------------------------------------------------------
# Check 2: Emails sent — follow-up needed?
# ---------------------------------------------------------------------------

def _check_pending_followups() -> int:
    """Suggest follow-ups on emails sent 3+ days ago with no reply logged."""
    logs_dir = VAULT_ROOT / "Logs"
    if not logs_dir.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=FOLLOWUP_THRESHOLD_DAYS)
    candidates = []

    for log_file in sorted(logs_dir.glob("????-??-??.json"), reverse=True)[:14]:
        try:
            file_date = datetime.strptime(log_file.stem, "%Y-%m-%d")
        except ValueError:
            continue
        if file_date > cutoff:
            continue  # too recent

        try:
            entries = json.loads(log_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        for entry in entries:
            action = entry.get("action_type", "")
            target = entry.get("target", "")
            result = entry.get("result", "")
            ts_str = entry.get("timestamp", "")

            if action == "plan_executed" and result == "success" and "email" in target.lower():
                try:
                    sent_dt = datetime.fromisoformat(ts_str[:19])
                    if sent_dt < cutoff:
                        candidates.append({"target": target, "sent": ts_str[:10]})
                except Exception:
                    pass

    if not candidates:
        return 0

    items_list = "\n".join(
        f"- `{c['target']}` (sent {c['sent']})" for c in candidates[:5]
    )
    body = f"""## Emails Sent — No Follow-up Detected

The following emails were sent {FOLLOWUP_THRESHOLD_DAYS}+ days ago.
No follow-up action has been logged. Consider checking if a reply was received:

{items_list}

## Suggested Action

1. Check your Gmail inbox for replies
2. If no reply → send a polite follow-up
3. If resolved → mark the original task as done
"""
    _write_suggestion(
        "followup_needed",
        f"{len(candidates)} email(s) may need follow-up",
        body,
    )
    return 1


# ---------------------------------------------------------------------------
# Check 3: Recurring patterns in logs
# ---------------------------------------------------------------------------

def _check_recurring_patterns() -> int:
    """Analyze 30 days of logs for recurring tasks and suggest automation."""
    logs_dir = VAULT_ROOT / "Logs"
    if not logs_dir.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=30)
    all_targets: list[str] = []

    for log_file in sorted(logs_dir.glob("????-??-??.json"), reverse=True)[:30]:
        try:
            file_date = datetime.strptime(log_file.stem, "%Y-%m-%d")
            if file_date < cutoff:
                continue
            entries = json.loads(log_file.read_text(encoding="utf-8"))
            for entry in entries:
                if entry.get("result") == "success":
                    all_targets.append(entry.get("target", ""))
        except Exception:
            continue

    if len(all_targets) < 5:
        return 0

    # Simple frequency analysis — find targets appearing 3+ times
    from collections import Counter
    # Normalize: strip timestamps from filenames
    import re
    normalized = []
    for t in all_targets:
        # Remove timestamps like _20260315_123456
        clean = re.sub(r"_\d{8}_\d{6}", "", t)
        clean = re.sub(r"_\d{8}", "", clean)
        normalized.append(clean)

    freq = Counter(normalized).most_common(5)
    recurring = [(name, count) for name, count in freq if count >= 3 and name.strip()]

    if not recurring:
        return 0

    # Ask LLM for insight
    try:
        from router import route_completion
        targets_text = "\n".join(f"- {name} (×{count})" for name, count in recurring)
        system = (
            "You are an AI assistant analyzing task patterns for a business owner. "
            "Based on recurring tasks, suggest 1-2 automation opportunities. "
            "Be concise and practical. Max 100 words."
        )
        user = f"These tasks recurred in the past 30 days:\n{targets_text}\n\nWhat automation opportunities do you see?"
        insight = route_completion(system, user, force_model="groq") or ""
    except Exception:
        insight = ""

    items_list = "\n".join(f"- `{name}` — {count} times" for name, count in recurring)
    body = f"""## Recurring Task Patterns Detected

These tasks have occurred 3+ times in the past 30 days:

{items_list}

## AI Analysis

{insight or "_Analysis unavailable — check LLM API keys._"}

## Suggested Action

Consider automating these recurring tasks by:
1. Creating a template plan (PLAN_template_*.md) for each
2. Setting up a scheduled trigger in schedule_setup.py
3. Adding a keyword rule to the watcher scripts
"""
    _write_suggestion(
        "automation_opportunity",
        f"Automation opportunity: {recurring[0][0][:40]}",
        body,
    )
    return 1


# ---------------------------------------------------------------------------
# Check 4: Weekly content gap
# ---------------------------------------------------------------------------

def _check_content_gap() -> int:
    """Suggest posting LinkedIn content if no post was made this week."""
    done_dir = VAULT_ROOT / "Done"
    if not done_dir.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=7)
    linkedin_posts = [
        f for f in done_dir.glob("*.md")
        if ("linkedin" in f.name.lower() or "LINKEDIN" in f.name)
        and datetime.fromtimestamp(f.stat().st_mtime) >= cutoff
    ]

    if linkedin_posts:
        return 0  # Already posted this week

    body = """## No LinkedIn Content This Week

No LinkedIn posts have been published in the past 7 days.
Consistent content publishing improves professional visibility and engagement.

## Suggested Action

Run the social scheduler to generate a LinkedIn post draft:

```
uv run python social_scheduler.py --linkedin
```

Or ask the AI to generate one based on your recent vault activity.
After generation, review in `Vault/Pending_Approval/` and approve.
"""
    _write_suggestion(
        "content_gap",
        "No LinkedIn content published this week",
        body,
    )
    return 1


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------

def run_proactive_scan() -> int:
    """Run all checks and write suggestions. Returns count of suggestions written."""
    from error_recovery import ErrorRecovery
    log.info("[Proactive] Starting scan...")
    count = 0

    with ErrorRecovery("proactive_engine", "Aging item check"):
        count += _check_aging_items()

    with ErrorRecovery("proactive_engine", "Follow-up check"):
        count += _check_pending_followups()

    with ErrorRecovery("proactive_engine", "Recurring pattern analysis"):
        count += _check_recurring_patterns()

    with ErrorRecovery("proactive_engine", "Content gap check"):
        count += _check_content_gap()

    log.info("[Proactive] Scan complete. %d suggestion(s) written.", count)
    return count


# ---------------------------------------------------------------------------
# Thread target for main.py
# ---------------------------------------------------------------------------

def _proactive_poll_loop():
    """Daemon thread target for main.py — runs every SCAN_INTERVAL_HOURS."""
    log.info("[Proactive] Engine starting (every %dh)...", SCAN_INTERVAL_HOURS)
    while True:
        try:
            run_proactive_scan()
        except Exception as exc:
            log.error("[Proactive] Scan failed: %s", exc)
        time.sleep(SCAN_INTERVAL_HOURS * 3600)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Proactive Intelligence Engine")
    parser.add_argument("--daemon", action="store_true",
                        help=f"Run continuously every {SCAN_INTERVAL_HOURS} hours")
    args = parser.parse_args()

    if args.daemon:
        _proactive_poll_loop()
    else:
        n = run_proactive_scan()
        print(f"\nProactive scan complete. {n} suggestion(s) written to Vault/Needs_Action/")
