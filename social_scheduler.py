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
import json
import logging
import sys
from datetime import datetime, timedelta
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


def generate_weekly_social_report() -> str:
    """
    Scan Vault/Done/ and Vault/Logs/ for the past 7 days of social media activity.
    Write a report to Vault/Reports/Social_Media_Weekly_YYYY-MM-DD.md.
    Returns the report file path.
    """
    from vault_io import VaultIO
    from router import route_completion

    vault = VaultIO()
    cutoff = datetime.now() - timedelta(days=7)
    week_end = datetime.now().strftime("%Y-%m-%d")

    # Count published posts per platform from Done/
    platform_counts: dict[str, int] = {"linkedin": 0, "facebook": 0, "instagram": 0}
    for f in vault.done.glob("*.md"):
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime < cutoff:
            continue
        name_lower = f.name.lower()
        for platform in platform_counts:
            if name_lower.startswith(platform) or f"_{platform}_" in name_lower:
                platform_counts[platform] += 1

    # Read log entries for social actions
    social_log_lines: list[str] = []
    for log_file in vault.logs.glob("????-??-??.json"):
        try:
            file_date = datetime.strptime(log_file.stem, "%Y-%m-%d")
        except ValueError:
            continue
        if file_date < cutoff:
            continue
        try:
            entries = json.loads(log_file.read_text(encoding="utf-8"))
            for entry in entries:
                target = entry.get("target", "").lower()
                action = entry.get("action_type", "").lower()
                if any(p in target or p in action for p in ("linkedin", "facebook", "instagram", "post")):
                    social_log_lines.append(
                        f"- {entry.get('timestamp', '')[:16]} | {entry.get('action_type')} | "
                        f"{entry.get('target')} | {entry.get('result')}"
                    )
        except Exception:
            pass

    log_summary = "\n".join(social_log_lines[-30:]) if social_log_lines else "_No social media log entries this week._"

    # AI-generated summary
    system = (
        "You are a social media analyst writing a weekly performance summary for a business owner. "
        "Be concise and professional. Use bullet points. Max 200 words."
    )
    user = f"""Weekly Social Media Activity ({(datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')} to {week_end}):

Posts published:
- LinkedIn: {platform_counts['linkedin']}
- Facebook: {platform_counts['facebook']}
- Instagram: {platform_counts['instagram']}

Activity log:
{log_summary}

Write a weekly social media performance summary including: total posts, platform breakdown, observations, and 1-2 recommendations for next week."""

    ai_summary = route_completion(system, user) or "_AI summary unavailable — check LLM API keys._"

    report_content = f"""---
type: social_media_report
week_ending: {week_end}
generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}
---

# Social Media Weekly Report — {week_end}

## Posts Published This Week

| Platform | Posts |
|----------|-------|
| LinkedIn | {platform_counts['linkedin']} |
| Facebook | {platform_counts['facebook']} |
| Instagram | {platform_counts['instagram']} |
| **Total** | **{sum(platform_counts.values())}** |

## AI Summary

{ai_summary}

## Activity Log

{log_summary}
"""

    report_path = vault.reports / f"Social_Media_Weekly_{week_end}.md"
    report_path.write_text(report_content, encoding="utf-8")
    log.info("[Social Report] Saved: Vault/Reports/Social_Media_Weekly_%s.md", week_end)
    return str(report_path)


def main():
    parser = argparse.ArgumentParser(description="Social Media Post Scheduler")
    parser.add_argument("--facebook",  action="store_true", help="Generate Facebook post draft")
    parser.add_argument("--instagram", action="store_true", help="Generate Instagram post draft")
    parser.add_argument("--linkedin",  action="store_true", help="Generate LinkedIn post draft")
    parser.add_argument("--all",       action="store_true", help="Generate all platform drafts")
    parser.add_argument("--report",    action="store_true", help="Generate weekly social media report")
    parser.add_argument("--topic",     default="",          help="Optional topic for the post")
    args = parser.parse_args()

    if not any([args.facebook, args.instagram, args.linkedin, args.all, args.report]):
        parser.print_help()
        sys.exit(0)

    if args.report:
        path = generate_weekly_social_report()
        print(f"\nWeekly social media report saved: {path}\n")
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
