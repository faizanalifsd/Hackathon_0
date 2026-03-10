---
name: vault-triage
description: >
  Triage a new item in the Obsidian Vault Inbox.
  Reads the file, classifies it (needs_action / done / urgent),
  stamps frontmatter, moves it to the correct folder, then
  updates Dashboard.md.
  Trigger when: a new .md file appears in Vault/Inbox/, or the user
  says "triage inbox", "process inbox", or "check inbox".
---

# Vault Triage Skill

You are an AI assistant responsible for triaging items in the Obsidian knowledge vault.

## Your Job

When invoked with a file path (e.g. `Inbox/foo.md`):

1. **Read** the file using the Read tool.
2. **Read** `Vault/Company_Handbook.md` to understand triage rules.
3. **Classify** the item:
   - `needs_action` — requires a human response, decision, or follow-up
   - `done` — purely informational, no action needed
   - `urgent` — deadline within 24 hours (also set priority: high)
4. **Stamp frontmatter** by prepending a YAML block:
   ```yaml
   ---
   source: inbox
   received: <current datetime YYYY-MM-DD HH:MM>
   status: <needs_action|done>
   priority: <high|medium|low>
   tags: [<relevant tags>]
   summary: "<one sentence summary>"
   ---
   ```
5. **Move** the file:
   - `needs_action` → `Vault/Needs_Action/<filename>`
   - `done` → `Vault/Done/<filename>`
   - Delete the original from Inbox after writing the destination.
6. **Call vault-summary skill** (or run the summary step inline) to update Dashboard.md.

## Rules (from Company Handbook)

- Urgent = deadline < 24h → `/Needs_Action` + tag `#urgent` + priority: high
- Action Required = needs reply/decision → `/Needs_Action`
- FYI / Informational → `/Done` directly

## Tools to use

- `Read` — read vault files
- `Edit` / `Write` — write frontmatter-stamped file to destination
- `Bash` — delete source file: `rm "Vault/Inbox/<filename>"`
- After moving: run the vault-summary skill to refresh Dashboard.md

## Example

User: "Triage Inbox/meeting_invite.md"

Steps:
1. Read `Vault/Inbox/meeting_invite.md`
2. Read `Vault/Company_Handbook.md`
3. Determine: meeting invite requiring RSVP → needs_action, priority medium
4. Write stamped version to `Vault/Needs_Action/meeting_invite.md`
5. Delete `Vault/Inbox/meeting_invite.md`
6. Update Dashboard.md
