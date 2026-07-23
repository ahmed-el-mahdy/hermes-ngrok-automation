#!/opt/hermes/.venv/bin/python
"""Check Telegram connectivity without printing the bot token or user IDs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
import time
import urllib.error
import urllib.request


STATE_PATH = Path("/opt/data/home/.hermes/state/telegram-health.json")
CACHE_MAX_AGE_SECONDS = 3600


def write_status(report: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {**report, "validated_at_epoch": time.time()}
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=STATE_PATH.parent, delete=False
    ) as handle:
        json.dump(payload, handle)
        handle.write("\n")
        temp_path = Path(handle.name)
    os.chmod(temp_path, 0o640)
    os.replace(temp_path, STATE_PATH)


parser = argparse.ArgumentParser()
parser.add_argument("--allow-cached", action="store_true")
parser.add_argument("--write-status", action="store_true")
args = parser.parse_args()


token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
allowed_users = os.environ.get("TELEGRAM_ALLOWED_USERS", "").strip()
if not token and args.allow_cached and STATE_PATH.exists():
    cached = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    age = max(0, int(time.time() - float(cached.get("validated_at_epoch", 0))))
    cached["source"] = "cached-live-check"
    cached["age_seconds"] = age
    cached["passed"] = bool(cached.get("passed")) and age <= CACHE_MAX_AGE_SECONDS
    print(json.dumps(cached))
    raise SystemExit(0 if cached["passed"] else 1)

checks = {
    "token_configured": bool(token),
    "allowlist_configured": bool(allowed_users),
}
payload: dict = {}
error = ""
if checks["token_configured"]:
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/getMe",
        headers={"User-Agent": "HermesTelegramValidator/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
            checks["telegram_api"] = response.status == 200 and payload.get("ok") is True
    except (OSError, ValueError, urllib.error.URLError) as exc:
        checks["telegram_api"] = False
        error = f"{type(exc).__name__}: {exc}"
else:
    checks["telegram_api"] = False

result = payload.get("result") or {}
failed_checks = sorted(name for name, passed in checks.items() if not passed)
report = {
    "passed": not failed_checks,
    "passed_count": sum(1 for passed in checks.values() if passed),
    "check_count": len(checks),
    "failed_checks": failed_checks,
    "checks": checks,
    "bot_username": result.get("username", ""),
    "source": "live-api",
}
if error:
    report["error"] = error
if args.write_status and report["passed"]:
    write_status(report)
print(json.dumps(report))
raise SystemExit(0 if report["passed"] else 1)
