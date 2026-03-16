# LinkedIn Posting Guide

## How to Post on LinkedIn (Approved Pipeline)

---

## The Full Flow

```
You run command
      |
      v
uv run python linkedin_post.py
      |  (enter topic + tone in terminal)
      v
Vault/Inbox/linkedin_*.md
      |  (pipeline auto-triages)
      v
Vault/Needs_Action/linkedin_*.md
      |  (Groq drafts full post)
      v
Vault/Pending_Approval/PLAN_linkedin_*.md
      |  (open in Obsidian, review + edit)
      v
Tick [x] Approve and save
      |  (pipeline detects checkbox)
      v
Vault/Approved/PLAN_linkedin_*.md
      |  (auto-posts to LinkedIn)
      v
Posted on LinkedIn
      |
      v
Vault/Done/PLAN_linkedin_*.md
```

---

## Step by Step

**Step 1 — Run the command:**
```bash
uv run python linkedin_post.py
```

**Step 2 — Answer the prompts:**
```
Enter your post topic or idea: AI revolution in 2026
Tone? (professional / casual / inspiring) [professional]: inspiring
```

**Step 3 — Wait ~30 seconds**

The pipeline automatically:
- Triages the file
- Sends topic to Groq
- Drafts a full LinkedIn post
- Saves it to `Vault/Pending_Approval/`

**Step 4 — Open plan in Obsidian**

Find `PLAN_linkedin_*.md` in `Vault/Pending_Approval/`

The plan looks like:
```
## LinkedIn Post

Your AI-drafted post text here...
#hashtag1 #hashtag2

---
## Your Decision

- [ ] Approve — post this to LinkedIn now
- [ ] Pending Approval — hold for later review
```

**Step 5 — Review and edit**

Edit the post text directly in Obsidian if needed.

**Step 6 — Tick the checkbox and save**

Check `[x] Approve` and save the file.

**Step 7 — Done**

Pipeline detects the approval, posts to LinkedIn, moves to `Done/`.

---

## Rules

- Never post without going through Pending_Approval first
- You always review before anything goes public
- Edit the Groq-drafted post freely before approving
- One command = one post request

---

## Requirements

| Item | Where |
|------|-------|
| `LINKEDIN_ACCESS_TOKEN` | `.env` file |
| `LINKEDIN_CLIENT_ID` | `.env` file |
| `LINKEDIN_CLIENT_SECRET` | `.env` file |
| `main.py` running | Terminal |
| `GROQ_API_KEY` | `.env` file |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Plan not appearing in Pending_Approval | Check main.py is running |
| Post not going live after approve | Check LINKEDIN_ACCESS_TOKEN in .env |
| Wrong post text | Edit it in Obsidian before ticking Approve |
| Token expired | Get new token from LinkedIn Developer App |
