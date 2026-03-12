# WhatsApp Watcher – How It Works

## Overview

`whatsapp_watcher.py` monitors WhatsApp Web via a Playwright-controlled Chromium browser and saves incoming messages as `.md` files into `Vault/Inbox/`.

---

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `POLL_INTERVAL_SECONDS` | 30 | Delay between scans in daemon mode |
| `SCAN_DURATION_SECONDS` | 15 | How long to wait before scanning in one-shot mode |
| `WATCH_KEYWORDS_DEFAULT` | `[]` (empty) | If empty, ALL messages are captured |
| `WHATSAPP_KEYWORDS` env var | — | Comma-separated keywords; overrides the default list |
| `SESSION_DIR` | `whatsapp_session/` | Persistent Chromium profile (saves login session) |
| `INBOX_DIR` | `Vault/Inbox/` | Where captured messages are written |

---

## Modes

### One-Shot Mode (default)
```bash
uv run python whatsapp_watcher.py
```
- Opens browser, waits `SCAN_DURATION_SECONDS` (15s), runs one scan, then exits.

### Daemon Mode
```bash
uv run python whatsapp_watcher.py --daemon
```
- Loops forever: scan → sleep 30s → scan → …
- Handles page death (browser crash / session expiry) via auto-reconnect.

---

## First-Run Setup

1. Run the script — a visible Chromium window opens (headless=False is required).
2. Scan the QR code in WhatsApp on your phone (Settings → Linked Devices).
3. Session cookies are saved in `whatsapp_session/` — subsequent runs skip the QR step.
4. Lock files (`lockfile`, `SingletonLock`, etc.) from crashed sessions are automatically cleared on startup.

---

## Execution Flow

```
main()
 └─ run_watcher(daemon)
      ├─ Clear stale Chrome lock files
      ├─ Launch Playwright persistent Chromium (whatsapp_session/)
      ├─ page.goto("https://web.whatsapp.com")
      ├─ Wait up to 5 min for chat list to appear (QR scan window)
      │
      ├─ [daemon=False]  sleep 15s → scan_once() → close browser
      │
      └─ [daemon=True]   loop:
            ├─ is_page_alive()? → if dead → reconnect()
            └─ scan_once() → sleep 30s → repeat
```

---

## `scan_once()` – Core Scraping Logic

```
1. Find unread chat badges (tries 4 different CSS selectors)
2. For each unread badge:
   a. Walk up the DOM to find the clickable chat row (4 container selectors tried)
   b. Click the row to open the chat; wait 1s
   c. Extract chat name (4 selectors tried)
   d. Extract last 10 messages (4 selectors + fallback to .copyable-text)
   e. For each message:
      - Extract text (4 selectors tried; falls back to full inner_text)
      - Strip lines starting with ✓ (checkmark noise)
      - Compute MD5 fingerprint → skip if already seen (de-duplication)
      - If keyword filter passes → extract sender → write .md to Inbox
```

### Selector Fallback Strategy
WhatsApp Web's CSS class names change frequently. Every DOM query tries multiple selectors in order and stops at the first hit — making the scraper resilient to WhatsApp UI updates.

---

## De-duplication

A seen_message_ids `set` (in-memory, per process run) stores MD5 hashes of `"{chat_name}::{text[:120]}"`. Any message whose fingerprint is already in the set is silently skipped, preventing duplicate Inbox files across repeated scans.

---

## Output File Format

**Filename:**
```
whatsapp_YYYYMMDD_HHMMSS_<ChatName>_<6-char-hash>.md
```
The 6-char MD5 hash of the first 80 chars of the message body prevents collisions when multiple messages arrive from the same chat in the same second.

**File Content:**
```markdown
---
source: whatsapp
received: YYYY-MM-DD HH:MM
status: inbox
priority: medium
tags: [whatsapp]
summary: ""
from: <sender>
chat: <chat_name>
---

# WhatsApp Message from <sender>

**Chat:** <chat_name>
**Time:** YYYY-MM-DD HH:MM

---

<message body>
```

---

## Auto-Reconnect (Daemon Mode)

`is_page_alive()` calls `page.title()` — if the page context is destroyed (browser crash, WhatsApp session expiry), it raises an exception. `reconnect()` then opens a new page on the same browser context and navigates back to `web.whatsapp.com`. If reconnect fails, the loop waits 30s and retries.

---

## Logging

Logs go to both `whatsapp_watcher.log` (file) and stdout. Key log messages:

| Level | Message |
|-------|---------|
| INFO | `WhatsApp Watcher started.` |
| INFO | `Watching for keywords: (all messages)` |
| INFO | `Opening WhatsApp Web...` |
| INFO | `WhatsApp Web loaded.` |
| INFO | `Found N unread chat(s) via selector: ...` |
| INFO | `Saved WhatsApp message -> <filename>` |
| INFO | `Captured N message(s) -> Vault/Inbox/` |
| WARNING | `[WA] Page died — reconnecting...` |
| ERROR | `[WA] Reconnect failed: ...` |
| DEBUG | `Skipped (no keyword match): ...` |

---

## Integration with the Pipeline

```
whatsapp_watcher.py
    → writes .md to Vault/Inbox/
        → vault-triage skill classifies + moves to Needs_Action/ or Done/
            → reasoning_loop.py → Plans/ → Pending_Approval/
                → approval_watcher.py → executes → Done/
```

---

## Known Limitations

- **headless=False required** — WhatsApp Web blocks headless browsers.
- **Seen-set is in-memory** — if the process restarts, messages from the last scan may be re-captured (same fingerprint will produce a new file).
- **Selector fragility** — WhatsApp updates can break selectors; the 4-selector fallback chain mitigates but does not eliminate this.
- **Group chats** — sender name is extracted from `data-pre-plain-text` attribute; falls back to chat name if unavailable.
