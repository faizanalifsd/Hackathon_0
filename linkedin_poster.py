"""
linkedin_poster.py – LinkedIn Auto-Poster for Business Leads.

Generates and queues LinkedIn posts from business lead summaries.
Posts are written to Vault/Pending_Approval/ for human review before
anything is published.

Actual publishing uses the LinkedIn API (requires a Developer App):
    https://www.linkedin.com/developers/apps

Setup:
    1. Create a LinkedIn Developer App → get Client ID + Secret
    2. Request r_liteprofile + w_member_social permissions
    3. Complete OAuth2 flow (run: uv run python linkedin_poster.py --auth)
    4. Token saved to linkedin_token.json

Usage:
    uv run python linkedin_poster.py --generate  # generate a post from vault leads
    uv run python linkedin_poster.py --post       # publish all approved posts
    uv run python linkedin_poster.py --auth       # run OAuth flow

Environment variables (or .env file):
    LINKEDIN_CLIENT_ID
    LINKEDIN_CLIENT_SECRET

Requirements:
    uv add requests python-dotenv
"""

import argparse
import json
import logging
import os
from dotenv import load_dotenv
load_dotenv()
import re
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler

from vault_io import VaultIO

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
TOKEN_FILE = BASE_DIR / "linkedin_token.json"
LOG_FILE = BASE_DIR / "linkedin_poster.log"

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_UGC_URL = "https://api.linkedin.com/v2/ugcPosts"
LINKEDIN_ME_URL = "https://api.linkedin.com/v2/userinfo"
REDIRECT_URI = "http://localhost:8765/callback"
SCOPES = "r_liteprofile w_member_social"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("linkedin-poster")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _load_env():
    """Load .env if present."""
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _get_credentials() -> tuple[str, str]:
    _load_env()
    client_id = os.environ.get("LINKEDIN_CLIENT_ID", "")
    client_secret = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        log.error(
            "Missing LINKEDIN_CLIENT_ID or LINKEDIN_CLIENT_SECRET.\n"
            "Add them to E:/Hackathon_0/.env"
        )
        sys.exit(1)
    return client_id, client_secret


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Minimal HTTP server to capture OAuth callback."""
    auth_code = None

    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            _OAuthCallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h1>Authorization complete. You can close this tab.</h1>")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"<h1>Authorization failed.</h1>")

    def log_message(self, *args):
        pass  # Suppress HTTP server logs


def run_oauth_flow():
    """Run LinkedIn OAuth2 flow and save token to linkedin_token.json."""
    try:
        import requests
    except ImportError:
        log.error("Run: uv add requests")
        sys.exit(1)

    client_id, client_secret = _get_credentials()

    auth_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
    }
    auth_url = f"{LINKEDIN_AUTH_URL}?{urlencode(auth_params)}"
    log.info("Opening LinkedIn authorization page...")
    webbrowser.open(auth_url)

    server = HTTPServer(("localhost", 8765), _OAuthCallbackHandler)
    log.info("Waiting for OAuth callback on http://localhost:8765 ...")
    server.handle_request()

    code = _OAuthCallbackHandler.auth_code
    if not code:
        log.error("Did not receive authorization code.")
        sys.exit(1)

    resp = requests.post(LINKEDIN_TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "client_secret": client_secret,
    })
    resp.raise_for_status()
    token_data = resp.json()
    TOKEN_FILE.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
    log.info("Token saved to %s", TOKEN_FILE)


def _get_access_token() -> str:
    # 1. Try linkedin_token.json first
    if TOKEN_FILE.exists():
        data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        return data["access_token"]
    # 2. Fallback: LINKEDIN_ACCESS_TOKEN in .env
    token = os.getenv("LINKEDIN_ACCESS_TOKEN")
    if token:
        log.info("Using LINKEDIN_ACCESS_TOKEN from .env")
        return token
    log.error("No token found. Set LINKEDIN_ACCESS_TOKEN in .env or run: uv run python linkedin_poster.py --auth")
    sys.exit(1)


def _get_person_urn(token: str) -> str:
    """Get LinkedIn member URN for authenticated user."""
    try:
        import requests
    except ImportError:
        log.error("Run: uv add requests")
        sys.exit(1)
    r = requests.get(LINKEDIN_ME_URL, headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    data = r.json()
    # /v2/userinfo returns "sub", older /v2/me returns "id"
    member_id = data.get("sub") or data.get("id")
    return f"urn:li:person:{member_id}"


# ---------------------------------------------------------------------------
# Post generation
# ---------------------------------------------------------------------------

def generate_post_from_vault(vault: VaultIO) -> str | None:
    """
    Read recent Needs_Action items and generate a LinkedIn post draft.
    Writes draft to Vault/Pending_Approval/ for review.
    Returns the filename of the draft, or None.
    """
    import subprocess
    items = vault.list_needs_action()
    if not items:
        log.info("No Needs_Action items to generate a post from.")
        return None

    # Use the first item for context
    context = ""
    for rel in items[:3]:
        try:
            context += f"\n\n--- {rel} ---\n{vault.read_file(rel)[:500]}"
        except Exception:
            pass

    prompt = f"""You are a LinkedIn content strategist for a business professional.
