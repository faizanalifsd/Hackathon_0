# Company Handbook

## Overview

This handbook defines standard operating procedures for the AI-assisted knowledge vault system.

## Folder Structure

| Folder | Purpose |
|--------|---------|
| `/Inbox` | New incoming items (emails, documents, notes) awaiting triage |
| `/Needs_Action` | Items triaged and requiring a human decision or follow-up |
| `/Done` | Completed or archived items |

## Triage Rules

1. **Urgent** – Items with deadlines within 24 hours → `/Needs_Action` with tag `#urgent`
2. **Action Required** – Items needing a response or decision → `/Needs_Action`
3. **FYI / Informational** – No action needed → `/Done` directly
4. **Spam / Irrelevant** – Delete or archive

## Note Format

Every processed note should include a frontmatter block:

```yaml
---
source: email | file | manual
received: YYYY-MM-DD HH:MM
status: inbox | needs_action | done
priority: high | medium | low
tags: []
summary: ""
---
```

## Agent Skill Responsibilities

| Skill | Trigger | Output |
|-------|---------|--------|
| `vault-triage` | New file in `/Inbox` | Move to correct folder, add frontmatter |
| `vault-summary` | After triage | Update `Dashboard.md` counts and activity |
| `vault-reasoning` | Item in `/Needs_Action` | Generate action plan, write to `/Plans` |
| `vault-execute` | Plan in `/Approved` | Execute approved plan, move to `/Done` |
| `hitl-approve` | Item in `/Pending_Approval` | Review and approve or reject plan |
