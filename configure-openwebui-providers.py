import json
import os
import sqlite3
import time
import urllib.request


gateway_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("API_SERVER_KEY")
ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://192.168.1.2:11434").rstrip("/")
ollama_model = os.environ.get("OLLAMA_MODEL", "qwen3-4b-gpu:latest")
if not gateway_key:
    raise SystemExit("Hermes gateway credential is missing")


def get_json(path):
    with urllib.request.urlopen(ollama_base_url + path, timeout=20) as response:
        return json.load(response)


version = get_json("/api/version")
tags = get_json("/api/tags")
models = {item.get("name") for item in tags.get("models", [])}
if ollama_model not in models:
    raise SystemExit(f"Required Ollama model is missing: {ollama_model}")

settings = {
    "openai.enable": True,
    "openai.api_base_urls": ["http://hermes-agent:8642/v1"],
    "openai.api_keys": [gateway_key],
    "openai.api_configs": {
        "0": {
            "enable": True,
            "tags": [{"name": "hermes-agent"}],
            "prefix_id": "",
            "model_ids": ["hermes-agent"],
            "connection_type": "external",
            "auth_type": "bearer",
        }
    },
    "ollama.enable": True,
    "ollama.base_urls": [ollama_base_url],
    "ollama.api_configs": {
        "0": {
            "enable": True,
            "tags": [{"name": "local-gpu"}],
            "prefix_id": "",
            "model_ids": [ollama_model],
            "connection_type": "external",
            "auth_type": "none",
        }
    },
}

db = sqlite3.connect("/app/backend/data/webui.db", timeout=30)
db.execute("pragma busy_timeout=30000")
columns = {row[1] for row in db.execute("pragma table_info(config)")}
if not {"key", "value", "updated_at"} <= columns:
    raise SystemExit("Unsupported Open WebUI config schema; expected v0.10 key/value storage")

updated_at = int(time.time())
with db:
    for key, value in settings.items():
        db.execute(
            """
            insert into config (key, value, updated_at) values (?, ?, ?)
            on conflict(key) do update set value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, json.dumps(value, separators=(",", ":")), updated_at),
        )

integrity = db.execute("pragma integrity_check").fetchone()[0]
db.close()
print(f"integrity={integrity}")
print(f"ollama_version={version.get('version', 'unknown')}")
print(f"ollama_model={ollama_model}")
print("openai_connections=1")
print("ollama_connections=1")
