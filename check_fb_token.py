from dotenv import load_dotenv
from pathlib import Path
import os, requests, json

load_dotenv(Path(".env"))
token = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN", "")
page_id = os.environ.get("FACEBOOK_PAGE_ID", "")

print(f"Token prefix: {token[:25]}...")
print(f"Page ID: {page_id}\n")

# Who does this token belong to?
r = requests.get("https://graph.facebook.com/v19.0/me", params={"access_token": token, "fields": "id,name"})
print(f"Token identity: {r.json()}\n")

# What permissions does it have?
r2 = requests.get("https://graph.facebook.com/v19.0/me/permissions", params={"access_token": token})
data = r2.json()
print("Permissions granted:")
for p in data.get("data", []):
    print(f"  {p['permission']}: {p['status']}")

# Try /me/accounts to see if page token is accessible
r3 = requests.get("https://graph.facebook.com/v19.0/me/accounts", params={"access_token": token})
print(f"\n/me/accounts response: {json.dumps(r3.json(), indent=2)}")
