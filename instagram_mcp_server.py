"""
instagram_mcp_server.py – Instagram Business MCP Server for Claude Code.

Posts content to Instagram Business/Creator account via Instagram Graph API.
Requires a Facebook Developer App connected to an Instagram Business account.
All posts go through Vault/Pending_Approval/ before publishing.

Setup:
    1. Go to developers.facebook.com → create/use existing App
    2. Connect your Instagram Business account to the App
    3. Get Instagram Business Account ID (not the same as Facebook Page ID)
    4. Use the same Page Access Token as Facebook (or generate one with instagram_basic,
       instagram_content_publish permissions)
    5. Add to .env:
       FACEBOOK_PAGE_ACCESS_TOKEN=your_token   (same token as Facebook)
       INSTAGRAM_ACCOUNT_ID=your_instagram_business_account_id

Note: Instagram Graph API only supports image/video posts for Business accounts.
      Text-only posts require using the carousel or Reels endpoint.
      For text posts we use the caption field with a placeholder image URL,
      or post as a Story. For simplicity, this implementation posts image+caption.

Tools exposed:
    - instagram_generate_post  → AI-generate caption draft → Pending_Approval/
    - instagram_publish_post   → publish approved post (image + caption)
    - instagram_get_account    → get Instagram account info
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
INSTAGRAM_GRAPH_URL = "https://graph.facebook.com/v19.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_credentials() -> tuple[str, str]:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
    token = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN", "")
    account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")
    if not token or not account_id:
        raise RuntimeError(
            "Missing FACEBOOK_PAGE_ACCESS_TOKEN or INSTAGRAM_ACCOUNT_ID in .env"
        )
    return token, account_id


def get_account_info() -> dict:
    """Get Instagram Business account info."""
    import requests
    token, account_id = _get_credentials()
    r = requests.get(
        f"{INSTAGRAM_GRAPH_URL}/{account_id}",
        params={"fields": "name,username,followers_count,media_count", "access_token": token},
    )
    r.raise_for_status()
    return r.json()


def publish_image_post(image_url: str, caption: str) -> dict:
    """
    Publish an image post to Instagram Business account.
    image_url must be a publicly accessible URL.
    """
    import requests
    token, account_id = _get_credentials()

    # Step 1: Create media container
    r = requests.post(
        f"{INSTAGRAM_GRAPH_URL}/{account_id}/media",
        data={"image_url": image_url, "caption": caption, "access_token": token},
    )
    r.raise_for_status()
    container_id = r.json().get("id")

    # Step 2: Publish the container
    r2 = requests.post(
        f"{INSTAGRAM_GRAPH_URL}/{account_id}/media_publish",
        data={"creation_id": container_id, "access_token": token},
    )
    r2.raise_for_status()
    return {"status": "published", "media_id": r2.json().get("id")}


def generate_instagram_post(topic: str = "") -> str:
    """Use Groq to generate an Instagram caption and save to Pending_Approval/."""
    from router import route_completion
    from vault_io import VaultIO

    vault = VaultIO()
    system = (
        "You are a social media manager for a business. "
        "Write an engaging Instagram caption (50-150 words). "
        "Use relevant hashtags (5-10). Be visual and inspirational. "
        "Output ONLY the caption text with hashtags — no labels or extra commentary."
    )
    user = topic if topic else "Share a business insight or achievement."
    caption = route_completion(system, user, force_model="groq") or ""
    if not caption.strip():
        return ""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"INSTAGRAM_POST_{timestamp}.md"
    content = f"""---
type: instagram_post
platform: instagram
status: pending_approval
generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}
approval_needed: yes
image_url: ""
---

# Instagram Post Draft

Review this caption. Add an `image_url` in the frontmatter above (required for Instagram).
Move to `Vault/Approved/` to publish, or `Vault/Done/` to discard.

---

{caption.strip()}

---

**Platform:** Instagram Business
**Requires:** image_url in frontmatter above (publicly accessible image URL)
**Action:** Add image_url, then move to Approved/
"""
    dest = vault.pending_approval / filename
    dest.write_text(content, encoding="utf-8")
    vault.log_action(
        action_type="instagram_post_drafted",
        actor="instagram_mcp_server",
        target=filename,
        approval_status="pending",
        result="success",
    )
    return filename


def publish_approved_instagram_posts() -> int:
    """Publish all approved INSTAGRAM_POST_*.md files."""
    import re
    from vault_io import VaultIO
    vault = VaultIO()
    approved = list(vault.approved.glob("INSTAGRAM_POST_*.md"))
    count = 0
    for post_file in approved:
        content = post_file.read_text(encoding="utf-8")
        # Extract image_url from frontmatter
        image_url = ""
        for line in content.splitlines():
            if line.startswith("image_url:"):
                image_url = line.split(":", 1)[1].strip().strip('"')
                break
        if not image_url:
            vault.log_action(
                action_type="instagram_post_published",
                actor="instagram_mcp_server",
                target=post_file.name,
                approval_status="approved",
                result="failed",
                details="No image_url in frontmatter",
            )
            continue
        # Extract caption between --- separators
        parts = content.split("---")
        caption = ""
        for i, part in enumerate(parts):
            if i > 2 and part.strip() and "Platform:" not in part and "Requires:" not in part and "Action:" not in part:
                caption = part.strip()
                break
        if not caption:
            continue
        try:
            result = publish_image_post(image_url, caption)
            vault.log_action(
                action_type="instagram_post_published",
                actor="instagram_mcp_server",
                target=post_file.name,
                approval_status="approved",
                result="success",
                details=result.get("media_id", ""),
            )
            vault.move_to_done(f"Approved/{post_file.name}", summary="Instagram post published")
            count += 1
        except Exception as exc:
            vault.log_action(
                action_type="instagram_post_published",
                actor="instagram_mcp_server",
                target=post_file.name,
                approval_status="approved",
                result="failed",
                details=str(exc),
            )
            fail_file = vault.needs_action / f"FAILED_instagram_{post_file.name}"
            fail_file.write_text(
                f"---\ntype: error\nplatform: instagram\n---\n\n"
                f"# Instagram Post Failed\n\n**File:** {post_file.name}\n**Error:** {exc}\n",
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

    mcp = FastMCP("Instagram")

    @mcp.tool()
    def instagram_generate_post(topic: str = "") -> str:
        """
        Generate an Instagram caption draft and save to Vault/Pending_Approval/.
        Nothing is posted without human approval.
        After approving, add an image_url to the frontmatter and move to Approved/.

        Args:
            topic: Optional topic for the post. If empty, uses business context.

        Returns:
            JSON with draft filename saved to Pending_Approval/
        """
        filename = generate_instagram_post(topic)
        if filename:
            return json.dumps({"status": "draft_created", "file": f"Pending_Approval/{filename}"})
        return json.dumps({"status": "error", "reason": "Could not generate caption"})

    @mcp.tool()
    def instagram_publish_approved() -> str:
        """
        Publish all approved Instagram posts from Vault/Approved/.
        Each post file must have image_url set in frontmatter.
        Files must be moved to Approved/ by human first.

        Returns:
            JSON with count of posts published
        """
        count = publish_approved_instagram_posts()
        return json.dumps({"status": "done", "published": count})

    @mcp.tool()
    def instagram_get_account() -> str:
        """
        Get Instagram Business account info (username, followers, media count).

        Returns:
            JSON with account details
        """
        try:
            info = get_account_info()
            return json.dumps({"status": "ok", **info})
        except Exception as exc:
            return json.dumps({"status": "error", "reason": str(exc)})

    mcp.run()


if __name__ == "__main__":
    run_mcp_server()
