#!/opt/hermes/.venv/bin/python
"""Run a live, semantic check of the configured Hermes vision route."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import yaml

from tools.vision_tools import vision_analyze_tool


parser = argparse.ArgumentParser()
parser.add_argument("image", type=Path)
parser.add_argument(
    "--expect",
    action="append",
    default=[],
    help="case-insensitive term that must appear in the analysis",
)
args = parser.parse_args()

if not args.image.is_file() or args.image.stat().st_size == 0:
    raise SystemExit(f"Image is missing or empty: {args.image}")

config = yaml.safe_load(
    Path("/opt/data/config.yaml").read_text(encoding="utf-8")
) or {}
vision = config.get("auxiliary", {}).get("vision", {})

prompt = (
    "Describe this image accurately. Transcribe all prominent Arabic and English "
    "text, then summarize its main idea. Never claim you cannot see the image."
)
payload = json.loads(
    asyncio.run(vision_analyze_tool(str(args.image), prompt))
)
analysis = str(payload.get("analysis") or "").strip()
lowered = analysis.lower()
refusal_markers = (
    "cannot view",
    "cannot see",
    "cannot analyze",
    "can't view",
    "can't see",
    "لا أستطيع رؤية",
    "لا يمكنني رؤية",
    "مش بيدعم تحليل الصور",
)
missing_terms = [term for term in args.expect if term.lower() not in lowered]
checks = {
    "provider_is_not_auto": vision.get("provider") not in {"", "auto", None},
    "success": payload.get("success") is True,
    "substantive_analysis": len(analysis) >= 100,
    "no_refusal": not any(marker in lowered for marker in refusal_markers),
    "expected_terms": not missing_terms,
}
report = {
    "passed": all(checks.values()),
    "checks": checks,
    "provider": vision.get("provider"),
    "model": vision.get("model"),
    "missing_terms": missing_terms,
    "analysis": analysis,
}
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(0 if report["passed"] else 1)
