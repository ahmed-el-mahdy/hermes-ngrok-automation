#!/opt/hermes/.venv/bin/python
"""Validate Telegram media configuration, TTS output, and optional delivery."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

import yaml


parser = argparse.ArgumentParser()
parser.add_argument(
    "--send-target",
    help="Optional Telegram target used for a real voice delivery check",
)
args = parser.parse_args()

config_path = Path("/opt/data/config.yaml")
config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
telegram_display = (
    config.get("display", {}).get("platforms", {}).get("telegram", {})
)
tts = config.get("tts", {})
stt = config.get("stt", {})

checks = {
    "tts_edge": tts.get("provider") == "edge",
    "tts_egyptian_female": (
        tts.get("edge", {}).get("voice") == "ar-EG-SalmaNeural"
    ),
    "stt_local": stt.get("provider") == "local",
    "stt_arabic": stt.get("local", {}).get("language") == "ar",
    "telegram_tool_progress_off": (
        telegram_display.get("tool_progress") == "off"
    ),
    "telegram_streaming_off": telegram_display.get("streaming") is False,
    "telegram_interim_off": (
        telegram_display.get("interim_assistant_messages") is False
    ),
    "telegram_busy_detail_off": (
        telegram_display.get("busy_ack_detail") is False
    ),
}

source_markers = {
    "/opt/hermes/tools/tts_tool.py": (
        "HERMES_EDGE_TTS_OUTPUT_PATH_FIX",
        "HERMES_TTS_GATEWAY_AUTODELIVERY_SCHEMA",
    ),
    "/opt/hermes/gateway/run.py": ("HERMES_AUTODELIVER_TTS_MEDIA",),
    "/opt/hermes/tools/send_message_tool.py": (
        "HERMES_TELEGRAM_VOICE_RETRY",
    ),
}
for source_path, markers in source_markers.items():
    source = Path(source_path).read_text(encoding="utf-8")
    for marker in markers:
        checks[f"patch_{marker.lower()}"] = marker in source

os.environ["HERMES_SESSION_PLATFORM"] = "telegram"
from tools.tts_tool import text_to_speech_tool

requested_path = Path("/opt/data/tmp/telegram_voice_validation.ogg")
for stale_path in (
    requested_path,
    requested_path.with_suffix(".mp3"),
):
    stale_path.unlink(missing_ok=True)

payload = json.loads(
    text_to_speech_tool(
        text="أهلاً يا أحمد، ده اختبار تأكيد للصوت المصري الجديد.",
        output_path=str(requested_path),
    )
)
actual_path = Path(str(payload.get("file_path") or ""))
checks["tts_generation"] = payload.get("success") is True
checks["tts_voice_compatible"] = payload.get("voice_compatible") is True
checks["tts_actual_ogg"] = actual_path.suffix.lower() == ".ogg"
checks["tts_nonempty"] = actual_path.is_file() and actual_path.stat().st_size > 0

file_description = ""
if checks["tts_nonempty"]:
    file_description = subprocess.run(
        ["file", "-b", str(actual_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
checks["tts_ogg_opus"] = (
    "Ogg data" in file_description and "Opus audio" in file_description
)

delivery = None
if args.send_target and checks["tts_ogg_opus"]:
    from tools.send_message_tool import send_message_tool

    delivery = json.loads(
        send_message_tool(
            {
                "action": "send",
                "target": args.send_target,
                "message": (
                    "[[audio_as_voice]]\n"
                    f"MEDIA:{actual_path}"
                ),
            }
        )
    )
    checks["telegram_delivery"] = (
        delivery.get("success") is True
        and bool(delivery.get("message_id"))
        and not delivery.get("warnings")
    )

report = {
    "passed": all(checks.values()),
    "passed_count": sum(checks.values()),
    "check_count": len(checks),
    "checks": checks,
    "failed_checks": [name for name, passed in checks.items() if not passed],
    "tts_provider": payload.get("provider"),
    "tts_file": str(actual_path),
    "tts_file_description": file_description,
    "delivery": delivery,
}
for generated_path in {
    requested_path,
    requested_path.with_suffix(".mp3"),
    actual_path,
}:
    generated_path.unlink(missing_ok=True)
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(0 if report["passed"] else 1)
