"""
Exchange a short-lived user token for a long-lived one,
then get the permanent page access token and update .env.
Usage: uv run python make_longlived_token.py --user-token "EAA..."
"""
import argparse, os, re, requests
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(".env")
load_dotenv(env_path)

APP_ID = os.environ.get("FACEBOOK_APP_ID", "")
APP_SECRET = os.environ.get("FACEBOOK_APP_SECRET", "")
PAGE_ID = os.environ.get("FACEBOOK_PAGE_ID", "").strip("'")

parser = argparse.ArgumentParser()
parser.add_argument("--user-token", required=True, help="Short-lived user access token from Graph API Explorer")
args = parser.parse_args()

# Step 1: Exchange for long-lived user token
print("Step 1: Exchanging for long-lived user token...")
r = requests.get(
    "https://graph.facebook.com/v19.0/oauth/access_token",
    params={
        "grant_type": "fb_exchange_token",
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "fb_exchange_token": args.user_token,
    },
)
data = r.json()
if "access_token" not in data:
    print(f"ERROR: {data}")
    raise SystemExit(1)
long_lived_user_token = data["access_token"]
expires_in = data.get("expires_in", "unknown")
print(f"  Long-lived user token obtained (expires in {expires_in}s ~ 60 days)")

# Step 2: Get permanent page token from /me/accounts
print("Step 2: Getting permanent page access token...")
r2 = requests.get(
    "https://graph.facebook.com/v19.0/me/accounts",
    params={"access_token": long_lived_user_token},
)
accounts = r2.json().get("data", [])
page_token = None
for page in accounts:
    if page.get("id") == PAGE_ID:
        page_token = page.get("access_token")
        break

if not page_token:
    print(f"ERROR: Page {PAGE_ID} not found in /me/accounts. Got: {accounts}")
    raise SystemExit(1)
print(f"  Page token obtained.")

# Step 3: Verify it never expires
print("Step 3: Verifying token expiry...")
r3 = requests.get(
    "https://graph.facebook.com/v19.0/debug_token",
    params={"input_token": page_token, "access_token": f"{APP_ID}|{APP_SECRET}"},
)
debug = r3.json().get("data", {})
expires_at = debug.get("expires_at", -1)
expiry_str = "NEVER (permanent)" if expires_at == 0 else f"expires_at={expires_at}"
print(f"  Token type: {debug.get('type')} | Expiry: {expiry_str}")

# Step 4: Update .env
env_text = env_path.read_text(encoding="utf-8")
new_text = re.sub(
    r"^FACEBOOK_PAGE_ACCESS_TOKEN=.*$",
    f"FACEBOOK_PAGE_ACCESS_TOKEN={page_token}",
    env_text,
    flags=re.MULTILINE,
)
env_path.write_text(new_text, encoding="utf-8")
print("\nSUCCESS: .env updated with permanent page access token.")
