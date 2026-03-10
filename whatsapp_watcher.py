"""
whatsapp_watcher.py – WhatsApp Web Watcher via Playwright.

Opens WhatsApp Web, monitors incoming messages, and writes matching
messages as .md files into Vault/Inbox/.

First run:
    1. Run this script — a Chromium browser window opens.
    2. Scan the QR code with your phone (WhatsApp -> Linked Devices).
    3. The session is saved in whatsapp_session/ for future runs.

Requirements:
    uv add playwright
    uv run playwright install chromium

Usage:
    uv run python whatsapp_watcher.py              # monitor once (30s)
    uv run python whatsapp_watcher.py --daemon     # poll continuously

Config:
    Set WATCH_KEYWORDS in this file or via WHATSAPP_KEYWORDS env var
    (comma-separated). If empty, ALL new messages are captured.
"""

import argparse
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
VAULT_ROOT = BASE_DIR / "Vault"
INBOX_DIR = VAULT_ROOT / "Inbox"
SESSION_DIR = BASE_DIR / "whatsapp_session"
LOG_FILE = BASE_DIR / "whatsapp_watcher.log"

# Keywords to filter — empty list = capture all new messages
WATCH_KEYWORDS_DEFAULT = ["urgent", "asap", "invoice", "payment", "meeting"]
POLL_INTERVAL_SECONDS = 60  # check every minute in daemon mode
SCAN_DURATION_SECONDS = 30  # how long to scan for new messages each poll

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("whatsapp-watcher")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_keywords() -> list[str]:
    raw = os.environ.get("WHATSAPP_KEYWORDS", "")
    if raw:
        return [k.strip().lower() for k in raw.split(",") if k.strip()]
    return [k.lower() for k in WATCH_KEYWORDS_DEFAULT]


def message_matches(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def message_to_markdown(sender: str, chat_name: str, text: str) -> tuple[str, str]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_sender = re.sub(r"[^\w\s-]", "", sender).strip().replace(" ", "_")[:40]
    filename = f"whatsapp_{timestamp}_{safe_sender}.md"

    content = f"""---
source: whatsapp
received: {datetime.now().strftime("%Y-%m-%d %H:%M")}
status: inbox
priority: medium
tags: [whatsapp]
summary: ""
from: {sender}
chat: {chat_name}
---

# WhatsApp Message from {sender}

**Chat:** {chat_name}
**Time:** {datetime.now().strftime("%Y-%m-%d %H:%M")}

---

{text.strip()}
"""
    return filename, content


# ---------------------------------------------------------------------------
# WhatsApp scraper
# ---------------------------------------------------------------------------

def run_watcher(daemon: bool = False):
    """Launch Playwright, open WhatsApp Web, and monitor messages."""
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        log.error(
            "Playwright not installed. Run:\n"
            "  uv add playwright && uv run playwright install chromium"
        )
        sys.exit(1)

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    keywords = get_keywords()
    log.info("Watching for keywords: %s", keywords if keywords else "(all messages)")

    seen_message_ids: set[str] = set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=False,  # Must be visible for QR scan
            args=["--no-sandbox"],
        )
        page = browser.new_page()
        log.info("Opening WhatsApp Web...")
        page.goto("https://web.whatsapp.com")

        # Wait for WhatsApp to load (QR scan or session restore)
        log.info("Waiting for WhatsApp to load (scan QR if prompted)...")
        try:
            page.wait_for_selector('[data-testid="chat-list"]', timeout=120_000)
            log.info("WhatsApp Web loaded.")
        except PWTimeout:
            log.error("Timed out waiting for WhatsApp to load.")
            browser.close()
            return

        def scan_once() -> int:
            """Scan visible unread chats and save matching messages. Returns count saved."""
            count = 0
            try:
                # Find chats with unread badge
                unread_chats = page.query_selector_all('[data-testid="icon-unread-count"]')
                log.info("Found %d unread chat(s).", len(unread_chats))

                for badge in unread_chats:
                    try:
                        # Click the parent chat row
                        chat_row = badge.evaluate_handle(
                            "el => el.closest('[data-testid=\"cell-frame-container\"]')"
                        )
                        chat_row.as_element().click()
                        time.sleep(1.5)

                        # Get chat name
                        try:
                            chat_name_el = page.query_selector('[data-testid="conversation-info-header-chat-title"]')
                            chat_name = chat_name_el.inner_text() if chat_name_el else "Unknown"
                        except Exception:
                            chat_name = "Unknown"

                        # Get last few messages
                        msgs = page.query_selector_all(
                            '.message-in [data-testid="msg-container"]'
                        )
                        for msg_el in msgs[-5:]:  # last 5 incoming messages
                            try:
                                text_el = msg_el.query_selector(
                                    '[data-testid="msg-meta"], .copyable-text'
                                )
                                if not text_el:
                                    continue
                                text = text_el.inner_text().strip()
                                if not text:
                                    continue

                                # De-duplicate using text+chat fingerprint
                                msg_id = f"{chat_name}::{text[:80]}"
                                if msg_id in seen_message_ids:
                                    continue

                                if message_matches(text, keywords):
                                    # Try to extract individual sender (group chats)
                                    try:
                                        pre_plain = msg_el.get_attribute("data-pre-plain-text") or ""
                                        # Format: "[HH:MM, DD/MM/YYYY] Sender Name: "
                                        sender = pre_plain.split("] ")[-1].rstrip(": ") if "] " in pre_plain else chat_name
                                    except Exception:
                                        sender = chat_name
                                    filename, content = message_to_markdown(
                                        sender, chat_name, text
                                    )
                                    (INBOX_DIR / filename).write_text(content, encoding="utf-8")
                                    seen_message_ids.add(msg_id)
                                    log.info("Saved WhatsApp message -> %s", filename)
                                    count += 1
                            except Exception as e:
                                log.debug("Error reading message: %s", e)
                    except Exception as e:
                        log.debug("Error processing chat: %s", e)

            except Exception as e:
                log.error("Scan error: %s", e)
            return count

        if daemon:
            log.info("Daemon mode — scanning every %ds. Press Ctrl+C to stop.", POLL_INTERVAL_SECONDS)
            try:
                while True:
                    n = scan_once()
                    if n:
                        log.info("Captured %d message(s) -> Vault/Inbox/", n)
                    time.sleep(POLL_INTERVAL_SECONDS)
            except KeyboardInterrupt:
                log.info("WhatsApp Watcher stopped.")
        else:
            log.info("Scanning for %ds...", SCAN_DURATION_SECONDS)
            time.sleep(SCAN_DURATION_SECONDS)
            n = scan_once()
            log.info("Done. Captured %d message(s).", n)

        browser.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="WhatsApp Web Vault Watcher")
    parser.add_argument("--daemon", action="store_true", help="Poll continuously")
    args = parser.parse_args()
    log.info("WhatsApp Watcher started.")
    run_watcher(daemon=args.daemon)


if __name__ == "__main__":
    main()
