#!/opt/hermes/.venv/bin/python
"""Check Telegram connectivity without printing the bot token or user IDs."""

from __future__ import annotations

import json
import os
import urllib.request


token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
allowed_users = os.environ.get("TELEGRAM_ALLOWED_USERS", "").strip()
if not token:
    raise SystemExit("telegram_configured=false")
if not allowed_users:
    raise SystemExit("telegram_allowlist=false")

request = urllib.request.Request(
    f"https://api.telegram.org/bot{token}/getMe",
    headers={"User-Agent": "HermesTelegramValidator/1.0"},
)
with urllib.request.urlopen(request, timeout=10) as response:
    payload = json.loads(response.read().decode("utf-8"))

result = payload.get("result") or {}
report = {
    "telegram_api": response.status == 200 and payload.get("ok") is True,
    "bot_username": result.get("username", ""),
    "allowlist_configured": True,
}
print(json.dumps(report))
raise SystemExit(0 if report["telegram_api"] else 1)
