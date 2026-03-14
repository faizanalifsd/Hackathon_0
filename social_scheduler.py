"""
social_scheduler.py – Social Media Post Scheduler (Gold Tier Feature 2)

Generates post drafts for Facebook, Instagram, and LinkedIn on a schedule.
Drafts go to Vault/Pending_Approval/ — human must approve before publishing.

Schedule:
  - Facebook + Instagram: Tuesday & Thursday @ 9:00 AM
  - LinkedIn:             Monday & Wednesday @ 8:00 AM

Usage:
    uv run python social_scheduler.py --facebook   # generate Facebook draft
    uv run python social_scheduler.py --instagram  # generate Instagram draft
    uv run python social_scheduler.py --linkedin   # generate LinkedIn draft
    uv run python social_scheduler.py --all        # generate all three

Windows Task Scheduler runs this with the appropriate flag on each day/time.
After running, check Vault/Pending_Approval/ for draft files.
Move to Vault/Approved/ to publish.
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
LOG_FILE = BASE_DIR / "social_scheduler.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("social-scheduler")


def generate_facebook_draft(topic: str = "") -> str | None:
    """Generate a Facebook post draft and save to Pending_Approval/."""
    try:
        from facebook_mcp_server import generate_facebook_post
        filename = generate_facebook_post(topic)
        if filename:
            log.info("[Facebook] Draft saved: Pending_Approval/%s", filename)
            return filename
        log.warning("[Facebook] No draft generated.")
    except Exception as exc:
        log.error("[Facebook] Draft generation failed: %s", exc)
    return None


def generate_instagram_draft(topic: str = "") -> str | None:
    """Generate an Instagram post draft and save to Pending_Approval/."""
    try:
        from instagram_mcp_server import generate_instagram_post
        filename = generate_instagram_post(topic)
        if filename:
            log.info("[Instagram] Draft saved: Pending_Approval/%s", filename)
            return filename
        log.warning("[Instagram] No draft generated.")
    except Exception as exc:
        log.error("[Instagram] Draft generation failed: %s", exc)
    return None


def generate_linkedin_draft(context: str = "") -> str | None:
    """Generate a LinkedIn post draft and save to Pending_Approval/."""
    try:
        from vault_io import VaultIO
        from linkedin_poster import generate_post_from_vault
        vault = VaultIO()
        filename = generate_post_from_vault(vault)
        if filename:
            log.info("[LinkedIn] Draft saved: Pending_Approval/%s", filename)
            return filename
        log.warning("[LinkedIn] No draft generated.")
    except Exception as exc:
        log.error("[LinkedIn] Draft generation failed: %s", exc)
    return None


def main():
    parser = argparse.ArgumentParser(description="Social Media Post Scheduler")
    parser.add_argument("--facebook",  action="store_true", help="Generate Facebook post draft")
    parser.add_argument("--instagram", action="store_true", help="Generate Instagram post draft")
    parser.add_argument("--linkedin",  action="store_true", help="Generate LinkedIn post draft")
    parser.add_argument("--all",       action="store_true", help="Generate all platform drafts")
    parser.add_argument("--topic",     default="",          help="Optional topic for the post")
    args = parser.parse_args()

    if not any([args.facebook, args.instagram, args.linkedin, args.all]):
        parser.print_help()
        sys.exit(0)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    log.info("Social scheduler run at %s", now)

    results = {}

    if args.all or args.facebook:
        results["facebook"] = generate_facebook_draft(args.topic)

    if args.all or args.instagram:
        results["instagram"] = generate_instagram_draft(args.topic)

    if args.all or args.linkedin:
        results["linkedin"] = generate_linkedin_draft(args.topic)

    ok = sum(1 for v in results.values() if v)
    total = len(results)
    log.info("Done: %d/%d drafts generated. Check Vault/Pending_Approval/ to review.", ok, total)
    print(f"\n{'='*60}")
    print(f"Social Media Drafts Generated: {ok}/{total}")
    print(f"Review in: Vault/Pending_Approval/")
    print(f"To publish: Move approved files to Vault/Approved/")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
