from dotenv import load_dotenv
from pathlib import Path
import os, requests
from datetime import datetime

load_dotenv(Path(".env"))
token = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN", "")
app_id = os.environ.get("FACEBOOK_APP_ID", "")
app_secret = os.environ.get("FACEBOOK_APP_SECRET", "")

r = requests.get(
    "https://graph.facebook.com/v19.0/debug_token",
    params={"input_token": token, "access_token": f"{app_id}|{app_secret}"},
)
data = r.json().get("data", {})

expires_at = data.get("expires_at", 0)
is_valid = data.get("is_valid", False)
token_type = data.get("type", "unknown")
scopes = data.get("scopes", [])

print(f"Valid:      {is_valid}")
print(f"Type:       {token_type}")
if expires_at == 0:
    print("Expiry:     NEVER (long-lived page token)")
else:
    exp_dt = datetime.fromtimestamp(expires_at)
    days_left = (exp_dt - datetime.now()).days
    print(f"Expiry:     {exp_dt.strftime('%Y-%m-%d %H:%M')} ({days_left} days left)")
print(f"Scopes:     {', '.join(scopes)}")
