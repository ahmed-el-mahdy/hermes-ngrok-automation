#!/opt/hermes/.venv/bin/python
"""Secret-safe smoke test for the persistent Hermes runtime."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import yaml


parser = argparse.ArgumentParser()
parser.add_argument(
    "--network",
    action="store_true",
    help="also run a live key-free web search",
)
args = parser.parse_args()


COMMANDS = (
    "file",
    "hermes",
    "hermes-admin",
    "jq",
    "pdfinfo",
    "pdftotext",
    "pip",
    "tesseract",
    "uv",
)
MODULES = (
    "bs4",
    "docx",
    "ddgs",
    "fitz",
    "lxml",
    "openpyxl",
    "pdfplumber",
    "pypdf",
)


def run(*command: str, timeout: int = 20) -> str:
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout


checks: dict[str, bool] = {}
checks["non_root_user"] = os.getuid() == 10000
for command in COMMANDS:
    checks[f"command_{command}"] = shutil.which(command) is not None
for module in MODULES:
    importlib.import_module(module)
    checks[f"module_{module}"] = True

config = yaml.safe_load(Path("/opt/data/config.yaml").read_text(encoding="utf-8")) or {}
checks["smart_approvals"] = config.get("approvals", {}).get("mode") == "smart"
checks["cron_approvals"] = config.get("approvals", {}).get("cron_mode") == "approve"
checks["loop_hard_stop"] = (
    config.get("tool_loop_guardrails", {}).get("hard_stop_enabled") is True
)
checks["shell_profile"] = config.get("terminal", {}).get("shell_init_files") == [
    "/opt/data/home/.hermes_env"
]
checks["serialized_cron"] = config.get("cron", {}).get("max_parallel_jobs") == 1
checks["fallbacks"] = len(config.get("fallback_providers") or []) >= 1
checks["ddgs_search"] = config.get("web", {}).get("search_backend") == "ddgs"
checks["provider_timeout"] = (
    config.get("providers", {}).get("openrouter", {}).get(
        "request_timeout_seconds"
    )
    == 60
)
checks["gateway_timeout"] = config.get("agent", {}).get("gateway_timeout") == 300
checks["runtime_policy"] = "[HERMES_RUNTIME_POLICY]" in str(
    config.get("agent", {}).get("system_prompt") or ""
)

for raw_path in (
    "/opt/data/cache/uv",
    "/opt/data/cache/huggingface",
    "/opt/data/python-packages",
):
    path = Path(raw_path)
    checks[f"owner_{path.name}"] = path.stat().st_uid == 10000
    checks[f"writable_{path.name}"] = os.access(path, os.W_OK)

with tempfile.TemporaryDirectory(prefix="hermes-runtime-") as raw_temp:
    temp = Path(raw_temp)

    import fitz

    pdf_path = temp / "sample.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "HERMES PDF EXTRACTION OK")
    document.save(pdf_path)
    document.close()
    pdf_text = run("pdftotext", str(pdf_path), "-")
    checks["pdf_extract"] = "HERMES PDF EXTRACTION OK" in pdf_text

    from docx import Document

    docx_path = temp / "sample.docx"
    writer = Document()
    writer.add_paragraph("HERMES DOCX EXTRACTION OK")
    writer.save(docx_path)
    reader = Document(docx_path)
    checks["docx_extract"] = any(
        "HERMES DOCX EXTRACTION OK" in paragraph.text
        for paragraph in reader.paragraphs
    )

languages = run("tesseract", "--list-langs")
checks["ocr_arabic"] = "ara" in languages.split()
checks["hermes_admin"] = "primary=" in run("hermes-admin", "status")
checks["pip_wrapper"] = "pip " in run("pip", "--version").lower()
checks["gold_monitor_installed"] = Path(
    "/opt/data/home/.hermes/scripts/monitor_gold.py"
).is_file()

if args.network:
    from tools.web_tools import web_search_tool

    search = json.loads(web_search_tool("Open WebUI official documentation", 2))
    checks["web_search_live"] = bool(
        search.get("success") and search.get("data", {}).get("web")
    )

report = {
    "passed": all(checks.values()),
    "checks": checks,
    "primary": (
        f"{config.get('model', {}).get('provider', '')}/"
        f"{config.get('model', {}).get('default', '')}"
    ),
    "fallback_count": len(config.get("fallback_providers") or []),
}
print(json.dumps(report, indent=2, sort_keys=True))
raise SystemExit(0 if report["passed"] else 1)
