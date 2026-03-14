"""
reasoning_loop.py – Claude Reasoning Loop: Needs_Action → Plans → (Auto-execute or Pending_Approval)

For each item in Vault/Needs_Action/ that does not yet have a Plan, this script:
  1. Reads the item content
  2. Invokes the model router to generate a structured PLAN_<name>.md
  3. Writes the plan to Vault/Plans/
  4. If approval_needed: no  → auto-executes the plan immediately (Ralph Wiggum Loop)
  5. If approval_needed: yes → moves plan to Vault/Pending_Approval/ for human review

Ralph Wiggum Loop (autonomous step):
  - Tasks that only need a note filed, calendar entry, or no external action → auto-execute.
  - Stuck task detection: if a task has been re-queued 3+ times without resolution,
    a CEO Briefing note is written to Needs_Action/ for human escalation.

Usage:
    uv run python reasoning_loop.py            # process all unplanned items
    uv run python reasoning_loop.py --daemon   # re-run every 10 minutes

Plan format:
    ---
    task: <original filename>
    approval_needed: yes | no
    priority: high | medium | low
    ---
    # Plan: <task title>
    ## Summary ...
    ## Steps / ## WhatsApp Reply / ## Actions Requiring Approval
"""

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from vault_io import VaultIO

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
LOG_FILE = BASE_DIR / "reasoning_loop.log"
POLL_INTERVAL_SECONDS = 600  # 10 minutes in daemon mode
RETRY_FILE = BASE_DIR / "reasoning_retries.json"
MAX_RETRIES = 3  # escalate to CEO briefing after this many re-queues

import io
_console = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(_console),
    ],
)
log = logging.getLogger("reasoning-loop")

