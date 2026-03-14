"""
calendar_mcp_server.py – Google Calendar MCP Server for Claude Code.

Exposes calendar create/list/update/delete as MCP tools.
Uses the same Google OAuth credentials.json as gmail_watcher.py
but with Calendar scopes (separate token: calendar_token.json).

First run will open a browser for OAuth authorization.

Usage (Claude Code loads automatically via .mcp.json):
    python calendar_mcp_server.py

Test manually:
    python calendar_mcp_server.py --test
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "calendar_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _get_calendar_service():
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

    return build("calendar", "v3", credentials=creds)


# ---------------------------------------------------------------------------
# Calendar actions
# ---------------------------------------------------------------------------

def create_event(
    title: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    calendar_id: str = "primary",
) -> dict:
    """
    Create a calendar event.
    start/end: ISO 8601 format e.g. '2026-03-15T10:00:00+05:00'
    """
    service = _get_calendar_service()
    event = {
        "summary": title,
        "description": description,
        "location": location,
        "start": {"dateTime": start, "timeZone": "Asia/Karachi"},
        "end": {"dateTime": end, "timeZone": "Asia/Karachi"},
    }
    result = service.events().insert(calendarId=calendar_id, body=event).execute()
    return {
        "status": "created",
        "event_id": result.get("id"),
        "html_link": result.get("htmlLink"),
        "title": result.get("summary"),
        "start": result.get("start", {}).get("dateTime"),
    }


def list_events(days_ahead: int = 7, max_results: int = 10, calendar_id: str = "primary") -> list[dict]:
    """List upcoming calendar events."""
    service = _get_calendar_service()
    now = datetime.utcnow().isoformat() + "Z"
    end = (datetime.utcnow() + timedelta(days=days_ahead)).isoformat() + "Z"
    result = service.events().list(
        calendarId=calendar_id,
        timeMin=now,
        timeMax=end,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    events = result.get("items", [])
    return [
        {
            "event_id": e.get("id"),
            "title": e.get("summary", ""),
            "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date")),
            "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date")),
            "location": e.get("location", ""),
            "description": e.get("description", ""),
        }
        for e in events
    ]


def update_event(
    event_id: str,
    title: str = "",
    start: str = "",
    end: str = "",
    description: str = "",
    location: str = "",
    calendar_id: str = "primary",
) -> dict:
    """Update an existing calendar event by ID."""
    service = _get_calendar_service()
    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
    if title:
        event["summary"] = title
    if description:
        event["description"] = description
    if location:
        event["location"] = location
    if start:
        event["start"] = {"dateTime": start, "timeZone": "Asia/Karachi"}
    if end:
        event["end"] = {"dateTime": end, "timeZone": "Asia/Karachi"}
    result = service.events().update(calendarId=calendar_id, eventId=event_id, body=event).execute()
    return {"status": "updated", "event_id": result.get("id"), "title": result.get("summary")}


def delete_event(event_id: str, calendar_id: str = "primary") -> dict:
    """Delete a calendar event by ID."""
    service = _get_calendar_service()
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    return {"status": "deleted", "event_id": event_id}


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

def run_mcp_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print("ERROR: mcp not installed. Run: uv add 'mcp[cli]'", file=sys.stderr)
        sys.exit(1)

    mcp = FastMCP("Calendar")

    @mcp.tool()
    def calendar_create_event(
        title: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
    ) -> str:
        """
        Create a Google Calendar event.

        Args:
            title: Event title/summary
            start: Start time in ISO 8601 format (e.g. '2026-03-15T10:00:00+05:00')
            end: End time in ISO 8601 format
            description: Optional event description
            location: Optional event location

        Returns:
            JSON with event_id and html_link
        """
        return json.dumps(create_event(title, start, end, description, location))

    @mcp.tool()
    def calendar_list_events(days_ahead: int = 7, max_results: int = 10) -> str:
        """
        List upcoming Google Calendar events.

        Args:
            days_ahead: How many days ahead to look (default 7)
            max_results: Maximum number of events to return (default 10)

        Returns:
            JSON array of upcoming events with id, title, start, end, location
        """
        return json.dumps(list_events(days_ahead, max_results), indent=2)

    @mcp.tool()
    def calendar_update_event(
        event_id: str,
        title: str = "",
        start: str = "",
        end: str = "",
        description: str = "",
        location: str = "",
    ) -> str:
        """
        Update an existing Google Calendar event.

        Args:
            event_id: The event ID (from calendar_list_events)
            title: New title (leave empty to keep current)
            start: New start time ISO 8601 (leave empty to keep current)
            end: New end time ISO 8601 (leave empty to keep current)
            description: New description (leave empty to keep current)
            location: New location (leave empty to keep current)

        Returns:
            JSON with updated event status
        """
        return json.dumps(update_event(event_id, title, start, end, description, location))

    @mcp.tool()
    def calendar_delete_event(event_id: str) -> str:
        """
        Delete a Google Calendar event.

        Args:
            event_id: The event ID to delete (from calendar_list_events)

        Returns:
            JSON with deletion status
        """
        return json.dumps(delete_event(event_id))

    mcp.run()


# ---------------------------------------------------------------------------
# CLI test mode
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("Testing Calendar MCP server...")
        events = list_events(days_ahead=7, max_results=5)
        print(f"Upcoming events (next 7 days): {len(events)}")
        for e in events:
            print(f"  - {e['title']} @ {e['start']}")
        print("\nCalendar auth working correctly.")
    else:
        run_mcp_server()
