# Skill: vault-reasoning

Generate structured Plan.md files from items in Vault/Needs_Action/.

## Trigger phrases
- "generate plan for [task]"
- "plan [filename]"
- "reason about Needs_Action"
- "process unplanned items"
- "create plans"

## What this skill does

1. Lists all items in `Vault/Needs_Action/`
2. For each item that does NOT already have a plan in `Vault/Plans/` or `Vault/Pending_Approval/`:
   - Reads the item content
   - Generates a structured PLAN_<task>.md
   - Writes it to `Vault/Plans/`
   - If the plan contains external actions (email, payment, social post), moves it to `Vault/Pending_Approval/`
3. Updates `Vault/Dashboard.md`
4. Writes an audit entry to `Vault/Logs/YYYY-MM-DD.json`

## Plan format

```markdown
---
task: <original filename>
approval_needed: yes | no
priority: high | medium | low
generated: YYYY-MM-DD HH:MM
---

# Plan: <short title>

## Summary
<2-3 sentences describing what needs to be done>

## Steps
1. <first step>
2. <second step>
...

## Actions Requiring Approval
- [ ] <any step involving: email send, social post, payment, external API call>

## Notes
<warnings, context, dependencies>
```

## Approval rules

Set `approval_needed: yes` if ANY step involves:
- Sending or replying to emails
- Posting on LinkedIn, Twitter/X, Instagram, Facebook
- Any payment or financial transaction
- Deleting files or records
- Any call to an external service or API

Set `approval_needed: no` for:
- Internal file organization
- Drafting documents (without sending)
- Analysis and summarization only

## Instructions

When this skill is triggered:

1. Use the Read tool to list files in `Vault/Needs_Action/`
2. Use the Read tool to list files in `Vault/Plans/` and `Vault/Pending_Approval/`
3. For each unplanned item:
   a. Read the item content
   b. Generate the plan following the format above
   c. Write to `Vault/Plans/PLAN_<taskname>.md` using the Write tool
   d. If `approval_needed: yes`, move the plan to `Vault/Pending_Approval/` using Bash: `mv "Vault/Plans/PLAN_x.md" "Vault/Pending_Approval/PLAN_x.md"`
   e. Log the action to `Vault/Logs/YYYY-MM-DD.json`
4. Update `Vault/Dashboard.md` using the vault-summary skill or by calling `uv run python vault_io.py`

## Example log entry

```json
{
  "timestamp": "2026-03-06T14:30:00",
  "action_type": "plan_generated",
  "actor": "claude_code",
  "target": "sample_email.md",
  "approval_status": "pending",
  "result": "success",
  "details": "Plan written to PLAN_sample_email.md, moved to Pending_Approval"
}
```
