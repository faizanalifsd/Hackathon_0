"""One-shot script: reads the page token from /me/accounts and writes it to .env."""
from dotenv import load_dotenv
from pathlib import Path
import os, re, requests

env_path = Path(".env")
load_dotenv(env_path)

user_token = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN", "")
page_id = os.environ.get("FACEBOOK_PAGE_ID", "")

r = requests.get(
    "https://graph.facebook.com/v19.0/me/accounts",
    params={"access_token": user_token},
)
data = r.json()

page_token = None
for page in data.get("data", []):
    if page.get("id") == page_id:
        page_token = page.get("access_token")
        break

if not page_token:
    print("ERROR: Could not find page token for page_id", page_id)
    raise SystemExit(1)

# Replace the token line in .env
env_text = env_path.read_text(encoding="utf-8")
new_text = re.sub(
    r"^FACEBOOK_PAGE_ACCESS_TOKEN=.*$",
    f"FACEBOOK_PAGE_ACCESS_TOKEN={page_token}",
    env_text,
    flags=re.MULTILINE,
)
env_path.write_text(new_text, encoding="utf-8")
print("SUCCESS: .env updated with the correct Page Access Token.")
print(f"Token prefix: {page_token[:25]}...")
