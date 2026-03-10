---
name: vault-summary
description: >
  Update the Obsidian Vault Dashboard.md with current folder counts,
  recent activity, and pending items list.
  Trigger when: after any triage operation, or when user says
  "update dashboard", "refresh dashboard", "show vault status".
---

# Vault Summary Skill

You are responsible for keeping `Vault/Dashboard.md` accurate and up-to-date.

## Your Job

1. **Scan all three folders** to count .md files:
   - `Vault/Inbox/` — items awaiting triage
   - `Vault/Needs_Action/` — items requiring human action
   - `Vault/Done/` — completed items

2. **List Needs_Action items** — read each file's frontmatter `summary` field to build the pending list.

3. **Rewrite Dashboard.md** with the following structure:

```markdown
# Dashboard

> Last updated: YYYY-MM-DD HH:MM

## Status Overview

| Folder | Count |
|--------|-------|
| Inbox | N |
| Needs Action | N |
| Done | N |

## Recent Activity

- YYYY-MM-DD HH:MM — <description of what just happened>

## Pending Items

- [[Needs_Action/filename]] — <summary from frontmatter>

## Quick Links

- [[Company_Handbook]]
- [[Inbox/]]
- [[Needs_Action/]]
- [[Done/]]
```

## Tools to use

- `Glob` — list files in each folder: `Vault/Inbox/*.md`, `Vault/Needs_Action/*.md`, `Vault/Done/*.md`
- `Read` — read frontmatter summaries from Needs_Action files
- `Write` — overwrite `Vault/Dashboard.md` with the updated content

## Notes

- Always include the current timestamp in "Last updated"
- Keep "Recent Activity" to the last 5 entries max
- If a folder is empty, show count 0 and note "_Nothing here._"
