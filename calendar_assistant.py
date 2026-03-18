"""
calendar_assistant.py – Smart Calendar Assistant (Platinum Tier Feature 5)

Two capabilities:
  1. Meeting detection — scans emails/WhatsApp for meeting mentions →
     writes PLAN_calendar_*.md to Vault/Plans/ for HITL approval →
     on approval, creates Google Calendar event via calendar_mcp_server.py

  2. Daily agenda — sends a 7 AM email with today's calendar events via Gmail

Usage:
    uv run python calendar_assistant.py --agenda   # send today's agenda now
    uv run python calendar_assistant.py --scan     # scan Needs_Action for meetings

schedule_setup.py adds a daily 7 AM task for --agenda.
main.py runs meeting detection automatically via InboxHandler.
"""

import logging
import os
import re
import sys
import time
import io
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
VAULT_ROOT = BASE_DIR / "Vault"
LOG_FILE = BASE_DIR / "calendar_assistant.log"

_console = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(_console),
    ],
)
log = logging.getLogger("calendar-assistant")

# Patterns that suggest a meeting request
MEETING_PATTERNS = [
    re.compile(r"\b(meet|meeting|call|sync|standup|catch[\s-]up|discuss|schedule)\b", re.I),
    re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I),
    re.compile(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", re.I),
    re.compile(r"\b(tomorrow|next week|this week|today at|this (monday|friday))\b", re.I),
    re.compile(r"\b(zoom|teams|google meet|meet\.google|calendly|skype)\b", re.I),
]
MEETING_CONFIDENCE_THRESHOLD = 0.3   # ≥ 2 of 5 patterns


# ---------------------------------------------------------------------------
# Meeting intent detection
# ---------------------------------------------------------------------------

def detect_meeting_intent(text: str) -> dict:
    """
    Returns {"has_meeting": bool, "confidence": float, "signals": [str]}.
    """
    signals = []
    for pat in MEETING_PATTERNS:
        m = pat.search(text)
        if m:
            signals.append(m.group(0))

    confidence = len(signals) / len(MEETING_PATTERNS)
    return {
        "has_meeting": confidence >= MEETING_CONFIDENCE_THRESHOLD,
        "confidence": round(confidence, 2),
        "signals": signals,
    }


def extract_meeting_details(text: str, task_name: str = "") -> dict | None:
    """
    Use LLM to extract structured meeting details from text.
    Returns {title, date_iso, start_time, end_time, attendees, location, description} or None.
    """
    from router import route_completion

    today = datetime.now().strftime("%Y-%m-%d")
    system = (
        "You are a calendar assistant. Extract meeting details from the text.\n"
        f"Today is {today}.\n"
        "Output ONLY valid JSON with these fields (use null for unknown):\n"
        '{"title": str, "date": "YYYY-MM-DD", "start_time": "HH:MM", '
        '"end_time": "HH:MM", "attendees": [str], "location": str, "description": str}\n'
        "If you cannot determine a specific date/time, use null."
    )
    user = f"Extract meeting details from:\n\n{text[:2000]}"

    raw = route_completion(system, user, force_model="groq")
    if not raw:
        return None

    try:
        # Extract JSON block from response
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            return None
        import json
        details = json.loads(json_match.group(0))
        # Validate required fields
        if details.get("title") and details.get("date"):
            return details
    except Exception as exc:
        log.warning("[Calendar] JSON parse failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Write calendar suggestion plan
# ---------------------------------------------------------------------------

def write_calendar_suggestion(task_name: str, details: dict) -> Path | None:
    """
    Write a PLAN_calendar_*.md to Vault/Plans/ for HITL approval.
    On approval, approval_watcher._execute_calendar_plan() creates the event.
    """
    from vault_io import VaultIO
    vault = VaultIO()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^\w]", "_", (details.get("title") or "meeting")[:30])
    plan_name = f"calendar_{ts}_{safe}.md"

    date_str = details.get("date") or datetime.now().strftime("%Y-%m-%d")
    start_time = details.get("start_time") or "09:00"
    end_time = details.get("end_time") or "10:00"
    attendees = ", ".join(details.get("attendees") or []) or "_not specified_"
    location = details.get("location") or "_not specified_"
    description = details.get("description") or ""

    content = f"""---
task: {task_name}
approval_needed: yes
priority: medium
source: calendar
generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}
---

# Plan: Calendar Event — {details.get("title", "Meeting")}

## Summary
Meeting detected in `{task_name}`. Review the details below and approve to create the Google Calendar event.

## Calendar Event

- **Title:** {details.get("title", "Meeting")}
- **Date:** {date_str}
- **Start:** {start_time}
- **End:** {end_time}
- **Attendees:** {attendees}
- **Location:** {location}
- **Description:** {description}

---
## Your Decision

Review the event details above, edit if needed, then check **one** box and save:

- [ ] ✅ Approve — create this Google Calendar event now
- [ ] ⏸ Pending Approval — hold for later review
"""

    plan_path = vault.plans / f"PLAN_{plan_name}"
    plan_path.write_text(content, encoding="utf-8")
    vault.log_action(
        action_type="calendar_suggestion_created",
        actor="calendar_assistant",
        target=plan_path.name,
        approval_status="pending",
        result="success",
        details=f"Meeting: {details.get('title')} on {date_str}",
    )
    log.info("[Calendar] Suggestion written: Plans/%s", plan_path.name)
    return plan_path


