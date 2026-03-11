"""
reasoning_loop.py – Claude Reasoning Loop: Needs_Action → Plans → Pending_Approval

For each item in Vault/Needs_Action/ that does not yet have a Plan, this script:
  1. Reads the item content
  2. Invokes Claude (via CLI) to generate a structured PLAN_<name>.md
  3. Writes the plan to Vault/Plans/
  4. If the plan requires human approval, moves it to Vault/Pending_Approval/

The loop then writes a briefing log entry and updates the Dashboard.

Usage:
    uv run python reasoning_loop.py            # process all unplanned items
    uv run python reasoning_loop.py --daemon   # re-run every 10 minutes

Plan format written by Claude:
    ---
    task: <original filename>
    approval_needed: yes | no
    priority: high | medium | low
    ---
    # Plan: <task title>
    ## Summary
    ...
    ## Steps
    1. ...
    ## Actions Requiring Approval
    - [ ] Send email to ...
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

        # Log the planning action
        vault.log_action(
            action_type="plan_generated",
            actor="reasoning_loop",
            target=task_name,
            approval_status="pending_user",
            result="success",
            details=f"Plan written to {plan_path.name} — awaiting user decision",
        )

        log.info("Plan sitting in Plans/ — open it in Obsidian, tick a checkbox, and save.")
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
