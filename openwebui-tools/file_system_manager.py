"""
title: File System Manager
description: Safely read, write, list, and delete files inside the Hermes workspace.
version: 2.0.0
"""

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field


WORKSPACE = Path("/app/backend/data/hermes_workspace")


class Tools:
    class Valves(BaseModel):
        workspace: str = Field(default=str(WORKSPACE))
        max_read_bytes: int = Field(default=1_000_000, ge=1, le=10_000_000)
        max_write_bytes: int = Field(default=2_000_000, ge=1, le=20_000_000)

    def __init__(self):
        self.valves = self.Valves()
        Path(self.valves.workspace).mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        root = Path(self.valves.workspace).resolve()
        candidate = (root / (path or ".")).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("Path must remain inside the Hermes workspace") from exc
        return candidate

    def read_file(self, path: str) -> str:
        """Read a UTF-8 file using a workspace-relative path."""
        try:
            full = self._resolve(path)
            if not full.is_file():
                return json.dumps({"status": "error", "error": "File not found", "path": path})
            if full.stat().st_size > self.valves.max_read_bytes:
                return json.dumps({"status": "error", "error": "File exceeds read limit", "path": path})
            return full.read_text(encoding="utf-8")
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc), "path": path})

    def write_file(self, path: str, content: str) -> str:
        """Atomically write UTF-8 content to a workspace-relative path."""
        try:
            encoded = content.encode("utf-8")
            if len(encoded) > self.valves.max_write_bytes:
                raise ValueError("Content exceeds write limit")
            full = self._resolve(path)
            full.parent.mkdir(parents=True, exist_ok=True)
            tmp = full.with_name(full.name + ".tmp")
            tmp.write_bytes(encoded)
            os.replace(tmp, full)
            return json.dumps({"status": "written", "path": str(full.relative_to(Path(self.valves.workspace).resolve())), "bytes": len(encoded)})
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc), "path": path})

    def list_files(self, directory: str = "") -> str:
        """List files recursively beneath a workspace-relative directory."""
        try:
            root = Path(self.valves.workspace).resolve()
            folder = self._resolve(directory)
            if not folder.exists():
                return json.dumps([])
            files = [str(item.relative_to(root)) for item in folder.rglob("*") if item.is_file()]
            return json.dumps(sorted(files)[:500], indent=2)
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc), "directory": directory})

    def delete_file(self, path: str) -> str:
        """Delete one regular file inside the workspace."""
        try:
            full = self._resolve(path)
            if not full.is_file():
                raise ValueError("File not found")
            full.unlink()
            return json.dumps({"status": "deleted", "path": path})
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc), "path": path})
