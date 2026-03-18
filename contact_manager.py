"""
contact_manager.py – Contact Memory System (Platinum Tier Feature 4)

Maintains Vault/Contacts/ with one .md file per person.
Each contact stores name, email, WhatsApp chat name, interaction history, and notes.

When reasoning_loop.py generates a plan, it injects the sender's contact context
into the LLM prompt, enabling personalized replies ("Hi John, great talking again").

Usage:
    from contact_manager import get_contact_context, record_interaction
    context = get_contact_context(task_content)
    record_interaction("john@example.com", "email_sent", "Replied re: invoice")
"""

import json
import re
import logging
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
VAULT_ROOT = BASE_DIR / "Vault"
CONTACTS_DIR = VAULT_ROOT / "Contacts"
LOG = logging.getLogger("contact-manager")

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_contacts_dir():
    CONTACTS_DIR.mkdir(parents=True, exist_ok=True)


def _safe_filename(identifier: str) -> str:
    """Convert 'John Smith' or 'john@x.com' to 'john_smith.md'."""
    # Remove domain part from emails for filename
    base = identifier.split("@")[0] if "@" in identifier else identifier
    safe = re.sub(r"[^\w\s-]", "", base).strip().replace(" ", "_").lower()
    return f"{safe[:60]}.md"


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_block = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    fm: dict = {}
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


