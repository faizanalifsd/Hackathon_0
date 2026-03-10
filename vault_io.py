"""
vault_io.py – Claude Code read/write helper for the Obsidian vault.

Usage:
    from vault_io import VaultIO
    v = VaultIO()
    items = v.list_inbox()
    v.move_to_needs_action("Inbox/my_note.md", summary="Needs reply")
    v.write_plan("my_note", content="# Plan\\n...")
    v.log_action("file_triage", "claude_code", "my_note.md", "auto", "success")
    v.update_dashboard()
"""

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

VAULT_ROOT = Path(__file__).parent / "Vault"

INBOX = VAULT_ROOT / "Inbox"
NEEDS_ACTION = VAULT_ROOT / "Needs_Action"
PLANS = VAULT_ROOT / "Plans"
PENDING_APPROVAL = VAULT_ROOT / "Pending_Approval"
APPROVED = VAULT_ROOT / "Approved"
DONE = VAULT_ROOT / "Done"
LOGS = VAULT_ROOT / "Logs"
DASHBOARD = VAULT_ROOT / "Dashboard.md"
HANDBOOK = VAULT_ROOT / "Company_Handbook.md"


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body) from a markdown string."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_block = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    fm = {}
    for line in fm_block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"')
    return fm, body


def _render_frontmatter(fm: dict) -> str:
    lines = ["---"]
    for k, v in fm.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _inject_frontmatter(text: str, updates: dict) -> str:
    fm, body = _parse_frontmatter(text)
    fm.update(updates)
    return _render_frontmatter(fm) + "\n" + body


# ---------------------------------------------------------------------------
# VaultIO class
# ---------------------------------------------------------------------------

