"""
facebook_mcp_server.py – Facebook Page MCP Server for Claude Code.

Posts content to a Facebook Page via Graph API.
All posts go through Vault/Pending_Approval/ before publishing.

Setup:
    1. Go to developers.facebook.com → create an App
    2. Add Facebook Login + Pages API permissions
    3. Generate a Page Access Token (long-lived, 60 days)
    4. Add to .env:
       FACEBOOK_PAGE_ACCESS_TOKEN=your_token
       FACEBOOK_PAGE_ID=your_page_id

Tools exposed:
    - facebook_generate_post  → AI-generate post draft → Pending_Approval/
    - facebook_publish_post   → publish approved post to Facebook Page
    - facebook_get_page_info  → get Page name, fans, and status
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
FACEBOOK_GRAPH_URL = "https://graph.facebook.com/v19.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_credentials() -> tuple[str, str]:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
    token = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN", "")
    page_id = os.environ.get("FACEBOOK_PAGE_ID", "")
    if not token or not page_id:
        raise RuntimeError(
            "Missing FACEBOOK_PAGE_ACCESS_TOKEN or FACEBOOK_PAGE_ID in .env"
        )
    return token, page_id


def get_page_info() -> dict:
    """Get Facebook Page name, fan count, and category."""
    import requests
    token, page_id = _get_credentials()
    r = requests.get(
        f"{FACEBOOK_GRAPH_URL}/{page_id}",
        params={"fields": "name,fan_count,category", "access_token": token},
    )
    r.raise_for_status()
    return r.json()


def publish_to_page(message: str) -> dict:
    """Publish a text post to the Facebook Page."""
    import requests
    token, page_id = _get_credentials()
    r = requests.post(
        f"{FACEBOOK_GRAPH_URL}/{page_id}/feed",
        data={"message": message, "access_token": token},
    )
    r.raise_for_status()
    return {"status": "published", "post_id": r.json().get("id")}


def generate_facebook_post(topic: str = "") -> str:
    """Use Groq to generate a Facebook post and save to Pending_Approval/."""
    from router import route_completion
    from vault_io import VaultIO

    vault = VaultIO()
    system = (
        "You are a social media manager for a business. "
        "Write a short, engaging Facebook post (80-150 words). "
        "Be conversational, use emojis sparingly, end with a call to action. "
        "Output ONLY the post text — no labels or extra commentary."
    )
    user = topic if topic else "Share a business tip or insight relevant to our work this week."
    post_text = route_completion(system, user, force_model="groq") or ""
    if not post_text.strip():
        return ""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"FACEBOOK_POST_{timestamp}.md"
    content = f"""---
type: facebook_post
platform: facebook
status: pending_approval
generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}
approval_needed: yes
---

# Facebook Post Draft

Review this post. Move to `Vault/Approved/` to publish, or `Vault/Done/` to discard.

---

{post_text.strip()}

---

**Platform:** Facebook Page
**Action:** Move to Approved/ to publish
"""
    dest = vault.pending_approval / filename
    dest.write_text(content, encoding="utf-8")
    vault.log_action(
        action_type="facebook_post_drafted",
        actor="facebook_mcp_server",
        target=filename,
        approval_status="pending",
        result="success",
    )
    return filename


def publish_approved_facebook_posts() -> int:
    """Publish all approved FACEBOOK_POST_*.md files."""
    from vault_io import VaultIO
    vault = VaultIO()
    approved = list(vault.approved.glob("FACEBOOK_POST_*.md"))
    count = 0
    for post_file in approved:
        content = post_file.read_text(encoding="utf-8")
        # Extract text between --- separators after frontmatter
        parts = content.split("---")
        post_text = ""
        for i, part in enumerate(parts):
            if i > 2 and part.strip() and "Platform:" not in part and "Action:" not in part:
                post_text = part.strip()
                break
        if not post_text:
            continue
        try:
            result = publish_to_page(post_text)
            vault.log_action(
                action_type="facebook_post_published",
                actor="facebook_mcp_server",
                target=post_file.name,
                approval_status="approved",
                result="success",
                details=result.get("post_id", ""),
            )
            vault.move_to_done(f"Approved/{post_file.name}", summary="Facebook post published")
            count += 1
        except Exception as exc:
            vault.log_action(
                action_type="facebook_post_published",
                actor="facebook_mcp_server",
                target=post_file.name,
                approval_status="approved",
                result="failed",
                details=str(exc),
            )
            # Write failure note to Needs_Action
            fail_file = vault.needs_action / f"FAILED_facebook_{post_file.name}"
            fail_file.write_text(
                f"---\ntype: error\nplatform: facebook\n---\n\n"
                f"# Facebook Post Failed\n\n**File:** {post_file.name}\n**Error:** {exc}\n",
                encoding="utf-8",
            )
    return count


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

def run_mcp_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print("ERROR: mcp not installed. Run: uv add 'mcp[cli]'", file=sys.stderr)
        sys.exit(1)

    mcp = FastMCP("Facebook")

    @mcp.tool()
    def facebook_generate_post(topic: str = "") -> str:
        """
        Generate a Facebook Page post draft using AI and save to Pending_Approval/.
        Nothing is posted without human approval.

        Args:
            topic: Optional topic or context for the post. If empty, uses business context.

        Returns:
            JSON with draft filename saved to Pending_Approval/
        """
        filename = generate_facebook_post(topic)
        if filename:
            return json.dumps({"status": "draft_created", "file": f"Pending_Approval/{filename}"})
        return json.dumps({"status": "error", "reason": "Could not generate post"})

    @mcp.tool()
    def facebook_publish_approved() -> str:
        """
        Publish all approved Facebook posts from Vault/Approved/.
        Files must be moved to Approved/ by human first.

        Returns:
            JSON with count of posts published
        """
        count = publish_approved_facebook_posts()
        return json.dumps({"status": "done", "published": count})

    @mcp.tool()
    def facebook_get_page_info() -> str:
        """
        Get Facebook Page information (name, fans, category).

        Returns:
            JSON with page details
        """
        try:
            info = get_page_info()
            return json.dumps({"status": "ok", **info})
        except Exception as exc:
            return json.dumps({"status": "error", "reason": str(exc)})

    mcp.run()


if __name__ == "__main__":
    run_mcp_server()
