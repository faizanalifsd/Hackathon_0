# Silver Tier — Setup & Testing Guide

---

## ✅ Current Working State (as of 2026-03-10)

### How to Run Everything
```bash
uv run python main.py
```
That's it. One command starts the full pipeline.

### What `main.py` Does
It runs 4 watchers + Gmail poller in a single process:

| Watcher | Watches | Triggers |
|---------|---------|----------|
| InboxHandler | `Vault/Inbox/` | Calls Claude to triage → moves to `Needs_Action/` |
| NeedsActionHandler | `Vault/Needs_Action/` | Calls Claude to generate plan → writes to `Plans/` |
| PlansHandler | `Vault/Plans/` | Reads plan frontmatter → moves to `Pending_Approval/` |
| ApprovedHandler | `Vault/Approved/` | Calls Claude to execute plan → sends email → moves to `Done/` |
| Gmail Poller | Gmail API | Every 2 min → fetches unread important emails → saves to `Inbox/` |

### Full Pipeline Flow
```
Gmail
  ↓ (every 2 min)
Vault/Inbox/            ← email saved here as .md file
  ↓ (InboxHandler fires on new file)
Vault/Needs_Action/     ← triage stamps frontmatter + classifies email
  ↓ (NeedsActionHandler fires on new file)
Vault/Plans/            ← Claude generates structured PLAN_*.md
  ↓ (PlansHandler fires on new file)
Vault/Pending_Approval/ ← plan waiting for YOUR review
  ↓ (YOU move the file to Approved/)
Vault/Approved/         ← ApprovedHandler fires
  ↓ (Claude executes: sends reply email via Gmail)
Vault/Done/             ← PLAN_*.md + REPORT_*.md saved here
```

### Your Only Job
1. Run `uv run python main.py`
2. Wait for emails to appear in `Vault/Pending_Approval/`
3. Review the plan file in Obsidian
4. If you agree → move the file to `Vault/Approved/`
5. The pipeline sends the email and archives everything to `Done/`

### How to Approve a Plan
**In terminal:**
```bash
mv "E:/Hackathon_0/Vault/Pending_Approval/PLAN_<filename>.md" "E:/Hackathon_0/Vault/Approved/"
```
**In Obsidian:** drag the file from `Pending_Approval/` → `Approved/` folder.

### Known Behaviours
- Watchers only fire on **new** file events — files already in a folder when `main.py` starts are NOT auto-processed
- If files are stuck in `Inbox/`, manually move them: `mv Vault/Inbox/*.md Vault/Needs_Action/`
- Plan generation via Claude takes ~60 seconds per email — keep `main.py` running
- Dashboard.md auto-updates after each pipeline step

### Folder Counts (Dashboard)
| Folder | Meaning |
|--------|---------|
| Inbox | Emails just fetched, not yet triaged |
| Needs Action | Triaged emails waiting for plan generation |
| Plans | Plans generated, being routed |
| Pending Approval | Plans waiting for YOUR approval |
| Approved (awaiting execution) | You approved, executing now |
| Done | Completed — email sent and archived |

---

## Prerequisites
- Bronze Tier complete and verified
- Terminal open at `E:/Hackathon_0/`
- Obsidian open with the `Vault/` folder

---

## Step 1 — One-Time Setup: Install Playwright Browser

Run in terminal:

```bash
cd E:/Hackathon_0
uv run playwright install chromium
```

**Pass:** Prints `Chromium X.X.X downloaded` without errors.

---

## Step 2 — One-Time Setup: Gmail API Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or select existing)
3. Enable **Gmail API** → APIs & Services → Enable APIs → search "Gmail API"
4. Create credentials → OAuth 2.0 Desktop App → Download as `credentials.json`
5. Place `credentials.json` in `E:/Hackathon_0/`
6. Run the Gmail watcher once to complete OAuth:

```bash

```

A browser window will open. Sign in and allow permissions.
A `token.json` file will be saved — **do not commit it to Git.**

**Pass:** Terminal prints `Gmail Watcher started.` then `Done. Fetched X email(s).`

---

## Step 3 — One-Time Setup: LinkedIn API (Optional)

