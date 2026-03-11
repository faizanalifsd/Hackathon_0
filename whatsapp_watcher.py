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
WATCH_KEYWORDS_DEFAULT = []  # empty = capture ALL messages
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
    # Use chat_name for filename (more reliable than sender in group chats)
    name_for_file = chat_name if chat_name and chat_name != "Unknown" else sender
    safe_name = re.sub(r"[^\w\s-]", "", name_for_file).strip().replace(" ", "_")[:40]
    # Add short content hash to prevent duplicate filenames
    import hashlib
    content_hash = hashlib.md5(text[:80].encode()).hexdigest()[:6]
    filename = f"whatsapp_{timestamp}_{safe_name}_{content_hash}.md"

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

    # Clear Chrome lock files left by previous crashed/killed sessions
    for lock_file in ["lockfile", "SingletonLock", "SingletonSocket", "SingletonCookie"]:
        lock_path = SESSION_DIR / lock_file
        if lock_path.exists():
            try:
                lock_path.unlink()
                log.info("Cleared lock file: %s", lock_file)
            except Exception:
                pass

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
        page.goto("https://web.whatsapp.com", timeout=60000, wait_until="domcontentloaded")

        # Wait for WhatsApp to load (QR scan or session restore)
        log.info("Waiting for WhatsApp to load (scan QR if prompted)...")
        try:
            page.wait_for_selector(
                '[data-testid="chat-list"], #side, ._aigv, [aria-label="Chat list"]',
                timeout=300_000
            )
            log.info("WhatsApp Web loaded.")
        except PWTimeout:
            log.error("Timed out waiting for WhatsApp to load.")
            browser.close()
            return

        def scan_once() -> int:
            """Scan visible unread chats and save matching messages. Returns count saved."""
            count = 0
            try:
                # Try multiple known selectors for unread badges (WhatsApp changes these often)
                unread_chats = []
                for selector in [
                    '[data-testid="icon-unread-count"]',
                    'span[data-testid="icon-unread-count"]',
                    '[aria-label*="unread"]',
                    'span.x1c4vz4f',  # fallback class
                ]:
                    unread_chats = page.query_selector_all(selector)
                    if unread_chats:
                        log.info("Found %d unread chat(s) via selector: %s", len(unread_chats), selector)
                        break

                if not unread_chats:
                    log.info("Found 0 unread chat(s).")
                    return 0

                for badge in unread_chats:
                    try:
                        # Click the parent chat row — walk up the DOM to find a clickable row
                        clicked = False
                        for container in [
                            '[data-testid="cell-frame-container"]',
                            '[role="listitem"]',
                            'div[tabindex="-1"]',
                            'li',
                        ]:
                            try:
                                chat_row = badge.evaluate_handle(
                                    f"el => el.closest('{container}')"
                                )
                                el = chat_row.as_element()
                                if el:
                                    el.click()
                                    clicked = True
                                    break
                            except Exception:
                                continue

                        if not clicked:
                            # Last resort: click the badge itself
                            try:
                                badge.click()
                            except Exception:
                                continue
                        time.sleep(2)

                        # Get chat name — try multiple selectors
                        chat_name = "Unknown"
                        for sel in [
                            '[data-testid="conversation-info-header-chat-title"]',
                            'header [data-testid="conversation-title"]',
                            'header span[title]',
                            '#main header span[dir="auto"]',
                        ]:
                            el = page.query_selector(sel)
                            if el:
                                chat_name = el.inner_text().strip() or el.get_attribute("title") or "Unknown"
                                break

                        # Get last few messages — try multiple selectors
                        msgs = []
                        for sel in [
                            '.message-in [data-testid="msg-container"]',
                            '[data-testid="msg-container"]',
                            'div.message-in',
                            'div[class*="message-in"]',
                        ]:
                            msgs = page.query_selector_all(sel)
                            if msgs:
                                log.debug("Found %d messages via selector: %s", len(msgs), sel)
                                break

                        # Fallback: grab all copyable-text spans in the conversation
                        if not msgs:
                            msgs = page.query_selector_all('.copyable-text')

                        for msg_el in msgs[-10:]:  # last 10 messages
                            try:
                                # Extract text — try specific selectors then full inner text
                                text = ""
                                for text_sel in [
                                    '.copyable-text',
                                    'span[dir="ltr"]',
                                    'span[dir="rtl"]',
                                    '[data-testid="msg-meta"]',
                                ]:
                                    text_el = msg_el.query_selector(text_sel)
                                    if text_el:
                                        text = text_el.inner_text().strip()
                                        if text:
                                            break
                                if not text:
                                    text = msg_el.inner_text().strip()
                                # Clean up timestamp noise (e.g. "10:30 AM\n\nHello")
                                lines = [l for l in text.splitlines() if l.strip() and not l.strip().startswith("✓")]
                                text = "\n".join(lines).strip()
                                if not text:
                                    continue

                                # De-duplicate using chat + content fingerprint
                                import hashlib
                                msg_id = hashlib.md5(f"{chat_name}::{text[:120]}".encode()).hexdigest()[:12]
                                if msg_id in seen_message_ids:
                                    continue
                                seen_message_ids.add(msg_id)

                                if message_matches(text, keywords):
                                    try:
                                        pre_plain = msg_el.get_attribute("data-pre-plain-text") or ""
                                        sender = pre_plain.split("] ")[-1].rstrip(": ") if "] " in pre_plain else chat_name
                                    except Exception:
                                        sender = chat_name
                                    filename, content = message_to_markdown(sender, chat_name, text)
                                    (INBOX_DIR / filename).write_text(content, encoding="utf-8")
                                    log.info("Saved WhatsApp message -> %s", filename)
                                    count += 1
                                else:
                                    log.debug("Skipped (no keyword match): %s", text[:60])
                            except Exception as e:
                                log.debug("Error reading message: %s", e)
                    except Exception as e:
                        log.debug("Error processing chat: %s", e)

            except Exception as e:
                log.error("Scan error: %s", e)
            return count

        def is_page_alive() -> bool:
            try:
                page.title()
                return True
            except Exception:
                return False

        def reconnect() -> bool:
            """Try to reopen WhatsApp Web on the existing browser context."""
            nonlocal page
            log.warning("[WA] Page died — reconnecting...")
            try:
                page = browser.new_page()
                page.goto("https://web.whatsapp.com", timeout=60000, wait_until="domcontentloaded")
                page.wait_for_selector(
                    '[data-testid="chat-list"], #side, [aria-label="Chat list"]',
                    timeout=60000
                )
                log.info("[WA] Reconnected successfully.")
                return True
            except Exception as exc:
                log.error("[WA] Reconnect failed: %s", exc)
                return False

        if daemon:
            log.info("Daemon mode — scanning every %ds. Press Ctrl+C to stop.", POLL_INTERVAL_SECONDS)
            try:
                while True:
                    if not is_page_alive():
                        if not reconnect():
                            log.error("[WA] Could not reconnect — waiting 30s before retry...")
                            time.sleep(30)
                            continue
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
