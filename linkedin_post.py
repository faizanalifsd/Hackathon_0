"""
linkedin_post.py — Start a LinkedIn post via the approval pipeline.

Usage:
    uv run python linkedin_post.py

What it does:
    1. Asks you for a post topic/title in the terminal
    2. Creates a linkedin_*.md file in Vault/Inbox/
    3. Pipeline picks it up:
         Inbox → Needs_Action → Groq drafts post → Pending_Approval/
    4. Open the plan in Obsidian, review/edit, tick [x] Approve, save
    5. Auto-posts to LinkedIn → moves to Done/
"""

import sys
import io
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

BASE_DIR = Path(__file__).parent
VAULT_ROOT = BASE_DIR / "Vault"
INBOX_DIR = VAULT_ROOT / "Inbox"

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def main():
    print("=" * 50)
    print("  LinkedIn Post Creator")
    print("=" * 50)
    print()

    topic = input("Enter your post topic or idea: ").strip()
    if not topic:
        print("No topic entered. Exiting.")
        return

    tone = input("Tone? (professional / casual / inspiring) [professional]: ").strip()
    if not tone:
        tone = "professional"

    # Create Inbox file
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_topic = topic[:40].replace(" ", "_").replace("/", "-")
    filename = f"linkedin_{ts}_{safe_topic}.md"
    filepath = INBOX_DIR / filename

    INBOX_DIR.mkdir(parents=True, exist_ok=True)

    content = f"""---
source: linkedin
received: {datetime.now().strftime("%Y-%m-%d %H:%M")}
status: inbox
priority: medium
tags: [linkedin, post]
summary: "LinkedIn post request: {topic}"
topic: {topic}
tone: {tone}
---

# LinkedIn Post Request

**Topic:** {topic}
**Tone:** {tone}
**Requested at:** {datetime.now().strftime("%Y-%m-%d %H:%M")}

---

Please draft a LinkedIn post about the topic above.
Keep it engaging, {tone}, and suitable for a professional audience.
"""

    filepath.write_text(content, encoding="utf-8")

    print()
    print(f"Created: Vault/Inbox/{filename}")
    print()
    print("Pipeline will now:")
    print("  1. Triage -> Needs_Action/")
    print("  2. Groq drafts your LinkedIn post -> Pending_Approval/")
    print("  3. Open the plan in Obsidian, review/edit")
    print("  4. Tick [x] Approve and save")
    print("  5. Auto-posts to LinkedIn -> Done/")
    print()
    print("Check Vault/Pending_Approval/ in Obsidian in ~30 seconds.")


if __name__ == "__main__":
    main()
