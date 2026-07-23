"""
title: Hermes Persistent Memory
description: Store and recall durable key-value memory in the mounted Hermes workspace.
version: 2.0.0
"""

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path


MEMORY_FILE = Path("/app/backend/data/hermes_workspace/.agent_memory.json")
LOCK_FILE = MEMORY_FILE.with_suffix(".lock")


class Tools:
    def __init__(self):
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not MEMORY_FILE.exists():
            MEMORY_FILE.write_text("{}\n", encoding="utf-8")

    def _load(self):
        try:
            value = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _mutate(self, callback):
        LOCK_FILE.touch(exist_ok=True)
        with LOCK_FILE.open("r+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            data = self._load()
            result = callback(data)
            tmp = MEMORY_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, MEMORY_FILE)
            return result

    def hermes_memory_debug(self) -> str:
        """Show the persistent memory file path, existence, and stored namespaces."""
        data = self._load()
        return json.dumps({"memory_file": str(MEMORY_FILE), "exists": MEMORY_FILE.exists(), "agents": sorted(k for k in data if k != "_meta")}, indent=2)

    def hermes_remember(self, key: str, value: str, agent: str = "hermes") -> str:
        """Store a key-value pair in an agent namespace."""
        if not key.strip() or not agent.strip():
            return json.dumps({"status": "error", "error": "agent and key are required"})

        def update(data):
            data.setdefault(agent, {})[key] = value
            data.setdefault("_meta", {})["last_write_utc"] = datetime.now(timezone.utc).isoformat()
            data["_meta"]["memory_file"] = str(MEMORY_FILE)

        self._mutate(update)
        return json.dumps({"status": "stored", "memory_file": str(MEMORY_FILE), "agent": agent, "key": key}, indent=2)

    def hermes_recall(self, key: str, agent: str = "hermes") -> str:
        """Recall one key from an agent namespace."""
        data = self._load()
        found = key in data.get(agent, {})
        return json.dumps({"memory_file": str(MEMORY_FILE), "agent": agent, "key": key, "found": found, "value": data.get(agent, {}).get(key)}, indent=2)

    def hermes_list_memories(self, agent: str = "hermes") -> str:
        """List keys in an agent namespace."""
        data = self._load()
        return json.dumps({"memory_file": str(MEMORY_FILE), "agent": agent, "keys": sorted(data.get(agent, {}))}, indent=2)

    def hermes_forget(self, key: str, agent: str = "hermes") -> str:
        """Delete one key from an agent namespace."""
        def update(data):
            existed = key in data.get(agent, {})
            data.get(agent, {}).pop(key, None)
            return existed

        existed = self._mutate(update)
        return json.dumps({"status": "deleted" if existed else "missing", "memory_file": str(MEMORY_FILE), "agent": agent, "key": key}, indent=2)
