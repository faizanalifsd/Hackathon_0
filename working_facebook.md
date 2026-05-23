# Facebook Page Posting — How It Works

## Overview

The Facebook posting system is a 4-stage vault pipeline with human approval built in.
No post ever goes live without you checking a checkbox in Obsidian.

---

## Full Pipeline

```
User runs command  (duplicate check runs here — blocks if same title already queued)
      ↓
[1] Vault/Inbox/          ← fb_request_{timestamp}.md written here
      ↓  (3 second pause — visible in Obsidian)
[2] Vault/Needs_Action/   ← file moved, frontmatter stamped
      ↓  (Groq generates post text while file sits here)
[3] Vault/Plans/          ← PLAN_FACEBOOK_POST_{timestamp}.md written once generation is done
      ↓
[HUMAN opens Plans/ in Obsidian — read the draft, edit if needed, tick one box]

   - [x] Approve  ────────────────────────────────────────────────────→ Vault/Approved/
   - [x] Pending  → Vault/Pending_Approval/                                    ↓
                          ↓                                           python --post
                  [HUMAN opens Pending_Approval/]                    (or --post flag)
                  - [x] Approve  ──────────────────────────────────→ Vault/Approved/
                  - [x] Reject   → Vault/Done/  (discarded)                    ↓
                                                                      Facebook Graph API
                                                                               ↓
                                                                      Vault/Done/ (archived)
```

---

## Step-by-Step Breakdown

### Step 1 — Duplicate Check + User Triggers the Request

```bash
# Interactive (prompts for title + tone)
python facebook_mcp_server.py --request

# Non-interactive (pass args directly)
python facebook_mcp_server.py --title "your topic" --tone professional
```

Available tones: `professional`, `casual`, `inspirational`, `funny`, `educational`

**Before writing anything**, the script scans these folders for a file whose frontmatter
`title:` matches the requested topic (case-insensitive):
- `Vault/Plans/`
- `Vault/Pending_Approval/`
- `Vault/Approved/`

If a match is found, the command exits with a warning instead of creating a duplicate.

---

### Step 2 — Inbox (3-second pause)

`fb_request_{timestamp}.md` is written to `Vault/Inbox/` with full frontmatter
(`source`, `received`, `status: inbox`, `priority`, `tags`, `summary`).

The script prints `[1/3] Request written → Vault/Inbox/...` and waits **3 seconds**
so you can see the file appear in Obsidian before it moves.

---

### Step 3 — Needs_Action (while AI generates)

`vault.move_to_needs_action()` moves the file to `Vault/Needs_Action/` and stamps
additional frontmatter (`status: needs_action`, `moved` timestamp).

The file **sits here while Groq generates the post text** — you can watch it in Obsidian.
Generation typically takes 2-5 seconds.

---

### Step 4 — AI Post Generation + Plan Write

`_generate_post_text(title, tone)` calls `router.route_completion()` → **Groq API** (fast, free tier,
forced via `force_model="groq"`).

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

Once generation is done, `_write_plan()` writes `Vault/Plans/PLAN_FACEBOOK_POST_{timestamp}.md` with:
- Full YAML frontmatter (`type`, `platform`, `status`, `title`, `tone`, `generated`, `approval_needed`)
- The generated post text
- A `## Decision` section with **two checkboxes**:
  ```
  - [ ] Approve — publish to Facebook
  - [ ] Pending — move to Pending_Approval for later
  ```

The `fb_request_*.md` remains in `Needs_Action/` as a log record.
The plan file stays in `Plans/` — it is NOT auto-moved. You decide what happens next.

---

### Step 5 — Human Decision in Plans/ (HITL Round 1)

Open `Vault/Plans/PLAN_FACEBOOK_POST_*.md` in Obsidian.

Read the draft. Edit the post text if needed. Then tick one checkbox:

| Checkbox | What happens |
|----------|-------------|
| `- [x] Approve` | Watcher moves file to `Vault/Approved/` |
| `- [x] Pending` | Watcher moves file to `Vault/Pending_Approval/` for later review |