# ---------------------------------------------------------------------------
# Scan Needs_Action for meeting mentions
# ---------------------------------------------------------------------------

def scan_for_meetings(vault=None) -> int:
    """
    Scan new items in Needs_Action/ for meeting mentions.
    Writes calendar suggestion plans for any detected meetings.
    Returns count of suggestions written.
    """
    if vault is None:
        from vault_io import VaultIO
        vault = VaultIO()

    from error_recovery import ErrorRecovery
    count = 0

    for f in vault.needs_action.glob("*.md"):
        if f.name.startswith(("PROACTIVE_", "CEO_BRIEFING_", "BLOCKED_", "PLAN_calendar_")):
            continue

        # Skip if calendar plan already exists for this task
        safe = f.name.replace(".md", "")
        existing = list(vault.plans.glob(f"PLAN_calendar_*{safe[:20]}*.md"))
        if existing:
            continue

        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        intent = detect_meeting_intent(text)
        if not intent["has_meeting"]:
            continue

        log.info("[Calendar] Meeting detected in %s (confidence=%.2f, signals=%s)",
                 f.name, intent["confidence"], intent["signals"])

        with ErrorRecovery("calendar_assistant", f"Extract meeting from {f.name}"):
            details = extract_meeting_details(text, f.name)
            if details:
                write_calendar_suggestion(f.name, details)
                count += 1
            else:
                log.warning("[Calendar] Could not extract details from %s", f.name)

    return count


# ---------------------------------------------------------------------------
# Execute calendar plan (called by approval_watcher.py)
# ---------------------------------------------------------------------------

def execute_calendar_plan(plan_content: str) -> tuple[bool, str]:
    """
    Parse a PLAN_calendar_*.md and create the Google Calendar event.
    Returns (success, report_markdown).
    """
    # Extract fields from ## Calendar Event section
    fields: dict = {}
    lines = plan_content.splitlines()
    in_section = False
    for line in lines:
        if line.strip() == "## Calendar Event":
            in_section = True
            continue
        if in_section:
            if line.startswith("##") or line.startswith("---"):
                break
            # Parse "- **Field:** Value"
            m = re.match(r"-\s+\*\*(.+?)\*\*:\s+(.+)", line.strip())
            if m:
                fields[m.group(1).lower()] = m.group(2).strip()

    title = fields.get("title", "Meeting")
    date_str = fields.get("date", datetime.now().strftime("%Y-%m-%d"))
    start_time = fields.get("start", "09:00").replace("_not specified_", "09:00")
    end_time = fields.get("end", "10:00").replace("_not specified_", "10:00")
    location = fields.get("location", "").replace("_not specified_", "")
    description = fields.get("description", "")

    # Build ISO 8601 datetimes
    try:
        # Attempt to get timezone offset from environment or default to +05:00 (PKT)
        tz = os.getenv("CALENDAR_TIMEZONE", "+05:00")
        start_iso = f"{date_str}T{start_time}:00{tz}"
        end_iso = f"{date_str}T{end_time}:00{tz}"
    except Exception:
        start_iso = f"{date_str}T09:00:00+05:00"
        end_iso = f"{date_str}T10:00:00+05:00"

    try:
        from calendar_mcp_server import create_event
        result = create_event(
            title=title,
            start=start_iso,
            end=end_iso,
            description=description,
            location=location,
        )
        event_id = result.get("id", "unknown")
        event_link = result.get("htmlLink", "")
        log.info("[Calendar] Event created: %s (%s)", title, event_id)
        return True, (
            f"## Execution Report\n\n"
            f"| Step | Result |\n|------|--------|\n"
            f"| Create calendar event | Done |\n"
            f"| Title | {title} |\n"
            f"| Date/Time | {date_str} {start_time}–{end_time} |\n"
            f"| Event ID | `{event_id}` |\n"
            f"| Link | {event_link} |\n\n"
            f"**Status: COMPLETE**"
        )
    except Exception as exc:
        log.error("[Calendar] Event creation failed: %s", exc)
        return False, (
            f"## Execution Report\n\n"
            f"Failed to create calendar event: {exc}\n\n"
            f"**Status: BLOCKED**"
        )


