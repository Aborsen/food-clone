"""One-time script to register the Telegram webhook URL.

Run locally after deploying to Vercel:
    python scripts/set_webhook.py

Requires these in .env:
    TELEGRAM_BOT_TOKEN
    WEBHOOK_SECRET
    VERCEL_URL          (e.g. your-app.vercel.app — no https://, no trailing slash)
"""
import os
import sys

import httpx

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def main() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    secret = os.getenv("WEBHOOK_SECRET")
    vercel_url = os.getenv("VERCEL_URL")

    missing = [k for k, v in {
        "TELEGRAM_BOT_TOKEN": token,
        "WEBHOOK_SECRET": secret,
        "VERCEL_URL": vercel_url,
    }.items() if not v]
    if missing:
        print(f"Missing env vars: {', '.join(missing)}", file=sys.stderr)
        return 1

    # Strip protocol / trailing slash if user accidentally included them
    vercel_url = vercel_url.replace("https://", "").replace("http://", "").rstrip("/")
    webhook_url = f"https://{vercel_url}/api/webhook"

    resp = httpx.post(
        f"https://api.telegram.org/bot{token}/setWebhook",
        json={
            "url": webhook_url,
            "secret_token": secret,
            "allowed_updates": ["message", "callback_query"],
        },
        timeout=15,
    )
    data = resp.json()
    print(f"→ setWebhook to {webhook_url}")
    print(data)
    return 0 if data.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
