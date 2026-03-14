"""
wa_send_once.py — One-shot WhatsApp message sender.

Opens the existing WhatsApp Web session, sends one message, closes.

Usage:
    uv run python wa_send_once.py "Zeeshan Jutt" "Your message here"
"""

import sys
import time
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("wa_send_once")

BASE_DIR = Path(__file__).parent
SESSION_DIR = BASE_DIR / "whatsapp_session"


def send_once(chat_name: str, message: str) -> bool:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=False,
            args=["--no-sandbox"],
        )

        page = browser.new_page()

        log.info("Opening WhatsApp Web...")
        page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")

        # Wait until WhatsApp loads (chat list appears)
        log.info("Waiting for WhatsApp to load (up to 120s)...")
        try:
            page.wait_for_selector(
                '[data-testid="chat-list"], #side, [aria-label="Chat list"], [data-testid="search"]',
                timeout=120_000,
            )
        except Exception:
            log.error("WhatsApp did not load in time.")
            browser.close()
            return False

        log.info("WhatsApp loaded. Searching for chat: '%s'", chat_name)
        time.sleep(2)

        # Find search box
        search_box = None
        for sel in [
            '[data-testid="search"]',
            'div[contenteditable="true"][data-tab="3"]',
            '[title="Search input textbox"]',
        ]:
            el = page.query_selector(sel)
            if el:
                search_box = el
                break

        if not search_box:
            log.error("Could not find search box.")
            browser.close()
            return False

        search_box.click()
        time.sleep(0.5)
        page.keyboard.press("Control+a")
        page.keyboard.press("Delete")
        page.keyboard.type(chat_name, delay=50)
        time.sleep(2.5)

        # Exact match click — click the title span itself (more reliable than clicking row container)
        clicked = False
        for row_sel in [
            '[data-testid="cell-frame-container"]',
            '[role="listitem"]',
            'div[tabindex="-1"]',
            'li',
        ]:
            rows = page.query_selector_all(row_sel)
            for row in rows:
                try:
                    title_el = (row.query_selector('span[title]') or
                                row.query_selector('span[dir="auto"]'))
                    if title_el:
                        name = (title_el.get_attribute("title") or title_el.inner_text()).strip()
                        if name.lower() == chat_name.lower():
                            # Try clicking the row first, fall back to title element
                            try:
                                row.click()
                            except Exception:
                                title_el.click()
                            clicked = True
                            log.info("Exact match found: '%s' — clicking row.", name)
                            break
                except Exception:
                    continue
            if clicked:
                break

        # If row click didn't open chat, try clicking the title span directly
        if clicked:
            time.sleep(2)
            # Check if chat opened
            check_sel = page.query_selector(
                '[data-testid="conversation-info-header-chat-title"], header span[title]'
            )
            if not check_sel or not check_sel.inner_text().strip():
                log.info("Row click didn't open chat — trying direct span click...")
                for row_sel in ['[data-testid="cell-frame-container"]', '[role="listitem"]', 'div[tabindex="-1"]', 'li']:
                    rows = page.query_selector_all(row_sel)
                    for row in rows:
                        try:
                            title_el = (row.query_selector('span[title]') or row.query_selector('span[dir="auto"]'))
                            if title_el:
                                name = (title_el.get_attribute("title") or title_el.inner_text()).strip()
                                if name.lower() == chat_name.lower():
                                    title_el.click()
                                    log.info("Clicked title span directly for '%s'.", name)
                                    break
                        except Exception:
                            continue

        if not clicked:
            # Debug: screenshot + show what names were found
            screenshot_path = str(BASE_DIR / "wa_debug.png")
            page.screenshot(path=screenshot_path)
            log.error("Screenshot saved: %s", screenshot_path)

            found_names = []
            for row_sel in ['[data-testid="cell-frame-container"]', '[role="listitem"]',
                            'div[tabindex="-1"]', 'li', 'div[role="row"]']:
                rows = page.query_selector_all(row_sel)
                for row in rows:
                    try:
                        title_el = (row.query_selector('span[title]') or
                                    row.query_selector('span[dir="auto"]') or
                                    row.query_selector('span'))
                        if title_el:
                            name = (title_el.get_attribute("title") or title_el.inner_text()).strip()
                            if name and len(name) > 1:
                                found_names.append(name)
                    except Exception:
                        continue
            log.error("No exact match for '%s' in search results.", chat_name)
            log.error("Names found: %s", list(dict.fromkeys(found_names))[:15])
            browser.close()
            return False

        time.sleep(2)

        # Safety: verify correct chat opened.
        # Filter out subtitle/status lines that WhatsApp shows below the contact name.
        INVALID_NAMES = {"last seen", "online", "click here", "contact info", "unknown", "typing"}
        def is_valid_chat_name(n: str) -> bool:
            n_lower = n.lower()
            return bool(n) and not any(bad in n_lower for bad in INVALID_NAMES)

        open_chat_name = ""
        for sel in [
            '[data-testid="conversation-info-header-chat-title"]',
            'header span[title]',
            '#main header span[dir="auto"]',
        ]:
            els = page.query_selector_all(sel)
            for el in els:
                candidate = (el.get_attribute("title") or el.inner_text()).strip()
                if is_valid_chat_name(candidate):
                    open_chat_name = candidate
                    break
            if open_chat_name:
                break

        if open_chat_name.lower() != chat_name.lower():
            log.info("Chat header is '%s' — checking for contact card 'Message' button...", open_chat_name)
            # Try to find and click the "Message" button on the contact card
            msg_btn = None
            for btn_sel in [
                '[data-testid="open-chat"]',
                'button[aria-label*="Message"]',
                'div[role="button"][title*="Message"]',
                'span[data-icon="chat"]',
            ]:
                el = page.query_selector(btn_sel)
                if el:
                    msg_btn = el
                    break

            if not msg_btn:
                # Try finding any button with message-like text
                buttons = page.query_selector_all('button, div[role="button"]')
                for btn in buttons:
                    try:
                        txt = btn.inner_text().strip().lower()
                        if txt in ("message", "send message", "chat"):
                            msg_btn = btn
                            break
                    except Exception:
                        continue

            if msg_btn:
                log.info("Found 'Message' button — clicking to open DM chat.")
                msg_btn.click()
                time.sleep(2.5)
                # Re-check header
                for sel in [
                    '[data-testid="conversation-info-header-chat-title"]',
                    'header span[title]',
                    '#main header span[dir="auto"]',
                ]:
                    el = page.query_selector(sel)
                    if el:
                        open_chat_name = (el.get_attribute("title") or el.inner_text()).strip()
                        if open_chat_name:
                            break

            if open_chat_name.lower() != chat_name.lower():
                log.error("Safety check FAILED — open chat is '%s', expected '%s'. Aborting.",
                          open_chat_name, chat_name)
                page.screenshot(path=str(BASE_DIR / "wa_debug.png"))
                browser.close()
                return False

        log.info("Safety check passed — '%s' is open.", open_chat_name)

        # Find compose box and type message
        compose_box = None
        for sel in [
            'div[contenteditable="true"][data-tab="10"]',
            'div[contenteditable="true"][spellcheck="true"]',
            'footer div[contenteditable="true"]',
            'div[contenteditable="true"]',
        ]:
            el = page.query_selector(sel)
            if el:
                compose_box = el
                break

        if not compose_box:
            log.error("Could not find compose box.")
            browser.close()
            return False

        compose_box.click()
        time.sleep(0.3)
        page.keyboard.type(message, delay=30)
        time.sleep(0.3)
        page.keyboard.press("Enter")
        time.sleep(2)

        log.info("✅ Message sent to '%s'", chat_name)
        browser.close()
        return True


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: uv run python wa_send_once.py \"Chat Name\" \"Message text\"")
        sys.exit(1)

    chat = sys.argv[1]
    msg = sys.argv[2]

    log.info("Sending to: %s", chat)
    log.info("Message: %s", msg)

    ok = send_once(chat, msg)
    sys.exit(0 if ok else 1)
