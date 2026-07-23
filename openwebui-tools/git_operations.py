"""
title: Git Operations
description: Run Git subcommands inside repositories under the Hermes workspace.
version: 2.0.0
"""

import json
import shlex
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        workspace: str = Field(default="/app/backend/data/hermes_workspace")
        timeout: int = Field(default=60, ge=1, le=300)

    def __init__(self):
        self.valves = self.Valves()
        Path(self.valves.workspace).mkdir(parents=True, exist_ok=True)

    def _repo(self, repo: str) -> Path:
        root = Path(self.valves.workspace).resolve()
        path = (root / (repo or ".")).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("Repository must remain inside the Hermes workspace") from exc
        if not path.is_dir():
            raise ValueError("Repository directory not found")
        return path

    def git_command(self, repo: str, command: str) -> str:
        """Run a Git subcommand in a workspace repository, for example status or log --oneline -5."""
        try:
            if any(token in command for token in ("\n", ";", "|", "&", ">", "<", "`", "$(")):
                raise ValueError("Shell operators are not allowed")
            args = shlex.split(command, posix=True)
            if not args:
                raise ValueError("Git command is empty")
            result = subprocess.run(
                ["git", *args],
                cwd=self._repo(repo),
                capture_output=True,
                text=True,
                timeout=self.valves.timeout,
                shell=False,
            )
            return json.dumps({"stdout": result.stdout[:10000], "stderr": result.stderr[:3000], "rc": result.returncode})
        except subprocess.TimeoutExpired:
            return json.dumps({"status": "error", "error": "Git command timed out"})
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)})
