# Skill: vault-execute

Execute approved plans from Vault/Approved/ and move completed items to Done/.

## Trigger phrases
- "execute approved plans"
- "process Approved folder"
- "run approved tasks"
- "execute [plan name]"

## What this skill does

1. Lists all files in `Vault/Approved/`
2. For each approved plan:
   - Reads the plan content
   - Executes each step that can be done autonomously:
     * File organization (moves, renames)
     * Drafting documents
     * Writing summaries
     * Logging
   - For steps requiring external action (email send, API call):
     * Notes exactly what needs to happen
     * Does NOT execute without explicit confirmation
   - Writes an Execution Report to `Vault/Done/REPORT_PLAN_<task>.md`
   - Moves the plan to `Vault/Done/`
   - Moves the original task file to `Vault/Done/` (if it exists in Needs_Action)
3. Logs every action to `Vault/Logs/YYYY-MM-DD.json`
4. Updates `Vault/Dashboard.md`

## Instructions

When this skill is triggered:

1. Read `Vault/Approved/` — list all .md files
2. If empty: report "No approved items to execute."
3. For each PLAN_*.md in Approved/:
   a. Read the plan
   b. Identify each step type:
      - **Safe (execute now):** file moves, summaries, drafts, logs
      - **Requires tool (note only):** email send → use Email MCP if available
      - **Always human:** payments, account deletions
   c. Execute safe steps using Read/Write/Bash tools
   d. Write execution report:
      ```
      Vault/Done/REPORT_PLAN_<taskname>.md
      ```
   e. Move plan: `mv Vault/Approved/PLAN_x.md Vault/Done/PLAN_x.md`
   f. Find original task in Needs_Action/<taskname>.md and move it to Done/
   g. Append audit log entry

## Execution report format

```markdown
---
type: execution_report
plan: PLAN_task.md
executed_at: YYYY-MM-DD HH:MM
result: COMPLETE | PARTIAL | BLOCKED
---

# Execution Report: PLAN_task.md

## Completed Steps
- [x] Step 1 description
- [x] Step 2 description

## Remaining Human Actions
- [ ] Send email to X (draft saved at Vault/Done/DRAFT_email_x.md)
- [ ] Approve payment of $Y to Z

## Status
PARTIAL — 2 of 4 steps complete. 2 await human action.
```

## Safety rules

- NEVER execute payment steps
- NEVER send emails without Email MCP being configured AND user having approved the specific email content
- NEVER delete files outside the vault
- If a step is ambiguous, classify it as "Requires Human" and document it
