"""
gmail_mcp_server.py – Gmail MCP Server for Claude Code.

Exposes Gmail send/draft/read as MCP tools that Claude can call directly.
Uses the same OAuth2 credentials as gmail_watcher.py.

Usage (Claude Code will start this automatically via .mcp.json):
    python gmail_mcp_server.py

Or run manually to test:
    python gmail_mcp_server.py --test

Setup:
    1. Ensure credentials.json is in E:/Hackathon_0/
    2. Run gmail_watcher.py once to complete OAuth (creates token.json)
    3. Claude Code loads this server via .mcp.json automatically
"""

import base64
import json
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

BASE_DIR = Path(__file__).parent
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _get_gmail_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# Gmail actions
# ---------------------------------------------------------------------------

def send_email(to: str, subject: str, body: str, reply_to_msg_id: str = "") -> dict:
    """Send an email via Gmail API."""
    service = _get_gmail_service()

    msg = MIMEMultipart()
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if reply_to_msg_id:
        msg["In-Reply-To"] = reply_to_msg_id
        msg["References"] = reply_to_msg_id

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(
        userId="me",
        body={"raw": raw},
    ).execute()
    return {"status": "sent", "message_id": result.get("id"), "thread_id": result.get("threadId")}


def draft_email(to: str, subject: str, body: str) -> dict:
    """Save a draft without sending."""
    service = _get_gmail_service()

    msg = MIMEMultipart()
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw}},
    ).execute()
    return {"status": "drafted", "draft_id": result.get("id")}


def list_unread(max_results: int = 10, query: str = "is:unread is:important") -> list[dict]:
    """List unread emails."""
    service = _get_gmail_service()
    results = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()
    messages = results.get("messages", [])
    out = []
    for m in messages:
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["Subject", "From", "Date"]
        ).execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        out.append({
            "id": m["id"],
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "date": headers.get("Date", ""),
        })
    return out


def read_email(message_id: str) -> dict:
    """Read full content of an email by ID."""
    service = _get_gmail_service()
    msg = service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()
    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

    def _decode(payload):
        if "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace") if data else ""

    return {
        "id": message_id,
        "subject": headers.get("Subject", ""),
        "from": headers.get("From", ""),
        "date": headers.get("Date", ""),
        "body": _decode(msg.get("payload", {})),
    }


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

def run_mcp_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print("ERROR: mcp package not installed. Run: uv add 'mcp[cli]'", file=sys.stderr)
        sys.exit(1)

    mcp = FastMCP("Gmail")

    @mcp.tool()
    def gmail_send(to: str, subject: str, body: str, reply_to_msg_id: str = "") -> str:
        """
        Send an email via Gmail.

        Args:
            to: Recipient email address
            subject: Email subject line
            body: Plain text email body
            reply_to_msg_id: Optional Gmail message ID to reply to (for threading)

        Returns:
            JSON string with status and message_id
        """
        result = send_email(to, subject, body, reply_to_msg_id)
        return json.dumps(result)

    @mcp.tool()
    def gmail_draft(to: str, subject: str, body: str) -> str:
        """
        Save an email as a Gmail draft without sending.

        Args:
            to: Recipient email address
            subject: Email subject line
            body: Plain text email body

        Returns:
            JSON string with status and draft_id
        """
        result = draft_email(to, subject, body)
        return json.dumps(result)

    @mcp.tool()
    def gmail_list_unread(max_results: int = 10, query: str = "is:unread is:important") -> str:
        """
        List unread emails from Gmail.

        Args:
            max_results: Maximum number of emails to return (default 10)
            query: Gmail search query (default: unread + important)

        Returns:
            JSON array of email summaries with id, subject, from, date
        """
        result = list_unread(max_results, query)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def gmail_read(message_id: str) -> str:
        """
        Read the full content of a Gmail message by its ID.

        Args:
            message_id: Gmail message ID (from gmail_list_unread)

        Returns:
            JSON with subject, from, date, and body text
        """
        result = read_email(message_id)
        return json.dumps(result, indent=2)

    mcp.run()


# ---------------------------------------------------------------------------
# CLI test mode
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("Testing Gmail MCP server...")
        print("Listing unread emails:")
        emails = list_unread(max_results=3)
        for e in emails:
            print(f"  - [{e['id']}] {e['subject']} (from {e['from']})")
        print(f"\nFound {len(emails)} email(s). Auth working correctly.")
    else:
        run_mcp_server()
