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
import queue
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
VAULT_ROOT = BASE_DIR / "Vault"
INBOX_DIR = VAULT_ROOT / "Inbox"
SESSION_DIR = BASE_DIR / "whatsapp_session"
LOG_FILE = BASE_DIR / "whatsapp_watcher.log"
SEEN_IDS_FILE = BASE_DIR / "whatsapp_seen.json"  # persists seen message IDs across restarts

# Keywords to filter — empty list = capture all new messages
WATCH_KEYWORDS_DEFAULT = []  # empty = capture ALL messages
POLL_INTERVAL_SECONDS = 30  # check every 30 seconds in daemon mode
SCAN_DURATION_SECONDS = 15  # how long to scan for new messages each poll

# ---------------------------------------------------------------------------
# Outgoing message queue  (approval_watcher puts items here; watcher sends them)
# ---------------------------------------------------------------------------

# Each item: (chat_name: str, message: str, result: list[bool], done_event: threading.Event)
_send_queue: queue.Queue = queue.Queue()


def send_whatsapp_message(chat_name: str, message: str, timeout: int = 90) -> bool:
    """
    Thread-safe: enqueue a message for the running watcher to send.
    Blocks until the watcher confirms it was sent (or timeout).
    """
    result = [False]
    done = threading.Event()
    _send_queue.put((chat_name, message, result, done))
    done.wait(timeout=timeout)
    return result[0]


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

