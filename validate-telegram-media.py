#!/opt/hermes/.venv/bin/python
"""Validate Telegram media configuration, TTS output, and optional delivery."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import subprocess

import yaml


parser = argparse.ArgumentParser()
parser.add_argument(
    "--send-target",
    help=(
        "Optional Telegram delivery target. Use 'telegram', "
        "'telegram:chat_id', or a numeric chat ID."
    ),
)
args = parser.parse_args()

config_path = Path("/opt/data/config.yaml")
config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
telegram_display = (
    config.get("display", {}).get("platforms", {}).get("telegram", {})
)
tts = config.get("tts", {})
stt = config.get("stt", {})
system_prompt = str(config.get("agent", {}).get("system_prompt") or "")

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
    "delivery_truth_policy": (
        "Never promise a later upload" in system_prompt
        and "invent a helper bot" in system_prompt
    ),
}

source_markers = {
    "/opt/hermes/tools/tts_tool.py": (
        "HERMES_EDGE_TTS_OUTPUT_PATH_FIX",
        "HERMES_TTS_GATEWAY_AUTODELIVERY_SCHEMA",
    ),
    "/opt/hermes/gateway/run.py": (
        "HERMES_AUTODELIVER_TTS_MEDIA",
        "HERMES_LIVE_MODEL_STATUS",
        "HERMES_TELEGRAM_VOICE_TRUTH",
    ),
    "/opt/hermes/gateway/platforms/base.py": (
        "HERMES_CONFIRMED_TELEGRAM_VOICE_DELIVERY",
    ),
    "/opt/hermes/plugins/platforms/telegram/adapter.py": (
        "HERMES_TELEGRAM_VOICE_FAILURE_IS_FAILURE",
    ),
    "/opt/hermes/tools/send_message_tool.py": (
        "HERMES_TELEGRAM_VOICE_RETRY",
    ),
}
for source_path, markers in source_markers.items():
    source = Path(source_path).read_text(encoding="utf-8")
    for marker in markers:
        checks[f"patch_{marker.lower()}"] = marker in source


async def validate_gateway_voice_delivery() -> dict[str, bool]:
    from gateway.config import Platform, PlatformConfig
    from gateway.platforms.base import (
        BasePlatformAdapter,
        MessageEvent,
        MessageType,
        SendResult,
    )
    from gateway.session import SessionSource

    test_path = Path("/opt/data/tmp/gateway_delivery_logic_test.ogg")
    test_path.write_bytes(b"OggS-hermes-delivery-test")
    false_claim = "MODEL_FALSE_DELIVERY_CLAIM"
    response = (
        f"{false_claim}\n"
        "[[audio_as_voice]]\n"
        f"MEDIA:{test_path}"
    )

    class FakeTelegramAdapter(BasePlatformAdapter):
        def __init__(self, voice_ok: bool):
            super().__init__(
                PlatformConfig(enabled=True),
                Platform.TELEGRAM,
            )
            self.voice_ok = voice_ok
            self.events: list[tuple[str, str]] = []

        async def connect(self):
            return True

        async def disconnect(self):
            return None

        async def get_chat_info(self, chat_id):
            return {"id": chat_id}

        async def send(
            self,
            chat_id,
            content,
            reply_to=None,
            metadata=None,
        ):
            self.events.append(("text", content))
            return SendResult(success=True, message_id="text-1")

        async def send_voice(
            self,
            chat_id,
            audio_path,
            caption=None,
            reply_to=None,
            metadata=None,
            **kwargs,
        ):
            self.events.append(("voice", audio_path))
            return SendResult(
                success=self.voice_ok,
                message_id="voice-1" if self.voice_ok else None,
                error=None if self.voice_ok else "simulated delivery failure",
            )

        async def send_typing(self, *args, **kwargs):
            return None

        async def stop_typing(self, *args, **kwargs):
            return None

    async def run_case(voice_ok: bool) -> list[tuple[str, str]]:
        adapter = FakeTelegramAdapter(voice_ok)

        async def handler(event):
            return response

        adapter.set_message_handler(handler)
        event = MessageEvent(
            text="voice delivery validation",
            message_type=MessageType.TEXT,
            source=SessionSource(
                platform=Platform.TELEGRAM,
                chat_id="validation",
                user_id="owner",
            ),
            message_id="validation-1",
        )
        await adapter._process_message_background(
            event,
            "telegram:validation",
        )
        return adapter.events

    try:
        success_events = await run_case(True)
        failure_events = await run_case(False)
        return {
            "gateway_voice_success_is_voice_only": (
                len(success_events) == 1
                and success_events[0][0] == "voice"
            ),
            "gateway_voice_failure_reports_failure": (
                len(failure_events) == 2
                and failure_events[0][0] == "voice"
                and failure_events[1][0] == "text"
            ),
            "gateway_voice_false_claim_removed": (
                bool(failure_events)
                and false_claim not in failure_events[-1][1]
            ),
        }
    finally:
        test_path.unlink(missing_ok=True)


checks.update(asyncio.run(validate_gateway_voice_delivery()))

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

    delivery_target = args.send_target.strip()
    if re.fullmatch(r"-?\d+(?::\d+)?", delivery_target):
        delivery_target = f"telegram:{delivery_target}"
    delivery = json.loads(
        send_message_tool(
            {
                "action": "send",
                "target": delivery_target,
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
