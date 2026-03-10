# Skill: hitl-approve

Human-in-the-Loop approval workflow — review pending plans and approve or reject them.

## Trigger phrases
- "show pending approvals"
- "review pending"
- "what needs my approval"
- "approve [task]"
- "reject [task]"

## What this skill does

1. Lists all files in `Vault/Pending_Approval/`
2. For each pending item, presents a formatted summary to the human
3. Based on human response:
   - **Approve:** moves file to `Vault/Approved/` (triggers vault-execute)
   - **Reject:** moves file to `Vault/Done/` with a "rejected" status stamp
   - **Edit:** saves an amended version to `Vault/Pending_Approval/` for re-review

## Instructions

When this skill is triggered:

1. Read `Vault/Pending_Approval/` — list all .md files
2. If empty: report "Nothing awaiting your approval."
3. For each pending file, present:
   ```
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   📋 PENDING: PLAN_task.md
   Priority: medium
   Actions requiring approval:
     - [ ] Send email to client@example.com
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ```
4. Ask: "Approve (A), Reject (R), Edit (E), Skip (S)?"
5. Act on response:
   - A → `mv Vault/Pending_Approval/PLAN_x.md Vault/Approved/PLAN_x.md`
   - R → stamp rejected frontmatter → `mv ... Vault/Done/PLAN_x.md`
   - E → show plan content, accept edits, write back
   - S → skip this item, move to next

## Approval log entry

After each decision, append to `Vault/Logs/YYYY-MM-DD.json`:

```json
{
  "timestamp": "...",
  "action_type": "plan_approved" | "plan_rejected",
  "actor": "human",
  "target": "PLAN_task.md",
  "approval_status": "approved" | "rejected",
  "result": "success"
}
```

## Safety notes

- Items in `Vault/Approved/` are picked up automatically by `approval_watcher.py`
- You can manually move files in Obsidian instead of using this skill
- Rejected plans are archived in Done/ — nothing is deleted
