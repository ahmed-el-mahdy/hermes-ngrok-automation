#!/opt/hermes/.venv/bin/python
"""Small, secret-safe runtime control surface for Hermes."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import tempfile
from datetime import datetime, timezone

import yaml


CONFIG_PATH = Path(os.environ.get("HERMES_CONFIG", "/opt/data/config.yaml"))
ENV_PATH = Path(os.environ.get("HERMES_ENV", "/opt/data/.env"))
BACKUP_DIR = Path(os.environ.get("HERMES_BACKUP_DIR", "/opt/data/backups/runtime"))
OPENROUTER_URL = "https://openrouter.ai/api/v1"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"

ALIASES = {
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
            state = "ready" if model["credential"] in available else "missing-key"
            print(
                f"{alias}: {model['provider']}/{model['default']} [{state}]"
            )
        return 0

    selected = ALIASES[args.alias]
    if selected["credential"] not in configured_names():
        parser.error(
            f"{selected['credential']} is not configured; model was not changed"
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
