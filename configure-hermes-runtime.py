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
NARAROUTER_URL = "https://router.bynara.id/v1"
OLLAMA_BRIDGE_URL = "http://ollama-bridge:8000/v1"
LOCAL_MODEL = "qwen3-4b-gpu:latest"


def configured_names() -> set[str]:
    names = {name for name, value in os.environ.items() if value}
    if ENV_PATH.exists():
        for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                if value.strip():
                    names.add(name.strip())
    return names


def upsert_custom_provider(
    config: dict,
    *,
    name: str,
    base_url: str,
    model: str,
    key_env: str = "",
    api_key: str = "",
) -> None:
    providers = config.setdefault("custom_providers", [])
    if not isinstance(providers, list):
        providers = []
        config["custom_providers"] = providers
    entry = next(
        (
            item
            for item in providers
            if isinstance(item, dict) and item.get("name") == name
        ),
        None,
    )
    if entry is None:
        entry = {"name": name}
        providers.append(entry)
    entry.update(
        {
            "base_url": base_url,
            "model": model,
            "api_mode": "chat_completions",
        }
    )
    if key_env:
        entry["key_env"] = key_env
        entry.pop("api_key", None)
    else:
        entry["api_key"] = api_key or "no-key-required"
        entry.pop("key_env", None)


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
has_gemini = bool(
    {"GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"} & available
)
has_nararouter = "NARAROUTER_API_KEY" in available

upsert_custom_provider(
    config,
    name="ollama-local",
    base_url=OLLAMA_BRIDGE_URL,
    model=LOCAL_MODEL,
)
if has_nararouter:
    upsert_custom_provider(
        config,
        name="nararouter",
        base_url=NARAROUTER_URL,
        model="mistral-large",
        key_env="NARAROUTER_API_KEY",
    )

fallbacks = [
    {
        "provider": "ollama-local",
        "model": LOCAL_MODEL,
        "base_url": OLLAMA_BRIDGE_URL,
    }
]

if has_nararouter:
    config["model"] = {
        "default": "mistral-large",
        "provider": "nararouter",
        "base_url": NARAROUTER_URL,
    }
    fallbacks.append(
        {
            "provider": "nararouter",
            "model": "glm-5.2-free",
            "base_url": NARAROUTER_URL,
        }
    )
elif has_openrouter:
    config["model"] = {
        "default": "nvidia/nemotron-3-super-120b-a12b:free",
        "provider": "openrouter",
        "base_url": OPENROUTER_URL,
    }
elif has_gemini:
    config["model"] = {
        "default": "gemini-2.5-flash",
        "provider": "gemini",
        "base_url": GEMINI_URL,
    }
else:
    config["model"] = {
        "default": LOCAL_MODEL,
        "provider": "ollama-local",
        "base_url": OLLAMA_BRIDGE_URL,
    }
    fallbacks = []

if has_openrouter:
    fallbacks.extend(
        [
            {
                "provider": "openrouter",
                "model": "nvidia/nemotron-3-super-120b-a12b:free",
                "base_url": OPENROUTER_URL,
            },
            {
                "provider": "openrouter",
                "model": "openrouter/free",
                "base_url": OPENROUTER_URL,
            },
        ]
    )
if has_gemini and config.get("model", {}).get("provider") != "gemini":
    fallbacks.append(
        {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "base_url": GEMINI_URL,
        }
    )
config["fallback_providers"] = fallbacks

agent = config.setdefault("agent", {})
agent["max_turns"] = 20
agent["gateway_timeout"] = 300
agent["api_max_retries"] = 1
agent["gateway_timeout_warning"] = 45
agent["gateway_notify_interval"] = 30
agent["tool_use_enforcement"] = ["gemini", "openrouter"]
agent["verify_on_stop"] = "auto"