Based on the following work/task context from their vault, generate a professional
LinkedIn post (150-300 words) that:
- Shares a business insight or lesson learned
- Is engaging and authentic
- Does NOT reveal private client details
- Ends with a question to drive engagement

CONTEXT:
{context}

Output ONLY the post text, ready to copy-paste. No preamble.
"""
    try:
        import shutil
        claude_cmd = shutil.which("claude") or shutil.which("claude.cmd") or \
            str(Path.home() / "AppData/Roaming/npm/claude.cmd")
        result = subprocess.run(
            [claude_cmd, "--print", prompt],
            capture_output=True, text=True, timeout=60, cwd=str(BASE_DIR)
        )
        if result.returncode != 0 or not result.stdout.strip():
            log.warning("Claude could not generate post: %s", result.stderr)
            return None
        post_text = result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.error("Post generation failed: %s", exc)
        return None

    # Write draft to Pending_Approval
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"LINKEDIN_POST_{timestamp}.md"
    content = f"""---
type: linkedin_post
status: pending_approval
generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}
approval_needed: yes
---

# LinkedIn Post Draft

Review this post, then move this file to Vault/Approved/ to publish it.

---

{post_text}

---

**To publish:** Move this file to `Vault/Approved/`
**To discard:** Move this file to `Vault/Done/`
"""
    dest = vault.pending_approval / filename
    dest.write_text(content, encoding="utf-8")
    log.info("LinkedIn post draft -> Pending_Approval/%s", filename)

    vault.log_action(
        action_type="linkedin_post_drafted",
        actor="linkedin_poster",
        target=filename,
        approval_status="pending",
        result="success",
    )
    return filename


# ---------------------------------------------------------------------------
# Post publishing
# ---------------------------------------------------------------------------

def publish_approved_posts(vault: VaultIO) -> int:
    """Publish all approved LinkedIn post files. Returns count published."""
    try:
        import requests
    except ImportError:
        log.error("Run: uv add requests")
        return 0

    approved = [
        p for p in vault.approved.glob("LINKEDIN_POST_*.md")
    ]
    if not approved:
        log.info("No approved LinkedIn posts to publish.")
        return 0

    token = _get_access_token()
    person_urn = _get_person_urn(token)
    count = 0

    for post_file in approved:
        content = post_file.read_text(encoding="utf-8")
        # Extract post text between the --- separators
        parts = content.split("---")
        post_text = ""
        for i, part in enumerate(parts):
            if "# LinkedIn Post Draft" in part and i + 1 < len(parts):
                # Text is between the first and second --- after the heading
                candidate = parts[i + 1].strip()
                if candidate and "To publish" not in candidate:
                    post_text = candidate
                    break
            elif i > 2 and part.strip() and "To publish" not in part:
                post_text = part.strip()
                break

        if not post_text:
            log.warning("Could not extract post text from %s", post_file.name)
            continue

        payload = {
            "author": person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": post_text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }

        try:
            r = requests.post(
                LINKEDIN_UGC_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "X-Restli-Protocol-Version": "2.0.0",
                },
            )
            r.raise_for_status()
            log.info("Published LinkedIn post: %s", post_file.name)

            vault.log_action(
                action_type="linkedin_post_published",
                actor="linkedin_poster",
                target=post_file.name,
                approval_status="approved",
                result="success",
            )

            # Move to Done
            rel = f"Approved/{post_file.name}"
            vault.move_to_done(rel, summary="LinkedIn post published")
            count += 1

        except Exception as exc:
            log.error("Failed to publish %s: %s", post_file.name, exc)
            vault.log_action(
                action_type="linkedin_post_published",
                actor="linkedin_poster",
                target=post_file.name,
                approval_status="approved",
                result="failed",
                details=str(exc),
            )

    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LinkedIn Auto-Poster")
    parser.add_argument("--auth", action="store_true", help="Run OAuth2 authorization flow")
    parser.add_argument("--generate", action="store_true", help="Generate a post draft from vault leads")
    parser.add_argument("--post", action="store_true", help="Publish all approved posts")
    args = parser.parse_args()

    if args.auth:
        run_oauth_flow()
        return

    vault = VaultIO()

    if args.generate:
        fname = generate_post_from_vault(vault)
        if fname:
            print(f"\nDraft saved → Vault/Pending_Approval/{fname}")
            print("Review it in Obsidian, then move to Vault/Approved/ to publish.")
        return

    if args.post:
        n = publish_approved_posts(vault)
        print(f"Published {n} post(s).")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
