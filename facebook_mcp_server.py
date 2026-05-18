"""
facebook_mcp_server.py – Facebook Page poster for Personal AI Employee.

Full vault pipeline:
    Inbox → Needs_Action → Plans → Pending_Approval → Approved → Done

Usage:
    python facebook_mcp_server.py --request   # ask title+tone → queue post
    python facebook_mcp_server.py --post      # publish all approved posts

Environment variables (.env):
    FACEBOOK_PAGE_ACCESS_TOKEN
    FACEBOOK_PAGE_ID
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
FACEBOOK_GRAPH_URL = "https://graph.facebook.com/v19.0"

load_dotenv(BASE_DIR / ".env")

TONES = [
    "professional",
    "casual",
    "inspirational",
    "funny",
    "educational",
]


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def _get_credentials() -> tuple[str, str]:
    token = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN", "")
    page_id = os.environ.get("FACEBOOK_PAGE_ID", "")
    if not token or not page_id:
        print("ERROR: Missing FACEBOOK_PAGE_ACCESS_TOKEN or FACEBOOK_PAGE_ID in .env")
        sys.exit(1)
    return token, page_id


# ---------------------------------------------------------------------------
# Facebook API
# ---------------------------------------------------------------------------

def get_page_info() -> dict:
    import requests
    token, page_id = _get_credentials()
    r = requests.get(
        f"{FACEBOOK_GRAPH_URL}/{page_id}",
        params={"fields": "name,id", "access_token": token},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def _get_page_token() -> tuple[str, str]:
    """Exchange user token for page token if needed, return (page_token, page_id)."""
    import requests
    token, page_id = _get_credentials()
    r = requests.get(
        f"{FACEBOOK_GRAPH_URL}/me/accounts",
        params={"access_token": token},
        timeout=10,
    )
    r.raise_for_status()
    for page in r.json().get("data", []):
        if page.get("id") == page_id:
            return page["access_token"], page_id
    return token, page_id


def publish_to_page(message: str) -> dict:
    import requests
    page_token, page_id = _get_page_token()
    r = requests.post(
        f"{FACEBOOK_GRAPH_URL}/{page_id}/feed",
        data={"message": message, "access_token": page_token},
        timeout=10,
    )
    r.raise_for_status()
    return {"status": "published", "post_id": r.json().get("id")}


# ---------------------------------------------------------------------------
# AI Generation
# ---------------------------------------------------------------------------

def _generate_post_text(title: str, tone: str) -> str:
    """Call Groq via router to generate post text."""
    from router import route_completion

    system = f"""You are an expert social media strategist writing Facebook posts for a high-growth tech brand.

Tone: {tone}

Follow this exact structure — match this example post closely:

EXAMPLE (openclaw ai topic):
**What if AI could understand human intuition?**
OpenClaw AI is pushing the boundaries of machine learning, enabling computers to learn from human decision-making patterns. This technology has the potential to revolutionize industries such as healthcare and finance.

By analyzing complex data sets and identifying patterns, OpenClaw AI can provide insights that might elude human analysts 📊. This can lead to more accurate predictions and better decision-making.

As OpenClaw AI continues to evolve, we can expect to see significant advancements in fields like natural language processing and computer vision 🤖.
Comment below to share your thoughts on the future of AI and its potential applications.
#OpenClawAI #ArtificialIntelligence #MachineLearning #AIresearch #Innovation #Tech #FutureOfWork #IntelligentSystems

---

STRUCTURE:
1. HOOK — one bold line (**like this**), a punchy question or surprising claim
2. PARAGRAPH 1 — introduce the topic with a specific insight, 2 sentences
3. PARAGRAPH 2 — go deeper, add a stat, nuance, or real-world impact, 2 sentences, 1 emoji mid-sentence
4. PARAGRAPH 3 — vision or future direction, 1-2 sentences + 1 emoji, then immediately the CTA on the next line (no blank line between)
5. HASHTAGS — 6-8 tags all on one line, directly after paragraph 3