def load_seen_ids() -> set:
    """Load persisted seen message IDs from disk."""
    import json
    if SEEN_IDS_FILE.exists():
        try:
            return set(json.loads(SEEN_IDS_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_seen_ids(seen: set):
    """Persist seen message IDs to disk."""
    import json
    try:
        SEEN_IDS_FILE.write_text(json.dumps(list(seen)), encoding="utf-8")
    except Exception as e:
        log.warning("Could not save seen IDs: %s", e)


def get_keywords() -> list[str]:
    raw = os.environ.get("WHATSAPP_KEYWORDS", "")
    if raw:
        return [k.strip().lower() for k in raw.split(",") if k.strip()]
    return [k.lower() for k in WATCH_KEYWORDS_DEFAULT]


def message_matches(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return False  # No keywords configured → capture nothing
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
    log.info("Watching for keywords: %s", keywords if keywords else "(none — no messages will be captured)")

    seen_message_ids: set[str] = load_seen_ids()
    log.info("Loaded %d seen message IDs from disk.", len(seen_message_ids))

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
                        # Read unread count from badge BEFORE clicking (clicking clears it)
                        unread_count = 10  # safe fallback
                        try:
                            badge_text = badge.inner_text().strip()
                            if badge_text.isdigit():
                                unread_count = int(badge_text)
                        except Exception:
                            pass

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
                        time.sleep(1)

                        # Get chat name — try title attribute first (avoids "last seen" text)
                        INVALID_NAMES = {"last seen", "online", "click here", "contact info", "unknown"}

                        def is_valid_name(n: str) -> bool:
                            n_lower = n.lower()
                            return bool(n) and not any(bad in n_lower for bad in INVALID_NAMES)

                        chat_name = "Unknown"
                        for sel in [
                            '[data-testid="conversation-info-header-chat-title"]',
                            'header [data-testid="conversation-title"]',
                            'header span[title]',
                            '#main header span[dir="auto"][title]',
                            '#main header span[dir="auto"]',
                        ]:
                            el = page.query_selector(sel)
                            if el:
                                name = el.get_attribute("title") or el.inner_text().strip()
                                if is_valid_name(name):
                                    chat_name = name
                                    break

                        if chat_name == "Unknown":
                            log.warning("Skipping chat — could not resolve contact name (contact not saved?).")
                            continue

                        log.info("[WA] Opened chat: '%s' | unread: %d", chat_name, unread_count)

                        # Strategy: find the "Unread messages" divider WhatsApp inserts
                        # in the conversation. All messages AFTER it are truly unread.
                        # If the divider is not found, fall back to last unread_count messages.
                        import hashlib

                        def extract_text(el) -> str:
                            """Extract clean message text from a message element."""
                            text = ""
                            for text_sel in ['span[dir="ltr"]', 'span[dir="rtl"]', '.copyable-text']:
                                t = el.query_selector(text_sel)
                                if t:
                                    text = t.inner_text().strip()
                                    if text:
                                        break
                            if not text:
                                text = el.inner_text().strip()
                            # Remove timestamp noise and tick marks
                            lines = [l for l in text.splitlines()
                                     if l.strip() and not l.strip().startswith("✓") and not l.strip().startswith("✗")]
                            return "\n".join(lines).strip()

                        def process_message(el) -> bool:
                            """Process a single message element. Returns True if saved."""
                            text = extract_text(el)
                            if not text:
                                return False
                            log.info("[WA] Candidate message: '%s'", text[:100])
                            msg_id = hashlib.md5(f"{chat_name}::{text[:120]}".encode()).hexdigest()[:12]
                            if msg_id in seen_message_ids:
                                log.info("[WA] Already seen (id=%s) — skip.", msg_id)
                                return False
                            seen_message_ids.add(msg_id)
                            save_seen_ids(seen_message_ids)
                            if message_matches(text, keywords):
                                try:
                                    pre_plain = el.get_attribute("data-pre-plain-text") or ""
                                    sender = pre_plain.split("] ")[-1].rstrip(": ") if "] " in pre_plain else chat_name
                                except Exception:
                                    sender = chat_name
                                filename, file_content = message_to_markdown(sender, chat_name, text)
                                (INBOX_DIR / filename).write_text(file_content, encoding="utf-8")
                                log.info("[WA] ✅ Saved -> %s", filename)
                                return True
                            else:
                                log.info("[WA] No keyword match — keywords=%s | text='%s'", keywords, text[:80])
                                return False

                        # Try to find the "Unread messages" divider first
                        unread_divider = None
                        for div_sel in [
                            '[data-testid="unread-notifications"]',
                            'div[role="button"][aria-label*="nread"]',
                            'div.focusable-list-item span',
                        ]:
                            els = page.query_selector_all(div_sel)
                            for el in els:
                                txt = (el.inner_text() or "").lower()
                                if "unread" in txt or "new message" in txt:
                                    unread_divider = el
                                    log.info("[WA] Found unread divider via: %s", div_sel)
                                    break
                            if unread_divider:
                                break

                        if unread_divider:
                            # Get all incoming message elements after the divider
                            all_msgs = page.query_selector_all('div.message-in, [data-testid="msg-container"]')
                            # Use JavaScript to find elements that come after the divider in DOM order
                            try:
                                after_divider = page.evaluate("""(divider) => {
                                    const all = Array.from(document.querySelectorAll('div.message-in, [data-testid="msg-container"]'));
                                    let found = false;
                                    return all.filter(el => {
                                        if (!found) {
                                            const pos = divider.compareDocumentPosition(el);
                                            if (pos & Node.DOCUMENT_POSITION_FOLLOWING) found = true;
                                        }
                                        return found;
                                    }).length;
                                }""", unread_divider)
                                log.info("[WA] Messages after unread divider: %d", after_divider)
                                # Process last N messages (those after the divider)
                                all_msgs = page.query_selector_all('div.message-in, [data-testid="msg-container"]')
                                for msg_el in all_msgs[-max(after_divider, unread_count):]:
                                    try:
                                        if process_message(msg_el):
                                            count += 1
                                    except Exception as e:
                                        log.warning("[WA] Message error: %s", e)
                            except Exception as e:
                                log.warning("[WA] Divider JS failed: %s — using count fallback", e)
                                unread_divider = None  # fall through to count-based

                        if not unread_divider:
                            # Fallback: take last unread_count incoming messages
                            msgs = page.query_selector_all('div.message-in')
                            if not msgs:
                                msgs = page.query_selector_all('[data-testid="msg-container"]')
                            log.info("[WA] Count fallback: %d total msgs, reading last %d", len(msgs), unread_count)
                            for msg_el in msgs[-unread_count:]:
                                try:
                                    if process_message(msg_el):
                                        count += 1
                                except Exception as e:
                                    log.warning("[WA] Message error: %s", e)
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

        def do_send_message(chat_name: str, message: str) -> bool:
            """Send a WhatsApp message to `chat_name` using the current page."""
            try:
                # 1. Open the search box
                search_box = None
                for search_sel in [
                    '[data-testid="search"]',
                    'div[contenteditable="true"][data-tab="3"]',
                    '[title="Search input textbox"]',
                    'div[role="textbox"][title]',
                ]:
                    el = page.query_selector(search_sel)
                    if el:
                        search_box = el
                        break

                if not search_box:
                    log.error("[WA] Could not find search box.")
                    return False

                search_box.click()
                time.sleep(0.5)
                # Select all and delete, then type — fill() doesn't trigger WhatsApp events
                page.keyboard.press("Control+a")
                page.keyboard.press("Delete")
                page.keyboard.type(chat_name, delay=50)
                time.sleep(2.5)  # wait for search results

                # 2. Click the chat row that matches the exact chat name
                clicked = False
                for row_sel in [
                    '[data-testid="cell-frame-container"]',
                    '[role="listitem"]',
                    'div[tabindex="-1"]',
                ]:
                    rows = page.query_selector_all(row_sel)
                    for row in rows:
                        try:
                            # Check title spans inside the row for exact name match
                            title_el = row.query_selector('span[title]') or row.query_selector('span[dir="auto"]')
                            if title_el:
                                name = title_el.get_attribute("title") or title_el.inner_text().strip()
                                if chat_name.lower() in name.lower() or name.lower() in chat_name.lower():
                                    row.click()
                                    clicked = True
                                    break
                        except Exception:
                            continue
                    if clicked:
                        break

                if not clicked:
                    log.error("[WA] Could not find exact chat row for '%s' — aborting to avoid wrong recipient.", chat_name)
                    return False

                time.sleep(2)  # wait for chat to open fully

                # 3. Find and use the compose box
                compose_box = None
                for compose_sel in [
                    'div[contenteditable="true"][data-tab="10"]',
                    'div[contenteditable="true"][spellcheck="true"]',
                    'div[role="textbox"][data-tab="10"]',
                    'footer div[contenteditable="true"]',
                    'div[contenteditable="true"][class*="copyable"]',
                    'div[contenteditable="true"]',  # broad fallback
                ]:
                    el = page.query_selector(compose_sel)
                    if el:
                        compose_box = el
                        break

                if not compose_box:
                    log.error("[WA] Could not find compose box to send reply.")
                    return False

                compose_box.click()
                time.sleep(0.3)
                # Use keyboard.type() not fill() — WhatsApp needs real keystroke events
                page.keyboard.type(message, delay=30)
                time.sleep(0.3)
                page.keyboard.press("Enter")
                time.sleep(1.5)
                log.info("[WA] ✅ Reply sent to '%s'", chat_name)
                return True

            except Exception as exc:
                log.error("[WA] do_send_message failed: %s", exc)
                return False

        def process_send_queue():
            """Process any pending outgoing messages from the send queue."""
            while not _send_queue.empty():
                try:
                    chat_name, message, result, done_event = _send_queue.get_nowait()
                    log.info("[WA] Sending queued reply to '%s'", chat_name)
                    result[0] = do_send_message(chat_name, message)
                    done_event.set()
                except queue.Empty:
                    break
                except Exception as exc:
                    log.error("[WA] Queue processing error: %s", exc)

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
                    # Send any queued outgoing replies BEFORE scanning
                    process_send_queue()
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