class VaultIO:
    """Read and write files inside the Obsidian vault."""

    def __init__(self, vault_root: str | None = None):
        self.root = Path(vault_root) if vault_root else VAULT_ROOT
        self.inbox = self.root / "Inbox"
        self.needs_action = self.root / "Needs_Action"
        self.plans = self.root / "Plans"
        self.pending_approval = self.root / "Pending_Approval"
        self.approved = self.root / "Approved"
        self.done = self.root / "Done"
        self.logs = self.root / "Logs"
        self.dashboard = self.root / "Dashboard.md"

        # Ensure all Silver Tier folders exist
        for folder in [
            self.inbox, self.needs_action, self.plans,
            self.pending_approval, self.approved, self.done, self.logs,
        ]:
            folder.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def read_file(self, rel_path: str) -> str:
        """Read any vault file by relative path (e.g. 'Inbox/foo.md')."""
        return (self.root / rel_path).read_text(encoding="utf-8")

    def list_inbox(self) -> list[str]:
        return [f"Inbox/{p.name}" for p in self.inbox.glob("*.md")]

    def list_needs_action(self) -> list[str]:
        return [f"Needs_Action/{p.name}" for p in self.needs_action.glob("*.md")]

    def list_plans(self) -> list[str]:
        return [f"Plans/{p.name}" for p in self.plans.glob("*.md")]

    def list_pending_approval(self) -> list[str]:
        return [f"Pending_Approval/{p.name}" for p in self.pending_approval.glob("*.md")]

    def list_approved(self) -> list[str]:
        return [f"Approved/{p.name}" for p in self.approved.glob("*.md")]

    def list_done(self) -> list[str]:
        return [f"Done/{p.name}" for p in self.done.glob("*.md")]

    def list_all(self) -> dict[str, list[str]]:
        return {
            "inbox": self.list_inbox(),
            "needs_action": self.list_needs_action(),
            "plans": self.list_plans(),
            "pending_approval": self.list_pending_approval(),
            "approved": self.list_approved(),
            "done": self.list_done(),
        }

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def write_inbox(self, filename: str, content: str) -> Path:
        """Write a new note into Inbox."""
        dest = self.inbox / filename
        dest.write_text(content, encoding="utf-8")
        return dest

    def write_plan(self, task_name: str, content: str) -> Path:
        """Write a Plan file to Plans/PLAN_<task_name>.md."""
        safe_name = task_name.replace(".md", "").replace("/", "_").replace("\\", "_")
        dest = self.plans / f"PLAN_{safe_name}.md"
        dest.write_text(content, encoding="utf-8")
        return dest

    def move_to_needs_action(
        self,
        rel_path: str,
        summary: str = "",
        priority: str = "medium",
        tags: list[str] | None = None,
    ) -> Path:
        """Move a file from Inbox → Needs_Action and stamp frontmatter."""
        src = self.root / rel_path
        dest = self.needs_action / src.name
        text = src.read_text(encoding="utf-8")
        text = _inject_frontmatter(text, {
            "status": "needs_action",
            "priority": priority,
            "summary": f'"{summary}"',
            "tags": str(tags or []),
            "moved": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        dest.write_text(text, encoding="utf-8")
        src.unlink()
        return dest

    def move_to_pending_approval(self, rel_path: str) -> Path:
        """Move a plan file from Plans/ → Pending_Approval/."""
        src = self.root / rel_path
        dest = self.pending_approval / src.name
        text = src.read_text(encoding="utf-8")
        text = _inject_frontmatter(text, {
            "approval_status": "pending",
            "submitted": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        dest.write_text(text, encoding="utf-8")
        src.unlink()
        return dest

    def move_to_approved(self, rel_path: str) -> Path:
        """Move a plan file from Pending_Approval/ → Approved/."""
        src = self.root / rel_path
        dest = self.approved / src.name
        text = src.read_text(encoding="utf-8")
        text = _inject_frontmatter(text, {
            "approval_status": "approved",
            "approved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        dest.write_text(text, encoding="utf-8")
        src.unlink()
        return dest

    def move_to_done(self, rel_path: str, summary: str = "") -> Path:
        """Move a file from any active folder → Done."""
        src = self.root / rel_path
        dest = self.done / src.name
        text = src.read_text(encoding="utf-8")
        text = _inject_frontmatter(text, {
            "status": "done",
            "summary": f'"{summary}"',
            "completed": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        dest.write_text(text, encoding="utf-8")
        src.unlink()
        return dest

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    def log_action(
        self,
        action_type: str,
        actor: str,
        target: str,
        approval_status: str = "auto",
        result: str = "success",
        details: str = "",
    ) -> None:
        """Append a structured JSON log entry to Vault/Logs/YYYY-MM-DD.json."""
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = self.logs / f"{today}.json"

        entry = {
            "timestamp": datetime.now().isoformat(),
            "action_type": action_type,
            "actor": actor,
            "target": target,
            "approval_status": approval_status,
            "result": result,
            "details": details,
        }

        entries = []
        if log_file.exists():
            try:
                entries = json.loads(log_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                entries = []

        entries.append(entry)
        log_file.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Dashboard update
    # ------------------------------------------------------------------

    def update_dashboard(self, recent_activity: str = "") -> None:
        """Rewrite Dashboard.md with current folder counts."""
        inbox_count = len(self.list_inbox())
        na_count = len(self.list_needs_action())
        plans_count = len(self.list_plans())
        pending_count = len(self.list_pending_approval())
        approved_count = len(self.list_approved())
        done_count = len(self.list_done())
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        activity_block = recent_activity if recent_activity else "_No recent activity._"

        content = f"""# Dashboard

> Last updated: {now}

## Status Overview

| Folder | Count |
|--------|-------|
| Inbox | {inbox_count} |
| Needs Action | {na_count} |
| Plans | {plans_count} |
| Pending Approval | {pending_count} |
| Approved (awaiting execution) | {approved_count} |
| Done | {done_count} |

## Recent Activity

{activity_block}

## Pending Items

"""
        if na_count == 0:
            content += "_Nothing pending._\n"
        else:
            for f in self.list_needs_action():
                content += f"- [[{f}]]\n"

        if pending_count > 0:
            content += "\n## Awaiting Your Approval\n\n"
            for f in self.list_pending_approval():
                content += f"- [[{f}]]\n"

        content += """
## Quick Links

- [[Company_Handbook]]
- [[Inbox/]]
- [[Needs_Action/]]
- [[Plans/]]
- [[Pending_Approval/]]
- [[Approved/]]
- [[Done/]]
"""
        self.dashboard.write_text(content, encoding="utf-8")
        print(
            f"[vault_io] Dashboard updated — "
            f"inbox:{inbox_count} needs_action:{na_count} "
            f"plans:{plans_count} pending:{pending_count} done:{done_count}"
        )


# ---------------------------------------------------------------------------
# CLI convenience
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    v = VaultIO()
    print(json.dumps(v.list_all(), indent=2))
    v.update_dashboard()
    print("Dashboard updated.")