1. Go to [LinkedIn Developer Apps](https://www.linkedin.com/developers/apps)
2. Create an app → request `r_liteprofile` + `w_member_social` permissions
3. Copy Client ID and Client Secret into `E:/Hackathon_0/.env`:

```env
LINKEDIN_CLIENT_ID=your_client_id_here
LINKEDIN_CLIENT_SECRET=your_client_secret_here
```

4. Run the OAuth flow:

```bash
python linkedin_poster.py --auth
```

A browser opens for LinkedIn sign-in. Token saved to `linkedin_token.json`.

**Pass:** Terminal prints `Token saved to linkedin_token.json`

---

## Step 4 — One-Time Setup: Copy .env

```bash
cp E:/Hackathon_0/.env.example E:/Hackathon_0/.env
```

Edit `.env` and fill in your values (LinkedIn credentials, keyword overrides).

---

## Step 5 — Test: Gmail Watcher

With `credentials.json` and `token.json` in place:

```bash
python gmail_watcher.py
```

**Pass:** Any unread important Gmail messages appear as `.md` files in `Vault/Inbox/`.

To run as a daemon (polls every 5 minutes):

```bash
python gmail_watcher.py --daemon
```

---

## Step 6 — Test: WhatsApp Watcher

```bash
python whatsapp_watcher.py
```

1. A Chromium browser window opens with WhatsApp Web
2. Scan the QR code with your phone (WhatsApp → Linked Devices → Link a Device)
3. The watcher scans for messages containing keywords: `urgent, asap, invoice, payment, meeting`
4. Any matching messages are saved as `.md` files in `Vault/Inbox/`

Session is saved in `whatsapp_session/` — subsequent runs skip the QR scan.

**Pass:** Terminal prints `WhatsApp Web loaded.` and eventually `Done. Captured X message(s).`

To run as a daemon (polls every 60 seconds):

```bash
python whatsapp_watcher.py --daemon
```

---

## Step 7 — Test: Reasoning Loop (Needs_Action → Plans)

First, drop a test item into `Vault/Needs_Action/`:

```bash
cp E:/Hackathon_0/Vault/Inbox/ E:/Hackathon_0/Vault/Needs_Action/test_silver.md
```

Or create one manually in Obsidian. Then run:

```bash
python reasoning_loop.py
```

**Pass:**
- `Vault/Plans/PLAN_test_silver.md` is created with a structured plan
- If the plan contains email/social/payment steps → it moves to `Vault/Pending_Approval/`
- Dashboard.md updates with new counts
- `Vault/Logs/YYYY-MM-DD.json` has a `plan_generated` entry

---

## Step 8 — Test: HITL Approval Workflow

After Step 7, you should have a file in `Vault/Pending_Approval/`.

**To approve it:**

In Obsidian: drag the file from `Pending_Approval/` → `Approved/`

Or in terminal:

```bash
mv "E:/Hackathon_0/Vault/Pending_Approval/PLAN_test_silver.md" \
   "E:/Hackathon_0/Vault/Approved/PLAN_test_silver.md"
```

Then run the approval watcher:

```bash
python approval_watcher.py
```

**Pass:**
- `Vault/Done/PLAN_test_silver.md` exists
- `Vault/Done/REPORT_PLAN_test_silver.md` exists with an execution report
- `Vault/Logs/YYYY-MM-DD.json` has a `plan_executed` entry
- Dashboard.md shows updated Done count

---

## Step 9 — Test: LinkedIn Post Generation

```bash
python linkedin_poster.py --generate
```

**Pass:** A draft file `LINKEDIN_POST_<timestamp>.md` appears in `Vault/Pending_Approval/`

To publish approved posts (after moving the file to `Vault/Approved/`):

```bash
python linkedin_poster.py --post
```

---

## Step 10 — Full End-to-End Flow Test

This tests the complete Silver pipeline:

```
WhatsApp keyword → Watcher → Inbox → Triage → Needs_Action
→ Reasoning Loop → Plans → Pending_Approval
→ You Approve → Approved → Approval Watcher → Done
```

1. Start WhatsApp watcher in daemon mode (Terminal 1):
   ```bash
   python whatsapp_watcher.py --daemon
   ```

2. Start approval watcher in daemon mode (Terminal 2):
   ```bash
   python approval_watcher.py --daemon
   ```

3. Send a WhatsApp message to yourself containing the word `urgent`

4. Check `Vault/Inbox/` — a new `.md` file should appear within 60 seconds

5. Trigger triage (Terminal 3):
   ```bash
   claude --print "Use the vault-triage skill to process any new inbox items"
   ```

6. Run reasoning loop:
   ```bash
   python reasoning_loop.py
   ```

7. Review the plan in `Vault/Pending_Approval/` (open Obsidian)

8. Move the plan to `Vault/Approved/` — the approval watcher picks it up automatically

9. Check `Vault/Done/` — task and report should both be there

**Pass:** Full pipeline completed without manual intervention after Step 8.

---

## Step 11 — Set Up Windows Task Scheduler

Run as **Administrator**:

```bash
python schedule_setup.py --install
```

This creates 4 scheduled tasks:

| Task | Schedule | Script |
|------|----------|--------|
| `AIEmployee_GmailFetch` | Every hour | `gmail_watcher.py` |
| `AIEmployee_DailyBriefing` | Daily 8:00 AM | `reasoning_loop.py` |
| `AIEmployee_LinkedInPost` | Daily 9:00 AM | `linkedin_poster.py --generate` |
| `AIEmployee_ApprovalWatcher` | On login | `approval_watcher.py --daemon` |

Verify tasks are installed:

```bash
python schedule_setup.py --status
```

**Pass:** All 4 tasks show status `Ready` or `Running`.

---

## Step 12 — Verify Agent Skills

```bash
ls E:/Hackathon_0/.claude/skills/vault-reasoning/
ls E:/Hackathon_0/.claude/skills/vault-execute/
ls E:/Hackathon_0/.claude/skills/hitl-approve/
```

**Pass:** All three print `SKILL.md`.

Test the reasoning skill directly in Claude Code:

```
generate plans for all items in Needs_Action
```

```
show pending approvals
```

---

## Summary Checklist

- [ ] Step 1 — Playwright Chromium installed
- [ ] Step 2 — Gmail OAuth complete (`token.json` exists)
- [ ] Step 3 — LinkedIn OAuth complete (optional)
- [ ] Step 4 — `.env` file created from `.env.example`
- [ ] Step 5 — Gmail Watcher fetches emails → Vault/Inbox/
- [ ] Step 6 — WhatsApp Watcher captures messages → Vault/Inbox/
- [ ] Step 7 — Reasoning Loop generates PLAN files
- [ ] Step 8 — HITL Approval Workflow moves tasks to Done
- [ ] Step 9 — LinkedIn Post draft generated → Pending_Approval
- [ ] Step 10 — Full end-to-end pipeline test passed
- [ ] Step 11 — Windows Task Scheduler tasks installed
- [ ] Step 12 — All 3 Silver Agent Skills present

**All 12 pass → Silver Tier confirmed. Tell Claude to proceed to Gold.**

---

## Quick Reference: Silver Tier Commands

> **Note:** `python` is NOT mandatory. All packages are already installed in `.venv`.
> You can activate the venv once and then just use `python` directly:
>
> ```bash
> # Activate venv (do this once per terminal session)
> source E:/Hackathon_0/.venv/Scripts/activate
>
> # Then use python directly for all commands below
> python gmail_watcher.py --daemon
> ```
>
> Or keep using `python` — both work identically.

```bash
# Watchers
python watcher.py                        # File system watcher (Bronze)
python gmail_watcher.py --daemon         # Gmail daemon
python whatsapp_watcher.py --daemon      # WhatsApp daemon

# AI Loops
python reasoning_loop.py                 # Generate plans once
python reasoning_loop.py --daemon        # Generate plans every 10 min
python approval_watcher.py               # Execute approved items once
python approval_watcher.py --daemon      # Watch Approved/ continuously

# LinkedIn
python linkedin_poster.py --generate     # Generate post draft
python linkedin_poster.py --post         # Publish approved posts
python linkedin_poster.py --auth         # Re-run OAuth flow

# Scheduling (run as Administrator)
python schedule_setup.py --install       # Install all tasks
python schedule_setup.py --status        # Check task status
python schedule_setup.py --remove        # Remove all tasks

# Vault
python vault_io.py                       # List all folders + update dashboard
```

---

## Pipeline Rules (Silver)

| Stage | Who moves it | Condition |
|-------|-------------|-----------|
| Inbox → Needs_Action | Claude (vault-triage) | Always |
| Needs_Action → Plans | reasoning_loop.py | Always |
| Plans → Pending_Approval | reasoning_loop.py | If approval needed |
| Pending_Approval → Approved | **You** | After your review |
| Approved → Done | approval_watcher.py | After execution |
| Needs_Action → Done | **You** | If test/dummy item |
