# Bronze Tier — Testing Guide

## Prerequisites
- Terminal open at `E:/Hackathon_0/`
- Obsidian open with the `Vault/` folder

---

## Test 1 — Verify Folder Structure

Open Obsidian and confirm these folders exist inside `Vault/`:

```
Vault/
├── Inbox/
├── Needs_Action/       ← sample_email.md should be here
├── Plans/              ← PLAN_sample_email.md should be here
├── Pending_Approval/
├── Approved/
├── Logs/               ← 2026-03-04.json should be here
├── Done/
├── Dashboard.md
└── Company_Handbook.md
```

**Pass:** All folders and files are present.

---

## Test 2 — Verify UV Python Project

Run in terminal:

```bash
cd E:/Hackathon_0
uv run python --version
```

**Pass:** Prints `Python 3.x.x` without errors.

---

## Test 3 — Verify Watcher Script Starts

Run in terminal:

```bash
cd E:/Hackathon_0
uv run python watcher.py
```

**Pass:** You see output like:
```
2026-03-04 ... [INFO] Vault Watcher started.
2026-03-04 ... [INFO] Monitoring: E:\Hackathon_0\Vault\Inbox
2026-03-04 ... [INFO] Press Ctrl+C to stop.
```

Keep this terminal open for Test 4.

---

## Test 4 — End-to-End: Drop File → Watcher Detects

With the watcher running (Test 3), open a **second terminal** and run:

```bash
cp E:/Hackathon_0/Vault/Needs_Action/sample_email.md E:/Hackathon_0/Vault/Inbox/test_drop.md
```

**Pass:** The first terminal (watcher) prints:
```
[INFO] New inbox item detected: test_drop.md
[INFO] Triggering triage for: Inbox/test_drop.md
```

Press `Ctrl+C` to stop the watcher after the test.

---

## Test 5 — Verify Agent Skills Exist

Run in terminal:

```bash
ls E:/Hackathon_0/.claude/skills/vault-triage/
ls E:/Hackathon_0/.claude/skills/vault-summary/
```

**Pass:** Both print `SKILL.md`.

---

## Test 6 — Verify Dashboard.md is Up-to-Date

Open `Vault/Dashboard.md` in Obsidian and confirm:

- `Inbox` count = 0
- `Needs Action` count = 1
- `Pending Items` lists `sample_email.md`

---

## Test 7 — Verify Audit Log

Open `Vault/Logs/2026-03-04.json` and confirm it contains a JSON entry with:
- `action_type: "file_triage"`
- `actor: "claude_code"`
- `result: "success"`

---

## Summary Checklist

- [ ] Test 1 — Folder structure correct
- [ ] Test 2 — UV Python project works
- [ ] Test 3 — Watcher starts without errors
- [ ] Test 4 — Watcher detects dropped file
- [ ] Test 5 — Agent Skills present
- [ ] Test 6 — Dashboard.md is accurate
- [ ] Test 7 — Audit log exists and is valid

**All 7 pass → Bronze Tier confirmed. Tell Claude to proceed to Silver.**

---

---

## How to Move Items from Needs_Action → Done

You currently have 5 items in `Vault/Needs_Action/`:
- `sample_email.md`
- `test.md`
- `test_drop.md`
- `test2.md`
- `zee.md`

The constitution pipeline is:
```
Needs_Action → Plans → Pending_Approval → Approved → Done
```

Follow these steps for **each item**:

---

### Step 1 — Review the item
Open the file in Obsidian. Read it and decide:
- Is it a real task that needs action? → follow Step 2
- Is it a test/dummy file? → skip to Step 5 (move directly to Done)

---

### Step 2 — Check if a Plan exists
Look in `Vault/Plans/` for a matching `PLAN_<filename>.md`.
- If it exists → review the plan steps
- If it does not exist → ask Claude: `"Write a plan for Needs_Action/<filename>.md"`

---

### Step 3 — Does it need approval?
Check the plan. If any step involves:
- Sending an email
- Any payment
- Posting on social media

→ Move the plan file to `Vault/Pending_Approval/`
→ Review it yourself, then move it to `Vault/Approved/`

If no approval is needed → go straight to Step 4.

---

### Step 4 — Mark as complete
Once the task is done (or reviewed and no action needed), move **both** files:

```bash
# Move the task file
mv "E:/Hackathon_0/Vault/Needs_Action/<filename>.md" "E:/Hackathon_0/Vault/Done/<filename>.md"

# Move the plan file (if one exists)
mv "E:/Hackathon_0/Vault/Plans/PLAN_<filename>.md" "E:/Hackathon_0/Vault/Done/PLAN_<filename>.md"
```

---

### Step 5 — For test/dummy files (quick cleanup)

These files were created during testing and can go straight to Done:

```bash
mv "E:/Hackathon_0/Vault/Needs_Action/test.md"      "E:/Hackathon_0/Vault/Done/test.md"
mv "E:/Hackathon_0/Vault/Needs_Action/test_drop.md" "E:/Hackathon_0/Vault/Done/test_drop.md"
mv "E:/Hackathon_0/Vault/Needs_Action/test2.md"     "E:/Hackathon_0/Vault/Done/test2.md"
mv "E:/Hackathon_0/Vault/Needs_Action/zee.md"       "E:/Hackathon_0/Vault/Done/zee.md"
```

For `sample_email.md` (the real test item) — it already has a plan at `Plans/PLAN_sample_email.md`.
Since it is a test item (no real email to send), move it to Done as well:

```bash
mv "E:/Hackathon_0/Vault/Needs_Action/sample_email.md" "E:/Hackathon_0/Vault/Done/sample_email.md"
mv "E:/Hackathon_0/Vault/Plans/PLAN_sample_email.md"   "E:/Hackathon_0/Vault/Done/PLAN_sample_email.md"
```

---

### Step 6 — Update the Dashboard

After moving all items, tell Claude:
> "update dashboard"

Or run the vault-summary skill so `Dashboard.md` reflects the new counts.

---

### Quick Reference: Pipeline Rules (from constitution)

| Stage | Who moves it | Condition |
|-------|-------------|-----------|
| Inbox → Needs_Action | Claude (auto triage) | Always |
| Needs_Action → Plans | Claude (writes plan) | Always |
| Plans → Pending_Approval | Claude | If approval needed |
| Pending_Approval → Approved | **You** | After your review |
| Approved → Done | Claude | After action executed |
| Needs_Action → Done | **You** | If test/dummy item |
