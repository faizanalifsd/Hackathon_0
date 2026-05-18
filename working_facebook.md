# Facebook Page Posting — How It Works

## Overview

The Facebook posting system is a 6-stage vault pipeline with human approval built in.
No post ever goes live without you checking a checkbox in Obsidian.

---

## Full Pipeline

```
User runs command  (duplicate check runs here — blocks if same title already queued)
      ↓
[1] Vault/Inbox/          ← fb_request_{timestamp}.md written here
      ↓
[2] Vault/Needs_Action/   ← same file moved, frontmatter stamped
      ↓
[3] Groq API              ← AI generates post text
      ↓
[3] Vault/Plans/          ← PLAN_FACEBOOK_POST_{timestamp}.md written with 2 checkboxes
      ↓
[HUMAN opens Plans/ in Obsidian — read the draft, edit if needed, tick one box]

   - [x] Approve  ──────────────────────────────────────────────────────→ Vault/Approved/
   - [x] Pending  → Vault/Pending_Approval/                                     ↓
                          ↓                                            Facebook Graph API
                  [HUMAN opens Pending_Approval/]                               ↓
                  - [x] Approve  ───────────────────────────────────→ Vault/Approved/
                  - [x] Reject   → Vault/Done/  (discarded)                     ↓
                                                                       Vault/Done/ (archived)
```

---

## Step-by-Step Breakdown

### Step 1 — Duplicate Check + User triggers the request

```bash
python facebook_mcp_server.py --title "your topic" --tone professional
```

Available tones: `professional`, `casual`, `inspirational`, `funny`, `educational`

**Before writing anything**, the script scans these folders for a file whose frontmatter
`title:` matches the requested topic (case-insensitive):
- `Vault/Plans/`
- `Vault/Pending_Approval/`
- `Vault/Approved/`

If a match is found, the command exits with a warning instead of creating a duplicate.

If no duplicate, `cmd_request()` writes `fb_request_{timestamp}.md` to `Vault/Inbox/`.

**File created:** `Vault/Inbox/fb_request_20260517_143000.md`

---

### Step 2 — Inbox → Needs_Action

`vault.move_to_needs_action()` is called immediately after writing to Inbox.

- Stamps frontmatter: `status: needs_action`, `priority: medium`, `tags: [facebook, social_media]`
- Adds `summary: "Facebook post request: {title}"`
- Moves the file from `Inbox/` to `Needs_Action/`

---

### Step 3 — AI Post Generation + Plan Write

`_generate_post_text(title, tone)` calls `router.route_completion()` → **Groq API** (fast, free tier).

**Post structure enforced by prompt:**
```
**Bold hook question or claim**

Paragraph 1 — topic intro, 2 sentences, specific insight

Paragraph 2 — deeper insight or stat, 2 sentences, 1 emoji mid-sentence

Paragraph 3 — vision/future, 1-2 sentences + 1 emoji
Comment below... [social CTA, never "Click the link"]
#Hashtag1 #Hashtag2 ... (6-8 tags, one line)
```

**Rules baked into the prompt:**
- No "Click the link", "Visit our website" (email-style CTAs banned)
- No corporate filler ("In today's fast-paced world", "game-changing")
- Emojis: 2-3 total, mid/end sentence only, never at line starts
- Length: 100-160 words excluding hashtags

`_write_plan()` writes the post into `Vault/Plans/PLAN_FACEBOOK_POST_{timestamp}.md` with:
- Full YAML frontmatter (type, platform, status, title, tone, generated, approval_needed)
- The generated post text
- A `## Decision` section with **two checkboxes**:
  ```
  - [ ] Approve — publish to Facebook
  - [ ] Pending — move to Pending_Approval for later
  ```

The file **stays in Plans/** — it is NOT auto-moved. You decide what happens next.

---

### Step 4 — Human Decision in Plans/ (HITL Round 1)

Open `Vault/Plans/PLAN_FACEBOOK_POST_*.md` in Obsidian.

Read the draft. Edit the post text if needed. Then tick one checkbox:

| Checkbox | What happens |
|----------|-------------|
| `- [x] Approve` | Watcher moves file to `Vault/Approved/` → publishes to Facebook → `Vault/Done/` |
| `- [x] Pending` | Watcher moves file to `Vault/Pending_Approval/` for later review |

**Requires daemon to be running:**
```bash
python approval_watcher.py --daemon
```

The `PlansHandler` watchdog watches `Vault/Plans/` for `on_modified` events.

---

### Step 4b — Human Decision in Pending_Approval/ (HITL Round 2)

If you chose `Pending` in the previous step, the file lands in `Vault/Pending_Approval/`.

Open it in Obsidian when ready. Tick one checkbox:

| Checkbox | What happens |
|----------|-------------|
| `- [x] Approve` | Watcher moves file to `Vault/Approved/` → publishes to Facebook → `Vault/Done/` |
| `- [x] Reject` | Watcher moves file to `Vault/Done/` (discarded, never published) |

The `PendingApprovalHandler` watchdog handles this folder.

---

### Step 5 — Publish to Facebook

When a file lands in `Vault/Approved/`, the `ApprovedHandler` watchdog fires `process_approved_social_post()`.

For Facebook files (`FACEBOOK_POST_*.md`), it calls `cmd_post()`:

1. Globs all `*FACEBOOK_POST_*.md` from `Vault/Approved/`
2. Extracts post text — reads everything between the second `---` separator and the `## Decision` header (robust, not fragile string matching)
3. Calls `publish_to_page(message)` → HTTP POST to:
   ```
   https://graph.facebook.com/v19.0/{PAGE_ID}/feed
   ```
4. On success: logs action, moves file to `Vault/Done/`, updates Dashboard
5. On failure: logs error, writes `FAILED_facebook_*.md` to `Vault/Needs_Action/`, leaves file in `Approved/` for retry

---

## Environment Variables Required

```env
FACEBOOK_PAGE_ACCESS_TOKEN=your_page_access_token
FACEBOOK_PAGE_ID=your_page_id
```

Set these in `.env` at the project root. Never commit this file.

---

## Key Files

| File | Role |
|------|------|
| `facebook_mcp_server.py` | Main script — pipeline orchestration + Facebook API calls |
| `vault_io.py` | File move/write helpers, frontmatter stamping, dashboard updates |
| `approval_watcher.py` | Daemon — watches Plans/ + Pending_Approval/ (checkboxes) and Approved/ (publish) |
| `router.py` | Routes AI calls to Groq/Claude based on task type |
| `.env` | Facebook credentials (not committed) |

---

## Folder Roles at a Glance

| Folder | Purpose |
|--------|---------|
| `Vault/Inbox/` | Raw request written on command run |
| `Vault/Needs_Action/` | Triage record (pipeline consistency) |
| `Vault/Plans/` | AI draft lives here — your first review point |
| `Vault/Pending_Approval/` | Parked posts — approved later or rejected |
| `Vault/Approved/` | Triggers immediate publish |
| `Vault/Done/` | Archive — published or discarded posts |