# ---------------------------------------------------------------------------
# Daily agenda email
# ---------------------------------------------------------------------------

def send_daily_agenda() -> bool:
    """Fetch today's Google Calendar events and email them to CEO_EMAIL."""
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env")
    except ImportError:
        pass

    ceo_email = os.getenv("CEO_EMAIL", "")
    if not ceo_email:
        log.warning("[Calendar] CEO_EMAIL not set — skipping agenda email")
        return False

    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        from calendar_mcp_server import _get_calendar_service
        service = _get_calendar_service()
        tz = os.getenv("CALENDAR_TIMEZONE", "+05:00")
        events_result = service.events().list(
            calendarId="primary",
            timeMin=f"{today}T00:00:00{tz}",
            timeMax=f"{tomorrow}T00:00:00{tz}",
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = events_result.get("items", [])
    except Exception as exc:
        log.error("[Calendar] Failed to fetch events: %s", exc)
        return False

    if not events:
        agenda_body = "_No events scheduled for today._"
    else:
        lines = []
        for event in events:
            start = event.get("start", {})
            time_str = start.get("dateTime", start.get("date", ""))
            if "T" in time_str:
                try:
                    dt = datetime.fromisoformat(time_str[:19])
                    time_str = dt.strftime("%H:%M")
                except Exception:
                    pass
            title = event.get("summary", "Untitled")
            location = event.get("location", "")
            loc_str = f" @ {location}" if location else ""
            lines.append(f"• **{time_str}** — {title}{loc_str}")
        agenda_body = "\n".join(lines)

    subject = f"[AI Employee] Today's Agenda — {today}"
    body = f"""**Good morning! Here's your agenda for {today}:**

{agenda_body}

---
*Sent automatically by your AI Employee at 7:00 AM*
*Powered by Google Calendar + Claude*
"""

    try:
        from gmail_mcp_server import send_email
        result = send_email(ceo_email, subject, body)
        log.info("[Calendar] Agenda sent to %s (ID: %s)", ceo_email, result.get("message_id", "?"))
        return True
    except Exception as exc:
        log.error("[Calendar] Agenda email failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Thread target for main.py (7 AM daily agenda)
# ---------------------------------------------------------------------------

def _seconds_until_7am() -> float:
    now = datetime.now()
    target = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _calendar_agenda_loop():
    """Daemon thread — sleeps until 7 AM, sends agenda, repeats daily."""
    log.info("[Calendar] Agenda loop started.")
    while True:
        wait = _seconds_until_7am()
        log.info("[Calendar] Next agenda email in %.0f seconds (7 AM).", wait)
        time.sleep(wait)
        from error_recovery import ErrorRecovery
        with ErrorRecovery("calendar_assistant", "Daily agenda email"):
            send_daily_agenda()
        time.sleep(90)   # prevent double-send within same minute


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Smart Calendar Assistant")
    parser.add_argument("--agenda", action="store_true", help="Send today's agenda email now")
    parser.add_argument("--scan", action="store_true", help="Scan Needs_Action for meeting mentions")
    args = parser.parse_args()

    if args.agenda:
        ok = send_daily_agenda()
        print("Agenda email sent." if ok else "Agenda email failed — check logs.")
    elif args.scan:
        n = scan_for_meetings()
        print(f"Meeting scan complete. {n} calendar suggestion(s) written to Vault/Plans/")
    else:
        parser.print_help()