def _new_contact_content(name: str, email: str, chat_name: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d")
    display = name or email or chat_name
    return f"""---
source: contact_manager
name: {name}
email: {email}
whatsapp_chat: {chat_name}
first_seen: {now}
last_interaction: {now}
---

# {display}

## Profile
- **Email:** {email or "_unknown_"}
- **WhatsApp:** {chat_name or "_unknown_"}

## Interaction History

| Date | Type | Summary |
|------|------|---------|

## Notes

"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_or_create_contact(
    email: str = "",
    name: str = "",
    chat_name: str = "",
) -> Path:
    """
    Find existing contact by email or chat_name, or create a new one.
    Returns Path to the contact .md file.
    """
    _ensure_contacts_dir()

    # Search for existing contact
    for cf in CONTACTS_DIR.glob("*.md"):
        try:
            fm, _ = _parse_frontmatter(cf.read_text(encoding="utf-8"))
        except Exception:
            continue
        if email and fm.get("email", "").lower() == email.lower():
            return cf
        if chat_name and fm.get("whatsapp_chat", "").lower() == chat_name.lower():
            return cf

    # Create new contact
    identifier = email or chat_name or name or "unknown"
    fname = _safe_filename(identifier)
    # Handle duplicate filenames
    dest = CONTACTS_DIR / fname
    if dest.exists():
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        dest = CONTACTS_DIR / f"{fname[:-3]}_{ts}.md"

    content = _new_contact_content(name, email, chat_name)
    dest.write_text(content, encoding="utf-8")
    LOG.info("[Contacts] Created new contact: %s", dest.name)
    return dest


def get_contact_context(task_content: str) -> str:
    """
    Extract sender identity from task_content frontmatter (from:, chat: fields).
    Look up or create the contact.
    Returns a compact context string to inject into LLM prompts, or "" if no info.
    """
    _ensure_contacts_dir()

    email = ""
    chat_name = ""
    sender_name = ""

    for line in task_content.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("from:"):
            raw = stripped.split(":", 1)[1].strip()
            m = re.search(r"<([^>]+@[^>]+)>", raw)
            if m:
                email = m.group(1).strip()
                sender_name = raw.split("<")[0].strip().strip('"')
            else:
                m2 = EMAIL_RE.search(raw)
                if m2:
                    email = m2.group(0)
                else:
                    sender_name = raw
        elif stripped.lower().startswith("chat:"):
            chat_name = stripped.split(":", 1)[1].strip()
        elif not sender_name and stripped.lower().startswith("from_name:"):
            sender_name = stripped.split(":", 1)[1].strip()

    if not email and not chat_name:
        return ""

    try:
        contact_path = get_or_create_contact(
            email=email, name=sender_name, chat_name=chat_name
        )
        fm, body = _parse_frontmatter(
            contact_path.read_text(encoding="utf-8")
        )

        name_display = fm.get("name") or sender_name or email or chat_name
        last = fm.get("last_interaction", "unknown")

        # Extract last 2 interaction rows from history table
        history_lines = []
        in_table = False
        row_count = 0
        for line in body.splitlines():
            if "## Interaction History" in line:
                in_table = True
                continue
            if in_table and line.startswith("##"):
                break
            if in_table and line.startswith("|") and "---" not in line and "Date" not in line:
                history_lines.append(line.strip())
                row_count += 1
                if row_count >= 2:
                    break

        history_str = ""
        if history_lines:
            history_str = f" Past interactions: {'; '.join(history_lines[:2])}."

        ctx_parts = [f"Contact: {name_display}"]
        if email:
            ctx_parts.append(f"email: {email}")
        if chat_name:
            ctx_parts.append(f"WhatsApp: {chat_name}")
        ctx_parts.append(f"last interaction: {last}")
        context = ", ".join(ctx_parts) + "." + history_str

        LOG.info("[Contacts] Context for '%s': %s", name_display, context[:100])
        return context

    except Exception as exc:
        LOG.warning("[Contacts] Context lookup failed: %s", exc)
        return ""


def record_interaction(
    identifier: str,
    action_type: str,
    summary: str,
) -> None:
    """
    Append a row to the '## Interaction History' table in the contact file.
    identifier: email address or WhatsApp chat name.
    """
    _ensure_contacts_dir()

    # Find contact file
    contact_path: Path | None = None
    for cf in CONTACTS_DIR.glob("*.md"):
        try:
            fm, _ = _parse_frontmatter(cf.read_text(encoding="utf-8"))
        except Exception:
            continue
        if (
            fm.get("email", "").lower() == identifier.lower()
            or fm.get("whatsapp_chat", "").lower() == identifier.lower()
        ):
            contact_path = cf
            break

    if not contact_path:
        # Auto-create minimal contact
        if "@" in identifier:
            contact_path = get_or_create_contact(email=identifier)
        else:
            contact_path = get_or_create_contact(chat_name=identifier)

    try:
        text = contact_path.read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(text)

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        row = f"| {now} | {action_type} | {summary[:80]} |"

        # Insert row after the table header
        lines = body.splitlines()
        new_lines = []
        inserted = False
        for line in lines:
            new_lines.append(line)
            if not inserted and "| Date |" in line:
                # Skip separator row, then insert after it
                continue
            if not inserted and "|------|" in line:
                new_lines.append(row)
                inserted = True

        if not inserted:
            new_lines.append(row)

        fm["last_interaction"] = now.split()[0]
        new_content = _render_frontmatter(fm) + "\n" + "\n".join(new_lines)
        contact_path.write_text(new_content, encoding="utf-8")
        LOG.info("[Contacts] Recorded '%s' for %s", action_type, identifier)

    except Exception as exc:
        LOG.error("[Contacts] record_interaction failed: %s", exc)


def list_contacts() -> list[dict]:
    """Return list of {name, email, chat_name, last_interaction} for all contacts."""
    _ensure_contacts_dir()
    result = []
    for cf in sorted(CONTACTS_DIR.glob("*.md")):
        try:
            fm, _ = _parse_frontmatter(cf.read_text(encoding="utf-8"))
            result.append({
                "name": fm.get("name", ""),
                "email": fm.get("email", ""),
                "chat_name": fm.get("whatsapp_chat", ""),
                "last_interaction": fm.get("last_interaction", ""),
                "file": cf.name,
            })
        except Exception:
            pass
    return result


def search_contacts(query: str) -> list[Path]:
    """Full-text search across all contact .md files."""
    _ensure_contacts_dir()
    ql = query.lower()
    return [
        cf for cf in CONTACTS_DIR.glob("*.md")
        if ql in cf.read_text(encoding="utf-8", errors="replace").lower()
    ]


if __name__ == "__main__":
    import json as _json
    contacts = list_contacts()
    print(f"Contacts ({len(contacts)}):")
    print(_json.dumps(contacts, indent=2))
