#!/opt/hermes/.venv/bin/python
"""Small, secret-safe runtime control surface for Hermes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
from datetime import datetime, timezone
import urllib.error
import urllib.request

import yaml


CONFIG_PATH = Path(os.environ.get("HERMES_CONFIG", "/opt/data/config.yaml"))
ENV_PATH = Path(os.environ.get("HERMES_ENV", "/opt/data/.env"))
BACKUP_DIR = Path(os.environ.get("HERMES_BACKUP_DIR", "/opt/data/backups/runtime"))
OPENROUTER_URL = "https://openrouter.ai/api/v1"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"
NARAROUTER_URL = "https://router.bynara.id/v1"
NARAROUTER_PLANS_URL = "https://router.bynara.id/api/plans"
OLLAMA_BRIDGE_URL = "http://ollama-bridge:8000/v1"

ALIASES = {
    "nara-mistral": {
        "provider": "nararouter",
        "default": "mistral-large",
        "base_url": NARAROUTER_URL,
        "credential": "NARAROUTER_API_KEY",
    },
    "nara-glm": {
        "provider": "nararouter",
        "default": "glm-5.2-free",
        "base_url": NARAROUTER_URL,
        "credential": "NARAROUTER_API_KEY",
    },
    "local-gpu": {
        "provider": "ollama-local",
        "default": "qwen3-4b-gpu:latest",
        "base_url": OLLAMA_BRIDGE_URL,
        "credential": None,
    },
    "openrouter-gpt": {
        "provider": "openrouter",
        "default": "openai/gpt-oss-20b:free",
        "base_url": OPENROUTER_URL,
        "credential": "OPENROUTER_API_KEY",
    },
    "openrouter-free": {
        "provider": "openrouter",
        "default": "openrouter/free",
        "base_url": OPENROUTER_URL,
        "credential": "OPENROUTER_API_KEY",
    },
    "openrouter-nemotron": {
        "provider": "openrouter",
        "default": "nvidia/nemotron-3-super-120b-a12b:free",
        "base_url": OPENROUTER_URL,
        "credential": "OPENROUTER_API_KEY",
    },
    "gemini-fast": {
        "provider": "gemini",
        "default": "gemini-3.1-flash-lite",
        "base_url": GEMINI_URL,
        "credential": "GOOGLE_API_KEY",
    },
    "gemini-stable": {
        "provider": "gemini",
        "default": "gemini-2.5-flash",
        "base_url": GEMINI_URL,
        "credential": "GOOGLE_API_KEY",
    },
}


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}


def configured_names() -> set[str]:
    names: set[str] = set()
    if ENV_PATH.exists():
        for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                if value.strip():
                    names.add(name.strip())
    names.update(name for name, value in os.environ.items() if value)
    return names


def configured_value(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if ENV_PATH.exists():
        for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                current_name, current_value = line.split("=", 1)
                if current_name.strip() == name:
                    return current_value.strip()
    return ""


def fetch_json(url: str, *, api_key: str = "") -> tuple[dict, dict[str, str]]:
    headers = {"User-Agent": "hermes-admin/1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
        quota_headers = {
            name.lower(): value
            for name, value in response.headers.items()
            if any(
                token in name.lower()
                for token in ("limit", "remaining", "reset", "quota")
            )
        }
    return payload, quota_headers


def print_quota() -> int:
    """Report documented limits without inventing an account balance."""
    try:
        plans, _ = fetch_json(NARAROUTER_PLANS_URL)
        free = next(
            (
                item
                for item in plans.get("data", [])
                if isinstance(item, dict) and item.get("code") == "free"
            ),
            None,
        )
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(f"nararouter_public_limits=unavailable ({type(exc).__name__})")
        free = None

    if free:
        print("nararouter_free_plan=active")
        print(f"nararouter_free_daily_tokens={free.get('token_cap_daily', '')}")
        print(f"nararouter_free_requests_per_minute={free.get('rpm_limit', '')}")
        print(
            "nararouter_free_models="
            + ",".join(str(model) for model in free.get("models", []))
        )
    else:
        print("nararouter_free_plan=unknown")

    key = configured_value("NARAROUTER_API_KEY")
    if key:
        try:
            models, quota_headers = fetch_json(
                f"{NARAROUTER_URL}/models", api_key=key
            )
            entitled = [
                item.get("id")
                for item in models.get("data", [])
                if isinstance(item, dict) and item.get("id")
            ]
            print(f"nararouter_authenticated_model_count={len(entitled)}")
            if quota_headers:
                for name, value in sorted(quota_headers.items()):
                    print(f"nararouter_header_{name}={value}")
            else:
                print("nararouter_quota_headers=not-provided")
        except (OSError, ValueError, urllib.error.URLError) as exc:
            print(
                "nararouter_authenticated_probe="
                f"unavailable ({type(exc).__name__})"
            )
    else:
        print("nararouter_authenticated_probe=missing-key")

    print("nararouter_exact_plan=dashboard-only")
    print("nararouter_exact_remaining_tokens=dashboard-only")
    print("nararouter_reset_free_plan=00:00_UTC")
    print("local_gpu_cloud_quota=none")
    print("local_gpu_limits=hardware,context,concurrency")
    return 0


def atomic_write(config: dict) -> Path:
    stat = CONFIG_PATH.stat()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUP_DIR / f"config-{stamp}.yaml"
    shutil.copy2(CONFIG_PATH, backup)

    payload = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=CONFIG_PATH.parent, delete=False
    ) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)
    os.chmod(temp_path, stat.st_mode & 0o777)
    try:
        os.chown(temp_path, stat.st_uid, stat.st_gid)
    except PermissionError:
        pass
    os.replace(temp_path, CONFIG_PATH)
    return backup


def print_status(config: dict) -> None:
    model = config.get("model") or {}
    print(f"primary={model.get('provider', '')}/{model.get('default', '')}")
    for index, fallback in enumerate(config.get("fallback_providers") or [], start=1):
        print(
            f"fallback_{index}="
            f"{fallback.get('provider', '')}/{fallback.get('model', '')}"
        )
    print(f"config={CONFIG_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect or select an approved Hermes model without exposing secrets."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("models")
    subparsers.add_parser("quota")
    use = subparsers.add_parser("use")
    use.add_argument("alias", choices=sorted(ALIASES))
    args = parser.parse_args()

    config = load_config()
    if args.command == "status":
        print_status(config)
        return 0
    if args.command == "models":
        available = configured_names()
        for alias, model in ALIASES.items():
            credential = model["credential"]
            state = (
                "ready"
                if credential is None or credential in available
                else "missing-key"
            )
            print(
                f"{alias}: {model['provider']}/{model['default']} [{state}]"
            )
        return 0
    if args.command == "quota":
        return print_quota()

    selected = ALIASES[args.alias]
    credential = selected["credential"]
    if credential is not None and credential not in configured_names():
        parser.error(
            f"{credential} is not configured; model was not changed"
        )
    config["model"] = {
        "default": selected["default"],
        "provider": selected["provider"],
        "base_url": selected["base_url"],
    }
    backup = atomic_write(config)
    print(f"selected={args.alias}")
    print(f"backup={backup}")
    print("applies_to=new_sessions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
