"""
title: Code Executor
description: Execute Python, Bash, or Node.js with bounded runtime and output.
version: 2.0.0
"""

import json
import os
import subprocess
import tempfile

from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        timeout: int = Field(default=60, ge=1, le=300)
        max_output_chars: int = Field(default=10_000, ge=1_000, le=100_000)

    def __init__(self):
        self.valves = self.Valves()

    def execute_code(self, language: str, code: str) -> str:
        """Run code using language python, bash, or node and return bounded stdout, stderr, and exit code."""
        runtimes = {
            "python": (".py", ["python3"]),
            "bash": (".sh", ["bash"]),
            "node": (".js", ["node"]),
        }
        if language not in runtimes:
            return json.dumps({"status": "error", "error": "language must be python, bash, or node"})
        suffix, command = runtimes[language]
        path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="w", encoding="utf-8") as handle:
                handle.write(code)
                path = handle.name
            result = subprocess.run(
                [*command, path],
                capture_output=True,
                text=True,
                timeout=self.valves.timeout,
                shell=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            limit = self.valves.max_output_chars
            return json.dumps({"stdout": result.stdout[:limit], "stderr": result.stderr[:limit], "rc": result.returncode})
        except subprocess.TimeoutExpired:
            return json.dumps({"status": "error", "error": "Execution timed out"})
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)})
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