# Actions that always require human approval
APPROVAL_TRIGGERS = [
    "send email", "reply to", "post to", "publish", "payment",
    "transfer", "delete", "remove", "linkedin", "twitter", "instagram",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plan_exists(vault: VaultIO, task_name: str) -> bool:
    """Check whether a PLAN_<task_name>.md already exists in Plans/ or Pending_Approval/."""
    safe = task_name.replace(".md", "")
    plan_path = vault.plans / f"PLAN_{safe}.md"
    pa_path = vault.pending_approval / f"PLAN_{safe}.md"
    approved_path = vault.approved / f"PLAN_{safe}.md"
    return plan_path.exists() or pa_path.exists() or approved_path.exists()


def _needs_approval(plan_content: str) -> bool:
    """Detect if a plan contains actions that require human sign-off."""
    lower = plan_content.lower()
    return any(trigger in lower for trigger in APPROVAL_TRIGGERS)


def _parse_plan_frontmatter_approval(plan_content: str) -> bool:
    """
    Read the approval_needed frontmatter field from a plan.
    Returns True if 'approval_needed: yes'.
    """
    for line in plan_content.splitlines():
        if line.strip().startswith("approval_needed"):
            return "yes" in line.lower()
    # Fall back to keyword detection
    return _needs_approval(plan_content)


def _find_claude_cmd() -> list[str]:
    """Return the correct claude CLI command for the current platform."""
    import shutil
    # Windows: prefer claude.cmd
    if sys.platform == "win32":
        for candidate in ["claude.cmd", "claude"]:
            path = shutil.which(candidate)
            if path:
                return [path]
        # Fallback to known npm path
        npm_claude = Path.home() / "AppData/Roaming/npm/claude.cmd"
        if npm_claude.exists():
            return [str(npm_claude)]
    else:
        path = shutil.which("claude")
        if path:
            return [path]
    return []


def _generate_plan_via_router(task_name: str, task_content: str) -> str | None:
    """
    Generate a plan via the model router:
      - Short emails → Groq (llama-3.3-70b)
      - Long emails  → OpenRouter (gemini-flash)
    Falls back to None so the caller can use _generate_plan_fallback.
    """
    try:
        from router import generate_plan
        result = generate_plan(task_name, task_content)
        return result
    except Exception as exc:
        log.error("Router plan generation failed: %s", exc)
        return None


def _generate_plan_fallback(task_name: str, task_content: str) -> str:
    """Generate a minimal plan when Claude CLI is unavailable."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""---
task: {task_name}
approval_needed: yes
priority: medium
generated: {now}
generator: fallback
---

# Plan: Review {task_name}

## Summary
This task was automatically triaged but requires manual planning.
Claude CLI was unavailable at the time of processing.

## Steps
1. Review the original task file: Needs_Action/{task_name}
2. Determine required actions
3. Execute or delegate as appropriate

## Actions Requiring Approval
- [ ] Manual review required — plan was auto-generated without Claude

## Notes
Re-run reasoning_loop.py when Claude CLI is available for a proper plan.

---
## Your Decision

Review the plan above, make any changes you need, then check **one** box and save the file:

- [ ] ✅ Approve — execute this plan now (Claude will send the reply email)
- [ ] ⏸ Pending Approval — hold for later review
"""


# ---------------------------------------------------------------------------
# Ralph Wiggum Loop — retry tracking + auto-execute
# ---------------------------------------------------------------------------

def _load_retries() -> dict:
    """Load per-task retry counts from disk."""
    if RETRY_FILE.exists():
        try:
            import json
            return json.loads(RETRY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_retries(retries: dict) -> None:
    import json
    RETRY_FILE.write_text(json.dumps(retries, indent=2), encoding="utf-8")


def _increment_retry(task_name: str) -> int:
    """Increment retry count for task_name, save to disk, return new count."""
    retries = _load_retries()
    retries[task_name] = retries.get(task_name, 0) + 1
    _save_retries(retries)
    return retries[task_name]


def _clear_retry(task_name: str) -> None:
    """Reset retry counter after a task is resolved."""
    retries = _load_retries()
    retries.pop(task_name, None)
    _save_retries(retries)


def _escalate_to_ceo(vault: VaultIO, task_name: str, task_content: str, retry_count: int) -> None:
    """Write a CEO Briefing file to Needs_Action/ when a task is stuck."""
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    brief_name = f"CEO_BRIEFING_{ts}_{task_name}"
    brief_path = vault.needs_action / brief_name
    content = f"""---
source: reasoning_loop
received: {datetime.now().strftime("%Y-%m-%d %H:%M")}
status: needs_action
priority: high
tags: [stuck, escalation, ceo_briefing]
summary: "STUCK TASK after {retry_count} retries — manual intervention required"
---

# CEO Briefing: Stuck Task Escalation

**Task:** `{task_name}`
**Retries:** {retry_count} (max: {MAX_RETRIES})
**Escalated at:** {datetime.now().strftime("%Y-%m-%d %H:%M")}

This task has been re-queued {retry_count} times without resolution.
The reasoning loop cannot make progress — human decision required.

## Original Task Content

{task_content}

---

**Action Required:** Review the original task and either:
1. Resolve it manually
2. Delete `Needs_Action/{task_name}` to remove from queue
3. Move to `Done/` if already handled
"""
    brief_path.write_text(content, encoding="utf-8")
    log.warning("[Escalation] Task '%s' stuck after %d retries → CEO Briefing: %s",
                task_name, retry_count, brief_name)
    vault.log_action(
        action_type="ceo_briefing_escalation",
        actor="reasoning_loop",
        target=task_name,
        approval_status="escalated",
        result="escalated",
        details=f"Stuck after {retry_count} retries",
    )


def _auto_execute_plan(vault: VaultIO, task_name: str, plan_name: str, plan_content: str) -> bool:
    """
    Auto-execute a low-risk plan (approval_needed: no).
    Moves the plan to Approved/ then immediately processes it.
    Returns True on success.
    """
    from approval_watcher import process_approved_plan
    import shutil

    plan_src = vault.plans / plan_name
    approved_dir = vault.approved
    approved_dir.mkdir(parents=True, exist_ok=True)
    plan_dest = approved_dir / plan_name

    try:
        shutil.copy2(str(plan_src), str(plan_dest))
        log.info("[AutoExecute] Copied plan to Approved/: %s", plan_name)
        process_approved_plan(vault, plan_dest)
        # Clean up Plans/ copy
        if plan_src.exists():
            plan_src.unlink()
        log.info("[AutoExecute] ✅ Plan executed and moved to Done/: %s", plan_name)
        _clear_retry(task_name)
        return True
    except Exception as exc:
        log.error("[AutoExecute] Failed for %s: %s", plan_name, exc)
        return False


# ---------------------------------------------------------------------------
# Core loop
# ---------------------------------------------------------------------------

def process_needs_action(vault: VaultIO) -> int:
    """Process all unplanned Needs_Action items. Returns number processed."""
    items = vault.list_needs_action()
    if not items:
        log.info("No items in Needs_Action.")
        return 0

    processed = 0
    for rel_path in items:
        task_name = Path(rel_path).name

        if _plan_exists(vault, task_name):
            log.info("Plan already exists for %s — skipping.", task_name)
            continue

        log.info("Generating plan for: %s", task_name)
        try:
            task_content = vault.read_file(rel_path)
        except Exception as exc:
            log.error("Cannot read %s: %s", rel_path, exc)
            continue

        # Stuck task detection
        retry_count = _increment_retry(task_name)
        if retry_count > MAX_RETRIES:
            _escalate_to_ceo(vault, task_name, task_content, retry_count)
            continue

        # Generate plan (Claude → fallback)
        plan_content = _generate_plan_via_router(task_name, task_content)
        if not plan_content:
            log.warning("Using fallback plan for %s", task_name)
            plan_content = _generate_plan_fallback(task_name, task_content)

        # Write plan to Plans/
        try:
            plan_path = vault.write_plan(task_name, plan_content)
            log.info("Plan written -> %s", plan_path.name)
        except Exception as exc:
            log.error("Failed to write plan for %s: %s", task_name, exc)
            continue

        plan_name = plan_path.name
        needs_approval = _parse_plan_frontmatter_approval(plan_content)

        if not needs_approval:
            # Ralph Wiggum Loop: auto-execute low-risk plans
            log.info("[AutoExecute] approval_needed: no — executing plan immediately: %s", plan_name)
            success = _auto_execute_plan(vault, task_name, plan_name, plan_content)
            if success:
                vault.log_action(
                    action_type="plan_auto_executed",
                    actor="reasoning_loop",
                    target=task_name,
                    approval_status="auto",
                    result="success",
                    details=f"Auto-executed {plan_name}",
                )
            else:
                log.warning("[AutoExecute] Failed — plan left in Plans/ for manual review: %s", plan_name)
        else:
            # Move to Pending_Approval for human review
            pa_path = vault.pending_approval / plan_name
            try:
                import shutil
                shutil.move(str(plan_path), str(pa_path))
                log.info("Plan moved -> Pending_Approval/%s", plan_name)
            except Exception as exc:
                log.error("Failed to move plan to Pending_Approval: %s", exc)

            vault.log_action(
                action_type="plan_generated",
                actor="reasoning_loop",
                target=task_name,
                approval_status="pending_user",
                result="success",
                details=f"Plan written to Pending_Approval/{plan_name} — awaiting approval",
            )
            log.info("Plan in Pending_Approval/ — review, then move to Approved/.")

        processed += 1

    # Update dashboard after all processing
    if processed > 0:
        vault.update_dashboard(
            recent_activity=f"- {datetime.now():%Y-%m-%d %H:%M} — Reasoning loop: processed {processed} item(s)"
        )

    return processed


def main():
    parser = argparse.ArgumentParser(description="Claude Reasoning Loop")
    parser.add_argument("--daemon", action="store_true",
                        help=f"Re-run every {POLL_INTERVAL_SECONDS}s")
    args = parser.parse_args()

    vault = VaultIO()
    log.info("Reasoning Loop started.")

    if args.daemon:
        log.info("Daemon mode — running every %ds. Press Ctrl+C to stop.", POLL_INTERVAL_SECONDS)
        try:
            while True:
                n = process_needs_action(vault)
                log.info("Cycle complete. Processed %d item(s).", n)
                time.sleep(POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            log.info("Reasoning Loop stopped.")
    else:
        n = process_needs_action(vault)
        log.info("Done. Processed %d item(s).", n)


if __name__ == "__main__":
    main()
