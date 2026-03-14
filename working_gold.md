# Gold Tier — Working Guide

This document explains every Gold Tier feature, how it works end-to-end, and how to set it up.

---

## Feature 1: Multiple MCP Servers

### What It Does
Gives Claude Code direct access to Calendar, LinkedIn, Facebook, Instagram, and a real browser — as MCP tools you can call in any conversation.

### Servers Registered (`.mcp.json`)

| Server | File | What It Connects To |
|--------|------|---------------------|
| `calendar` | `calendar_mcp_server.py` | Google Calendar API |
| `linkedin` | `linkedin_mcp_server.py` | LinkedIn API (via `linkedin_poster.py`) |
| `facebook` | `facebook_mcp_server.py` | Facebook Graph API (Page posts) |
| `instagram` | `instagram_mcp_server.py` | Instagram Graph API (Business posts) |
| `browser` | `@playwright/mcp` (npm) | Real Chromium browser automation |
| `gmail` | `gmail_mcp_server.py` | Gmail API (already active) |
| `filesystem` | `@modelcontextprotocol/server-filesystem` | Vault/ read/write |
| `github` | `@modelcontextprotocol/server-github` | GitHub repo access |

### Available Tools Per Server

**Calendar (`calendar_mcp_server.py`)**
- `calendar_create_event` — create a Google Calendar event
- `calendar_list_events` — list upcoming events
- `calendar_update_event` — update an existing event
- `calendar_delete_event` — delete an event

**LinkedIn (`linkedin_mcp_server.py`)**
- `linkedin_generate_post` — generate a post draft → `Vault/Pending_Approval/`
- `linkedin_publish_post` — publish approved post from `Vault/Approved/`
- `linkedin_get_profile` — get your LinkedIn profile info

**Facebook (`facebook_mcp_server.py`)**
- `facebook_generate_post` — AI-generate a post draft → `Vault/Pending_Approval/`
- `facebook_publish_approved` — publish approved posts from `Vault/Approved/`
- `facebook_get_page_info` — get Page name, fans, category

**Instagram (`instagram_mcp_server.py`)**
- `instagram_generate_post` — AI-generate a caption draft → `Vault/Pending_Approval/`
- `instagram_publish_approved` — publish approved posts from `Vault/Approved/`
- `instagram_get_account` — get account username, followers, media count

### Setup Steps

**Google Calendar:**
```bash
# First run triggers OAuth browser flow (separate from Gmail)
uv run python calendar_mcp_server.py
# Approve in browser → saves calendar_token.json
```

**LinkedIn:**
```bash
# Add to .env:
LINKEDIN_CLIENT_ID=your_client_id
LINKEDIN_CLIENT_SECRET=your_client_secret

# Run OAuth flow:
uv run python linkedin_poster.py --auth
```

**Facebook:**
```bash
# Add to .env:
FACEBOOK_PAGE_ACCESS_TOKEN=your_page_token
FACEBOOK_PAGE_ID=your_page_id
```

**Instagram:**
```bash
# Add to .env (uses same token as Facebook):
FACEBOOK_PAGE_ACCESS_TOKEN=your_page_token
INSTAGRAM_ACCOUNT_ID=your_instagram_business_account_id
```

**Browser (no setup needed):**
```bash
# Installed automatically via npx on first use
```

---

## Feature 2: Social Media Scheduling

### What It Does
Automatically generates post drafts for Facebook, Instagram, and LinkedIn on a fixed weekly schedule. You review and approve each draft before anything is published.

### Schedule

| Platform | Days | Time |
|----------|------|------|
| Facebook + Instagram | Monday, Wednesday & Friday | 9:00 AM |
| LinkedIn | Monday, Wednesday & Friday | 9:00 AM |

### Flow

```
social_scheduler.py runs on schedule
        ↓
Generates draft via Groq AI
        ↓
Saves to Vault/Pending_Approval/
   FACEBOOK_POST_YYYYMMDD_HHMMSS.md
   INSTAGRAM_POST_YYYYMMDD_HHMMSS.md
   LINKEDIN_POST_YYYYMMDD_HHMMSS.md
        ↓
YOU review the draft in Obsidian
        ↓
Move file to Vault/Approved/
        ↓
approval_watcher.py detects it
        ↓
Publishes to the platform → Vault/Done/
```

### Manual Usage

```bash
# Generate one draft now:
uv run python social_scheduler.py --facebook
uv run python social_scheduler.py --instagram
uv run python social_scheduler.py --linkedin

# Generate all three at once:
uv run python social_scheduler.py --all

# With a custom topic:
uv run python social_scheduler.py --all --topic "our new product launch"
```

### Instagram Note
Instagram requires an image. After generating the draft, open the file in Obsidian and fill in the `image_url:` field in the frontmatter with a publicly accessible image URL before moving to Approved/.

### Install Windows Scheduled Tasks
```bash
# Run as Administrator:
python schedule_setup.py --install
```

---

## Feature 3: Ralph Wiggum Autonomous Loop

### What It Does
The reasoning loop can now **auto-execute low-risk plans** without waiting for human approval. It also detects **stuck tasks** and escalates them to you as a CEO Briefing note.

### Two Paths Based on Plan Risk

```
Needs_Action/task.md
        ↓
reasoning_loop.py generates plan
        ↓
    approval_needed: no?
    ├── YES → auto-execute immediately (no human needed)
    │          ↓
    │    Plan copied to Approved/ → approval_watcher executes it → Done/
    │
    └── NO  → move to Pending_Approval/
               ↓
          YOU review → move to Approved/ → execution → Done/
```

### Low-Risk vs High-Risk

The AI router (`router.py`) sets `approval_needed` in the plan frontmatter:

