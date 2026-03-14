"""
linkedin_mcp_server.py – LinkedIn MCP Server for Claude Code.

Wraps linkedin_poster.py functions as MCP tools.
Requires LinkedIn OAuth2 token (run: uv run python linkedin_poster.py --auth first).

Setup:
    1. Add to .env:
       LINKEDIN_CLIENT_ID=your_id
       LINKEDIN_CLIENT_SECRET=your_secret
    2. Run OAuth: uv run python linkedin_poster.py --auth
    3. Claude Code loads this server via .mcp.json

Tools exposed:
    - linkedin_generate_post  → generate AI post draft → Pending_Approval/
    - linkedin_publish_post   → publish approved post from Approved/
    - linkedin_get_profile    → get authenticated user's LinkedIn profile
"""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

def run_mcp_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print("ERROR: mcp not installed. Run: uv add 'mcp[cli]'", file=sys.stderr)
        sys.exit(1)

    from vault_io import VaultIO

    mcp = FastMCP("LinkedIn")

    @mcp.tool()
    def linkedin_generate_post(context: str = "") -> str:
        """
        Generate a professional LinkedIn post draft from vault context.
        The draft is saved to Vault/Pending_Approval/ for human review.
        Nothing is posted without approval.

        Args:
            context: Optional extra context or topic for the post.
                     If empty, uses recent Needs_Action items from vault.

        Returns:
            JSON with filename of the draft saved to Pending_Approval/
        """
        from linkedin_poster import generate_post_from_vault
        vault = VaultIO()
        filename = generate_post_from_vault(vault)
        if filename:
            return json.dumps({"status": "draft_created", "file": f"Pending_Approval/{filename}"})
        return json.dumps({"status": "no_draft", "reason": "No vault context available"})

    @mcp.tool()
    def linkedin_publish_post(filename: str) -> str:
        """
        Publish an approved LinkedIn post from Vault/Approved/.
        The file must have been moved to Approved/ first (human approval step).

        Args:
            filename: The LINKEDIN_POST_*.md filename in Vault/Approved/

        Returns:
            JSON with publish status
        """
        from linkedin_poster import publish_approved_posts
        vault = VaultIO()
        count = publish_approved_posts(vault)
        return json.dumps({"status": "published", "count": count})

    @mcp.tool()
    def linkedin_get_profile() -> str:
        """
        Get the authenticated LinkedIn user's profile info.

        Returns:
            JSON with LinkedIn member ID and URN
        """
        try:
            import requests
            from linkedin_poster import _get_access_token, _get_person_urn, LINKEDIN_ME_URL
            token = _get_access_token()
            r = requests.get(LINKEDIN_ME_URL, headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            data = r.json()
            return json.dumps({
                "status": "ok",
                "id": data.get("id"),
                "urn": f"urn:li:person:{data.get('id')}",
                "first_name": data.get("localizedFirstName", ""),
                "last_name": data.get("localizedLastName", ""),
            })
        except Exception as exc:
            return json.dumps({"status": "error", "reason": str(exc)})

    mcp.run()


if __name__ == "__main__":
    run_mcp_server()