delegation_route = (
    "NaraRouter mistral-large with the local GPU Qwen route as its immediate "
    "automatic fallback"
    if has_nararouter
    else "the local GPU Qwen route"
)
policy = f"""[HERMES_RUNTIME_POLICY]
You are a general-purpose personal assistant and execution agent. Help across research, software, automation, documents, planning, learning, communication, analysis, and other requested domains. Treat every specialist domain as an on-demand capability, never as your permanent identity or primary objective. Act autonomously on the user's approved tasks and verify real results before claiming completion. Provider failover is automatic: never stop a task merely because one provider is rate-limited, never ask the user to switch models, and continue the same task on the next configured route. The local GPU model is the immediate fallback after the primary cloud route and does not consume cloud quota. Delegated workers use {delegation_route}; do not override that route in a task prompt. Delegate only a clearly bounded unit of work with explicit completion criteria, avoid duplicate delegations, and wait for the existing child result before spawning a replacement. A provider quota or availability failure is recoverable through the inherited fallback chain and is not a reason to abandon the delegated task. Never present an earlier session's test report as current; rerun a short current check and cite its actual result. When the user speaks Arabic, answer entirely in natural Egyptian Arabic; keep only commands, paths, model IDs, and unavoidable technical terms in English, and never insert unrelated words from other languages. The progress label iteration X/Y is the agent loop count, not a test count; explain this distinction if reporting tests. For routine readiness checks, run hermes-smoke-test and report its exact passed_count/check_count values. Never run the full /opt/hermes/tests suite or gateway integration tests as a capability check. /opt/hermes is an immutable application directory: do not change its ownership or write caches there. If the user explicitly requests a targeted source test, run only the relevant test file with a timeout, --basetemp=/opt/data/tmp/pytest, and -o cache_dir=/opt/data/cache/pytest. Missing configuration for disabled optional platforms such as Discord or Spotify is informational, not a failed core check. Use built-in tools directly: web_search/web_extract/browser_snapshot are tools, not skills, so never call skill_view for them. web_search uses the key-free DDGS backend. If web_extract reports that no extraction provider is configured, use browser_navigate plus browser_snapshot, or bounded Python requests with Beautiful Soup, instead of retrying web_extract. The hermes and hermes-admin commands are available on PATH; use hermes-admin status/models/use for safe model inspection and switching, and never ask the user to expose config files or API keys. PDF, DOCX, spreadsheet, OCR, HTML parsing, pip, and uv support are already installed. Do not use sudo. Install extra Python packages with pip; packages persist under /opt/data/python-packages. Cron scripts belong in ~/.hermes/scripts and cronjob receives the script filename, never an absolute path. Never present placeholder or fabricated data as live. For network, shell, browser, and delegated work, use bounded operations; after two identical failures change approach, and never repeat the same command indefinitely. For long work, send concise progress updates, preserve partial evidence, and finish with verified outcomes and any remaining limitation."""
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
delegation["provider"] = "nararouter" if has_nararouter else "ollama-local"
delegation["model"] = "mistral-large" if has_nararouter else LOCAL_MODEL
delegation["base_url"] = ""
delegation["api_key"] = ""
delegation["api_mode"] = ""
delegation["max_iterations"] = 20
delegation["child_timeout_seconds"] = 600
delegation["max_concurrent_children"] = 1
delegation["max_spawn_depth"] = 1
delegation["max_summary_chars"] = 12000

config.setdefault("cron", {})["max_parallel_jobs"] = 1

providers = config.setdefault("providers", {})
nara = providers.setdefault("nararouter", {})
nara["request_timeout_seconds"] = 60
nara["stale_timeout_seconds"] = 15
ollama_local = providers.setdefault("ollama-local", {})
ollama_local["request_timeout_seconds"] = 180
ollama_local["stale_timeout_seconds"] = 60
openrouter = providers.setdefault("openrouter", {})
openrouter["request_timeout_seconds"] = 60
openrouter["stale_timeout_seconds"] = 45
gemini = providers.setdefault("gemini", {})
gemini["request_timeout_seconds"] = 45
gemini["stale_timeout_seconds"] = 30

for settings in (config.get("auxiliary") or {}).values():
    if isinstance(settings, dict):
        settings["provider"] = "auto"
        settings["model"] = ""
        settings["base_url"] = ""
        settings["api_key"] = ""

atomic_write(config)
print(f"nararouter_ready={str(has_nararouter).lower()}")
print(f"openrouter_ready={str(has_openrouter).lower()}")
print(f"gemini_ready={str(has_gemini).lower()}")
print(f"primary={config['model']['provider']}/{config['model']['default']}")
print(f"fallback_count={len(config.get('fallback_providers') or [])}")
