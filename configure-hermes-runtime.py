#!/usr/bin/env python3
"""Apply durable runtime defaults to the persistent Hermes configuration."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

import yaml


CONFIG_PATH = Path("/opt/data/config.yaml")
ENV_PATH = Path("/opt/data/.env")
OPENROUTER_URL = "https://openrouter.ai/api/v1"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"


def configured_names() -> set[str]:
    names: set[str] = set()
    if ENV_PATH.exists():
        for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                if value.strip():
                    names.add(name.strip())
    return names


def replace_policy(existing: str, marker: str, policy: str) -> str:
    text = existing.strip()
    if marker in text:
        text = text.split(marker, 1)[0].rstrip()
    return (text + "\n\n" + policy).strip()


def atomic_write(config: dict) -> None:
    stat = CONFIG_PATH.stat()
    payload = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=CONFIG_PATH.parent, delete=False
    ) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)
    os.chmod(temp_path, stat.st_mode & 0o777)
    os.chown(temp_path, stat.st_uid, stat.st_gid)
    os.replace(temp_path, CONFIG_PATH)


config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
available = configured_names()
has_openrouter = "OPENROUTER_API_KEY" in available

if has_openrouter:
    config["model"] = {
        "default": "nvidia/nemotron-3-super-120b-a12b:free",
        "provider": "openrouter",
        "base_url": OPENROUTER_URL,
    }
    config["fallback_providers"] = [
        {
            "provider": "openrouter",
            "model": "openai/gpt-oss-20b:free",
            "base_url": OPENROUTER_URL,
        },
        {
            "provider": "openrouter",
            "model": "openrouter/free",
            "base_url": OPENROUTER_URL,
        },
        {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "base_url": GEMINI_URL,
        },
    ]
else:
    config["fallback_providers"] = [
        {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "base_url": GEMINI_URL,
        }
    ]

agent = config.setdefault("agent", {})
agent["max_turns"] = 20
agent["gateway_timeout"] = 300
agent["api_max_retries"] = 1
agent["gateway_timeout_warning"] = 45
agent["gateway_notify_interval"] = 30
agent["tool_use_enforcement"] = ["gemini", "openrouter"]

policy = """[HERMES_RUNTIME_POLICY]
Act autonomously on the user's approved tasks and verify real results before claiming completion. Never present an earlier session's test report as current; rerun a short current check and cite its actual result. For routine readiness checks, run hermes-smoke-test. Never run the full /opt/hermes/tests suite or gateway integration tests as a capability check. /opt/hermes is an immutable application directory: do not change its ownership or write caches there. If the user explicitly requests a targeted source test, run only the relevant test file with a timeout, --basetemp=/opt/data/tmp/pytest, and -o cache_dir=/opt/data/cache/pytest. Missing configuration for disabled optional platforms such as Discord or Spotify is informational, not a failed core check. Use built-in tools directly: web_search/web_extract/browser_snapshot are tools, not skills, so never call skill_view for them. web_search uses the key-free DDGS backend. If web_extract reports that no extraction provider is configured, use browser_navigate plus browser_snapshot, or bounded Python requests with Beautiful Soup, instead of retrying web_extract. The hermes and hermes-admin commands are available on PATH; use hermes-admin status/models/use for safe model inspection and switching, and never ask the user to expose config files or API keys. PDF, DOCX, spreadsheet, OCR, HTML parsing, pip, and uv support are already installed. Do not use sudo. Install extra Python packages with pip; packages persist under /opt/data/python-packages. Cron scripts belong in ~/.hermes/scripts and cronjob receives the script filename, never an absolute path. Never present placeholder or fabricated data as live. For network, shell, browser, and delegated work, use bounded operations; after two identical failures change approach, and never repeat the same command indefinitely. For long work, send concise progress updates, preserve partial evidence, and finish with verified outcomes and any remaining limitation."""
agent["system_prompt"] = replace_policy(
    str(agent.get("system_prompt") or ""), "[HERMES_RUNTIME_POLICY]", policy
)

approvals = config.setdefault("approvals", {})
approvals["mode"] = "smart"
approvals["timeout"] = 60
approvals["cron_mode"] = "approve"

guardrails = config.setdefault("tool_loop_guardrails", {})
guardrails["warnings_enabled"] = True
guardrails["hard_stop_enabled"] = True
guardrails["warn_after"] = {
    "exact_failure": 2,
    "same_tool_failure": 3,
    "idempotent_no_progress": 2,
}
guardrails["hard_stop_after"] = {
    "exact_failure": 3,
    "same_tool_failure": 4,
    "idempotent_no_progress": 3,
}

terminal = config.setdefault("terminal", {})
terminal["timeout"] = 90
terminal["lifetime_seconds"] = 180
terminal["cwd"] = "/opt/data/home"
terminal["shell_init_files"] = ["/opt/data/home/.hermes_env"]

code_execution = config.setdefault("code_execution", {})
code_execution["timeout"] = 120
code_execution["max_tool_calls"] = 30

web = config.setdefault("web", {})
web["search_backend"] = "ddgs"

delegation = config.setdefault("delegation", {})
delegation["max_iterations"] = 15
delegation["child_timeout_seconds"] = 180
delegation["max_concurrent_children"] = 2

config.setdefault("cron", {})["max_parallel_jobs"] = 1

providers = config.setdefault("providers", {})
openrouter = providers.setdefault("openrouter", {})
openrouter["request_timeout_seconds"] = 60
openrouter["stale_timeout_seconds"] = 45
gemini = providers.setdefault("gemini", {})
gemini["request_timeout_seconds"] = 45
gemini["stale_timeout_seconds"] = 30

if has_openrouter:
    for settings in (config.get("auxiliary") or {}).values():
        if isinstance(settings, dict):
            settings["provider"] = "openrouter"
            settings["model"] = "openrouter/free"
            settings["base_url"] = OPENROUTER_URL
            settings["api_key"] = ""

atomic_write(config)
print(f"openrouter_ready={str(has_openrouter).lower()}")
print(f"primary={config['model']['provider']}/{config['model']['default']}")
print(f"fallback_count={len(config.get('fallback_providers') or [])}")
