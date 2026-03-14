"""
gmail_watcher.py – Gmail Watcher for the Obsidian Vault.

Polls Gmail for unread, important emails and writes each one as a .md
file into Vault/Inbox/, then marks the email as read.

Setup (one-time):
    1. Go to Google Cloud Console → APIs & Services → Enable Gmail API
    2. Create OAuth2 Desktop credentials → download as credentials.json
    3. Place credentials.json in E:/Hackathon_0/
    4. Run this script once — it will open a browser for OAuth consent
       and save token.json for future runs.

Requirements (added to pyproject.toml):
    google-auth-oauthlib
    google-auth-httplib2
    google-api-python-client

Usage:
    uv run python gmail_watcher.py              # run once
    uv run python gmail_watcher.py --daemon     # poll continuously
"""

import argparse
import base64
import logging
import sys
import time
from datetime import datetime
from email import message_from_bytes
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
VAULT_ROOT = BASE_DIR / "Vault"
INBOX_DIR = VAULT_ROOT / "Inbox"
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"
LOG_FILE = BASE_DIR / "gmail_watcher.log"

# Gmail query — fetches unread emails NOT from automated senders.
# Excludes OTPs, notifications, newsletters, and system alerts.
# Adjust to taste — Gmail search operators: https://support.google.com/mail/answer/7190
GMAIL_QUERY = (
    "is:unread is:important "
    "-category:promotions "
    "-category:updates "
    "-category:social "
    "-subject:(OTP OR verify OR verification OR \"sign in\" OR \"sign-in\" "
    "OR alert OR notification OR newsletter OR unsubscribe)"
)
POLL_INTERVAL_SECONDS = 120  # 2 minutes

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

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
log = logging.getLogger("gmail-watcher")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def get_gmail_service():
    """Authenticate and return a Gmail API service object."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        log.error(
            "Missing Google client libraries. Run:\n"
            "  uv add google-auth-oauthlib google-auth-httplib2 google-api-python-client"
        )
        sys.exit(1)

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                log.error(
                    "credentials.json not found at %s\n"
                    "Download it from Google Cloud Console → APIs & Services → Credentials.",
                    CREDENTIALS_FILE,
                )
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# Email processing
# ---------------------------------------------------------------------------

def _decode_body(payload: dict) -> str:
    """Extract plain-text body from a Gmail message payload."""
    if "parts" in payload:
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        # Recurse into nested parts
        for part in payload["parts"]:
            result = _decode_body(part)
            if result:
                return result
    else:
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    return ""


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def email_to_markdown(msg: dict) -> tuple[str, str]:
    """
    Convert a Gmail message dict to (filename, markdown_content).
    Returns a safe filename and a vault-ready .md string.
    """
    payload = msg.get("payload", {})
    headers = payload.get("headers", [])

    subject = _header(headers, "Subject") or "No Subject"
    sender_raw = _header(headers, "From") or "Unknown"
    date_str = _header(headers, "Date") or datetime.now().isoformat()
    body = _decode_body(payload)

    # Extract bare email address from "Name <email@x.com>" format
    import re
    email_match = re.search(r"<([^>]+@[^>]+)>", sender_raw)
    sender_email = email_match.group(1).strip() if email_match else sender_raw.strip()

    # Safe filename: strip non-alphanumeric
    safe_subject = re.sub(r"[^\w\s-]", "", subject).strip().replace(" ", "_")[:60]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"email_{timestamp}_{safe_subject}.md"

    content = f"""---
source: email
received: {datetime.now().strftime("%Y-%m-%d %H:%M")}
status: inbox
priority: medium
tags: []
summary: ""
from: {sender_email}
from_name: {sender_raw}
subject: {subject}
---

# {subject}

**From:** {sender_raw}
**Date:** {date_str}

---

{body.strip()}
"""
    return filename, content


def fetch_and_save_emails(service) -> int:
    """Fetch unread important emails, write to Inbox, mark as read. Returns count."""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)

    try:
        results = service.users().messages().list(
            userId="me", q=GMAIL_QUERY, maxResults=20
        ).execute()
    except Exception as exc:
        log.error("Gmail API error: %s", exc)
        return 0

    messages = results.get("messages", [])
    if not messages:
        log.info("No new important emails.")
        return 0

    count = 0
    for msg_ref in messages:
        try:
            msg = service.users().messages().get(
                userId="me", id=msg_ref["id"], format="full"
            ).execute()

            filename, content = email_to_markdown(msg)
            dest = INBOX_DIR / filename
            dest.write_text(content, encoding="utf-8")
            log.info("Saved email -> %s", filename)

            # Mark as read
            service.users().messages().modify(
                userId="me",
                id=msg_ref["id"],
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()

            count += 1
        except Exception as exc:
            log.error("Failed to process message %s: %s", msg_ref["id"], exc)

    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Gmail Vault Watcher")
    parser.add_argument(
        "--daemon", action="store_true",
        help=f"Poll continuously every {POLL_INTERVAL_SECONDS}s"
    )
    args = parser.parse_args()

    log.info("Gmail Watcher started.")
    service = get_gmail_service()

    if args.daemon:
        log.info("Daemon mode — polling every %ds. Press Ctrl+C to stop.", POLL_INTERVAL_SECONDS)
        try:
            while True:
                count = fetch_and_save_emails(service)
                if count:
                    log.info("Fetched %d email(s) -> Vault/Inbox/", count)
                time.sleep(POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            log.info("Gmail Watcher stopped.")
    else:
        count = fetch_and_save_emails(service)
        log.info("Done. Fetched %d email(s).", count)


if __name__ == "__main__":
    main()