- **`approval_needed: no`** — purely informational, internal note, no external action
- **`approval_needed: yes`** — anything that sends email, posts to social media, sends WhatsApp, or involves payments

### Stuck Task Escalation

If the same task appears in `Needs_Action/` more than **3 times** without being resolved:

1. The reasoning loop writes a `CEO_BRIEFING_*.md` to `Needs_Action/`
2. The briefing contains the original task content and asks for manual intervention
3. Retry counts are tracked in `reasoning_retries.json`

### Files Involved
- `reasoning_loop.py` — main loop with auto-execute and retry logic
- `reasoning_retries.json` — per-task retry counter (auto-created)

### Run Manually
```bash
# Process all unplanned Needs_Action items once:
uv run python reasoning_loop.py

# Run as daemon (every 10 minutes):
uv run python reasoning_loop.py --daemon
```

---

## Feature 4: Weekly CEO Briefing

### What It Does
Every **Sunday at 10 PM**, scans the entire Vault for the past 7 days of activity and emails you a structured business briefing.

### Briefing Contents
- Items completed this week (emails, WhatsApp, plans, social posts)
- Current open items in Needs_Action
- Items awaiting your approval
- New inbox items
- Recent system activity log
- AI-generated executive summary with risks and recommended actions

### Delivery
1. **Preferred:** Email sent to `CEO_EMAIL` from your Gmail account
2. **Fallback:** If email fails, briefing saved to `Vault/Needs_Action/CEO_BRIEFING_*.md`

### Setup
```bash
# Add to .env:
CEO_EMAIL=your@email.com
```

### Schedule
- Windows Task: `AIEmployee_CEOBriefing` — runs every Sunday at 10:00 PM

### Run Manually
```bash
# Send the briefing now:
uv run python ceo_briefing.py

# Preview without sending:
uv run python ceo_briefing.py --dry-run
```

---

## Feature 5: Error Recovery & Graceful Degradation

### What It Does
Wraps every pipeline stage in error handling. If anything fails, the system:
1. Logs the error
2. Writes a recovery note to `Vault/Needs_Action/ERROR_component_timestamp.md`
3. Includes an intelligent recovery suggestion
4. Continues running (does NOT crash)

### Health Check

Run at any time to check all pipeline components:

```bash
uv run python error_recovery.py --health
```

Output example:
```
==================================================
  AI Employee Health Check — 2026-03-14 10:00
==================================================
  ✅ groq                     Response OK
  ✅ gmail_token               Token file exists
  ⚠️ calendar_token           calendar_token.json missing — run calendar_mcp_server.py once
  ✅ whatsapp_session          Session dir exists
  ✅ vault_inbox               Vault/Inbox exists
  ✅ vault_needs_action        Vault/Needs_Action exists
  ✅ vault_done                Vault/Done exists
==================================================
  6/7 components healthy
==================================================
```

### Stale Inbox Recovery

Items sitting in `Vault/Inbox/` for more than 24 hours are automatically moved to `Needs_Action/`:

```bash
uv run python error_recovery.py --recover-inbox
```

This also runs automatically every time `main.py` starts.

### Recovery Note Format

When a component fails, `Vault/Needs_Action/ERROR_component_timestamp.md` is created with:
- Which component failed and what it was doing
- The error message
- A recovery suggestion (auth fix, restart command, etc.)
- Full Python traceback

### Startup Health Check
`main.py` runs a health check automatically on every startup and logs any issues.

---

## Complete Gold Tier Pipeline

```
                    ┌─────────────────────────────────────────────────┐
                    │           AI Vault Pipeline (main.py)           │
                    │                                                 │
  Gmail (2min) ─────┤──► Inbox/ ──► Triage ──► Needs_Action/        │
  WhatsApp (30s) ───┤                                ↓               │
                    │                     reasoning_loop.py          │
  Social Scheduler  │                    (plan generation)            │
  Tue/Thu FB+IG ────┤                          ↓                     │
  Mon/Wed LinkedIn ─┤              approval_needed: no?              │
                    │                 ├── YES → auto-execute          │
                    │                 └── NO  → Pending_Approval/     │
                    │                               ↓                │
                    │                    YOU review in Obsidian       │
                    │                               ↓                │
                    │              Move to Approved/ → Execute        │
                    │                               ↓                │
                    │         WhatsApp reply / Email / Social post    │
                    │                               ↓                │
                    │                            Done/                │
                    │                                                 │
  Sunday 10PM ──────┤──► ceo_briefing.py ──► Email you summary      │
                    │                                                 │
  Error anywhere ───┤──► error_recovery.py ──► Needs_Action/ note   │
                    └─────────────────────────────────────────────────┘
```

---

## Quick Command Reference

```bash
# Start the full pipeline:
uv run python main.py

# Health check:
uv run python error_recovery.py --health

# Generate social posts now:
uv run python social_scheduler.py --all

# Send CEO briefing now (preview):
uv run python ceo_briefing.py --dry-run

# Process Needs_Action items (plan generation):
uv run python reasoning_loop.py

# Install all Windows scheduled tasks (run as Admin):
python schedule_setup.py --install

# Check scheduled task status:
python schedule_setup.py --status
```

---

## Required .env Variables (Gold Tier)

```env
# CEO Briefing
CEO_EMAIL=your@email.com

# LinkedIn
LINKEDIN_CLIENT_ID=your_client_id
LINKEDIN_CLIENT_SECRET=your_client_secret

# Facebook + Instagram
FACEBOOK_PAGE_ACCESS_TOKEN=your_page_access_token
FACEBOOK_PAGE_ID=your_page_id
INSTAGRAM_ACCOUNT_ID=your_instagram_business_account_id
```