STRICT RULES:
- CTA must invite social engagement: "Comment below...", "Tag someone who...", "What do you think?", "Drop your thoughts below" — NEVER "Click the link", "Visit our website", "Send us a message"
- Emojis: 2-3 total, placed naturally mid-sentence or end of sentence, NEVER at line starts
- No corporate filler: no "In today's fast-paced world", "We're excited to announce", "game-changing", "cutting-edge"
- Voice: knowledgeable and human, like a smart colleague sharing an insight — not a press release, not an email newsletter
- Total length: 100-160 words excluding hashtags
- Output ONLY the post text — no labels, no headers, no extra commentary"""

    text = route_completion(system, f"Topic: {title}", force_model="groq") or ""
    return text.strip()


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def _write_plan(vault, title: str, tone: str, post_text: str, timestamp: str) -> str:
    """Step 3 — Write generated post as a Plan."""
    plan_name = f"FACEBOOK_POST_{timestamp}"
    content = (
        f"---\n"
        f"type: facebook_post\n"
        f"platform: facebook\n"
        f"status: plan\n"
        f"title: \"{title}\"\n"
        f"tone: {tone}\n"
        f"generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"approval_needed: yes\n"
        f"---\n\n"
        f"# Facebook Post Plan\n\n"
        f"**Topic:** {title}  \n"
        f"**Tone:** {tone}\n\n"
        f"---\n\n"
        f"{post_text}\n\n"
        f"---\n\n"
        f"**Platform:** Facebook Page\n\n"
        f"## Decision\n\n"
        f"- [ ] Approve — publish to Facebook\n"
        f"- [ ] Pending — move to Pending_Approval for later\n"
    )
    dest = vault.write_plan(plan_name, content)
    return dest.name  # e.g. PLAN_FACEBOOK_POST_20260516_141609.md


def _check_duplicate(title: str) -> str | None:
    """
    Scan Plans/, Pending_Approval/, and Approved/ for a file whose frontmatter
    title matches the requested topic (case-insensitive).
    Returns the relative path of the duplicate if found, else None.
    """
    from vault_io import VaultIO
    vault = VaultIO()
    title_lower = title.strip().lower()
    folders = [
        ("Plans", vault.plans),
        ("Pending_Approval", vault.pending_approval),
        ("Approved", vault.approved),
    ]
    for folder_name, folder_path in folders:
        for f in folder_path.glob("PLAN_FACEBOOK_POST_*.md"):
            try:
                for line in f.read_text(encoding="utf-8").splitlines():
                    if line.strip().lower().startswith("title:"):
                        existing = line.split(":", 1)[1].strip().strip('"').lower()
                        if existing == title_lower:
                            return f"{folder_name}/{f.name}"
            except Exception:
                continue
    return None


# ---------------------------------------------------------------------------
# Main commands
# ---------------------------------------------------------------------------

def cmd_request(title: str = "", tone: str = ""):
    """Interactive (or CLI-arg) path: title + tone → full pipeline."""
    from vault_io import VaultIO
    import sys

    print("\n=== Facebook Post Request ===\n")

    # Accept args passed directly; fall back to interactive only if stdin is a TTY.
    if not title:
        if not sys.stdin.isatty():
            print("ERROR: Title is required. Pass --title \"Your topic\" when running non-interactively.")
            sys.exit(1)
        title = input("Post title / topic: ").strip()
    if not title:
        print("ERROR: Title cannot be empty.")
        sys.exit(1)

    if not tone:
        if sys.stdin.isatty():
            print("\nAvailable tones:")
            for i, t in enumerate(TONES, 1):
                print(f"  {i}. {t}")
            tone_input = input("\nChoose tone (number or name) [default: professional]: ").strip()
            if tone_input.isdigit():
                idx = int(tone_input) - 1
                tone = TONES[idx] if 0 <= idx < len(TONES) else "professional"
            elif tone_input.lower() in TONES:
                tone = tone_input.lower()
            else:
                tone = "professional"
        else:
            tone = "professional"

    # Duplicate check
    duplicate = _check_duplicate(title)
    if duplicate:
        print(f"WARNING: A post with this topic already exists: {duplicate}")
        print("Delete or approve it first before creating a new one.")
        sys.exit(1)

    print(f"\nTone selected: {tone}")
    print("Generating post...\n")

    vault = VaultIO()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Generate + write Plan directly (no Inbox/Needs_Action — avoids reasoning_loop picking it up)
    post_text = _generate_post_text(title, tone)
    if not post_text:
        print("ERROR: Could not generate post text. Check Groq API key.")
        sys.exit(1)
    plan_file = _write_plan(vault, title, tone, post_text, timestamp)
    print(f"[1/1] Plan written to Plans/{plan_file}\n")

    # Log
    vault.log_action(
        action_type="facebook_post_drafted",
        actor="facebook_mcp_server",
        target=plan_file,
        approval_status="awaiting_review",
        result="success",
    )

    # Update dashboard
    vault.update_dashboard(
        recent_activity=f"- Facebook post drafted: **{title}** ({tone}) → Plans/"
    )

    print("=" * 40)
    print("Post draft ready for review.")
    print(f"\nDraft post preview:\n")
    print("-" * 40)
    print(post_text.encode(sys.stdout.encoding, errors="replace").decode(sys.stdout.encoding))
    print("-" * 40)
    print(f"\nFile: Vault/Plans/{plan_file}")
    print("Open in Obsidian: tick  [x] Approve  to publish  |  [x] Pending  to park it.\n")


def cmd_post():
    """Publish all approved FACEBOOK_POST_*.md files."""
    from vault_io import VaultIO

    vault = VaultIO()
    approved = list(vault.approved.glob("*FACEBOOK_POST_*.md"))

    if not approved:
        print("No approved Facebook posts found in Vault/Approved/")
        return

    print(f"Found {len(approved)} approved post(s). Publishing...\n")
    count = 0

    for post_file in approved:
        content = post_file.read_text(encoding="utf-8")

        # Extract post text: everything after the second --- and before ## Decision
        body = content.split("---", 2)[-1]  # strip frontmatter
        decision_split = body.split("## Decision")
        post_text = decision_split[0].strip()
        # Also strip the topic/tone header lines at the top of the body
        lines = post_text.splitlines()
        post_text = "\n".join(
            l for l in lines
            if not l.startswith("# Facebook Post Plan")
            and not l.startswith("**Topic:**")
            and not l.startswith("**Tone:**")
            and not l.startswith("**Platform:**")
            and l.strip() != "---"
        ).strip()

        if not post_text:
            print(f"  SKIP {post_file.name} — could not extract post text.")
            continue

        try:
            result = publish_to_page(post_text)
            post_id = result.get("post_id", "")
            print(f"  PUBLISHED {post_file.name}")
            print(f"  Post ID: {post_id}\n")

            vault.log_action(
                action_type="facebook_post_published",
                actor="facebook_mcp_server",
                target=post_file.name,
                approval_status="approved",
                result="success",
                details=post_id,
            )
            vault.move_to_done(
                f"Approved/{post_file.name}",
                summary="Facebook post published",
            )
            count += 1

        except Exception as exc:
            print(f"  FAILED {post_file.name}: {exc}")
            vault.log_action(
                action_type="facebook_post_published",
                actor="facebook_mcp_server",
                target=post_file.name,
                approval_status="approved",
                result="failed",
                details=str(exc),
            )
            fail_file = vault.needs_action / f"FAILED_facebook_{post_file.name}"
            fail_file.write_text(
                f"---\ntype: error\nplatform: facebook\n---\n\n"
                f"# Facebook Post Failed\n\n**File:** {post_file.name}\n**Error:** {exc}\n",
                encoding="utf-8",
            )

    vault.update_dashboard(
        recent_activity=f"- Facebook: {count} post(s) published"
    )
    print(f"Done. Published {count}/{len(approved)} post(s).")


# ---------------------------------------------------------------------------
# MCP Server (for Claude Code integration)
# ---------------------------------------------------------------------------

def run_mcp_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print("ERROR: mcp not installed. Run: uv add 'mcp[cli]'", file=sys.stderr)
        sys.exit(1)

    mcp = FastMCP("Facebook")

    @mcp.tool()
    def facebook_get_page_info() -> str:
        """Get Facebook Page name and ID."""
        try:
            return json.dumps({"status": "ok", **get_page_info()})
        except Exception as exc:
            return json.dumps({"status": "error", "reason": str(exc)})

    @mcp.tool()
    def facebook_publish_approved() -> str:
        """Publish all approved Facebook posts from Vault/Approved/."""
        cmd_post()
        return json.dumps({"status": "done"})

    mcp.run()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Facebook Page Poster — Personal AI Employee")
    parser.add_argument("--request", action="store_true", help="Request a new post")
    parser.add_argument("--title", default="", help="Post title/topic (non-interactive)")
    parser.add_argument("--tone", default="", help=f"Tone: {', '.join(TONES)} (default: professional)")
    parser.add_argument("--post", action="store_true", help="Publish all approved posts from Vault/Approved/")
    parser.add_argument("--mcp", action="store_true", help="Run as MCP server (for Claude Code)")
    args = parser.parse_args()

    if args.request or args.title:
        cmd_request(title=args.title, tone=args.tone)
    elif args.post:
        cmd_post()
    elif args.mcp:
        run_mcp_server()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