**Requires daemon to be running:**
```bash
python approval_watcher.py --daemon
```

The `PlansHandler` watchdog watches `Vault/Plans/` for `on_modified` events.

---

### Step 5b — Human Decision in Pending_Approval/ (HITL Round 2)

If you chose `Pending` in the previous step, the file lands in `Vault/Pending_Approval/`.

Open it in Obsidian when ready. Tick one checkbox:

| Checkbox | What happens |
|----------|-------------|
| `- [x] Approve` | Watcher moves file to `Vault/Approved/` |
| `- [x] Reject` | Watcher moves file to `Vault/Done/` (discarded, never published) |

The `PendingApprovalHandler` watchdog handles this folder.

---

### Step 6 — Publish to Facebook

Once a file is in `Vault/Approved/`, publish with:

```bash
python facebook_mcp_server.py --post
```

`cmd_post()`:
1. Globs all `*FACEBOOK_POST_*.md` from `Vault/Approved/`
2. Extracts post text — reads everything between the second `---` separator and the `## Decision`
   header (filters out header lines like `# Facebook Post Plan`, `**Topic:**`, `**Tone:**`, `**Platform:**`)
3. Calls `publish_to_page(message)`:
   - First calls `/me/accounts` to exchange the user token for a page-scoped token
   - Then HTTP POST to `https://graph.facebook.com/v19.0/{PAGE_ID}/feed`
4. On success: logs action, moves file to `Vault/Done/`, updates Dashboard
5. On failure: logs error, writes `FAILED_facebook_*.md` to `Vault/Needs_Action/`, leaves file in `Approved/` for retry

> **Note on the daemon path:** `ApprovedHandler` in `approval_watcher.py` routes files starting
> with `PLAN_` to the generic plan executor (email/WhatsApp), not the Facebook publisher.
> Because `PLAN_FACEBOOK_POST_*.md` starts with `PLAN_`, the daemon alone will not publish it.
> **Always run `--post` manually** (or via Task Scheduler) after approving a Facebook post.

---

## CLI Reference

| Command | What it does |
|---------|-------------|
| `python facebook_mcp_server.py --request` | Interactive: prompts for title + tone, drafts post |
| `python facebook_mcp_server.py --title "topic" --tone casual` | Non-interactive draft creation |
| `python facebook_mcp_server.py --post` | Publish all approved posts from `Vault/Approved/` |
| `python facebook_mcp_server.py --mcp` | Run as MCP server (for Claude Code integration) |

---

## Environment Variables Required

```env
FACEBOOK_PAGE_ACCESS_TOKEN=your_page_access_token
FACEBOOK_PAGE_ID=your_page_id
```

Set these in `.env` at the project root. Never commit this file.

The token may be a user token — `_get_page_token()` automatically exchanges it for the
correct page-scoped token by calling `/me/accounts` before every post.

---

## Key Files

| File | Role |
|------|------|
| `facebook_mcp_server.py` | Main script — duplicate check, Groq generation, plan write, Facebook API |
| `vault_io.py` | File move/write helpers, frontmatter stamping, dashboard updates |
| `approval_watcher.py` | Daemon — watches Plans/ + Pending_Approval/ (checkboxes) |
| `router.py` | Routes AI calls; Facebook generation is forced to Groq |
| `.env` | Facebook credentials (not committed) |

---

## Folder Roles at a Glance

| Folder | Purpose |
|--------|---------|
| `Vault/Inbox/` | Raw request written on command run (visible for 3 seconds) |
| `Vault/Needs_Action/` | Request record lives here while Groq generates; failed publish reports also land here |
| `Vault/Plans/` | AI draft — your first review point |
| `Vault/Pending_Approval/` | Parked posts — approved later or rejected |
| `Vault/Approved/` | Ready to publish — run `--post` to send |
| `Vault/Done/` | Archive — published or discarded posts |
