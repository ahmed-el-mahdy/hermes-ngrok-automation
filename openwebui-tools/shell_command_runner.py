"""
title: Shell Command Runner
description: Run approved commands in the Hermes workspace without shell expansion.
version: 2.0.0
"""

import json
import os
import shlex
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        allowed: str = Field(default="pwd,ls,cat,grep,find,mkdir,cp,mv,pip,pip3,npm,python3,node,git,curl,wget,echo,touch,bash")
        workspace: str = Field(default="/app/backend/data/hermes_workspace")
        timeout: int = Field(default=120, ge=1, le=600)

    def __init__(self):
        self.valves = self.Valves()
        Path(self.valves.workspace).mkdir(parents=True, exist_ok=True)

    def run_shell(self, command: str) -> str:
        """Run one approved command. Pipes, redirection, command substitution, and bash -c are rejected."""
        try:
            if any(token in command for token in ("\n", ";", "|", "&", ">", "<", "`", "$(")):
                raise ValueError("Shell operators are not allowed; run one command at a time")
            args = shlex.split(command, posix=True)
            if not args:
                raise ValueError("Command is empty")
            allowed = {item.strip() for item in self.valves.allowed.split(",") if item.strip()}
            base = os.path.basename(args[0])
            if base not in allowed:
                raise ValueError(f"Command '{base}' is not allowed")
            if base == "bash" and (len(args) < 2 or args[1].startswith("-")):
                raise ValueError("bash may run workspace script files only")
            result = subprocess.run(
                args,
                cwd=self.valves.workspace,
                capture_output=True,
                text=True,
                timeout=self.valves.timeout,
                shell=False,
                env={**os.environ, "HOME": self.valves.workspace},
            )
            return json.dumps({"stdout": result.stdout[:10000], "stderr": result.stderr[:3000], "rc": result.returncode})
        except subprocess.TimeoutExpired:
            return json.dumps({"status": "error", "error": "Command timed out"})
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)})
