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
        and "return no final prose" in system_prompt
        and "deterministically synthesizes and sends" in system_prompt
        and "never claim that voice generation" in system_prompt
    ),
}

source_markers = {
    "/opt/hermes/tools/transcription_tools.py": (
        "HERMES_STT_INITIAL_PROMPT",
        "HERMES_STT_EGYPTIAN_COMMAND_CORRECTIONS",
        "HERMES_APPLY_STT_EGYPTIAN_COMMAND_CORRECTIONS",
    ),
    "/opt/hermes/tools/tts_tool.py": (
        "HERMES_EDGE_TTS_OUTPUT_PATH_FIX",
        "HERMES_TTS_GATEWAY_AUTODELIVERY_SCHEMA",
    ),
    "/opt/hermes/gateway/run.py": (
        "HERMES_AUTODELIVER_TTS_MEDIA",
        "HERMES_CANONICALIZE_TELEGRAM_TTS",
        "HERMES_LIVE_MODEL_STATUS",
        "HERMES_SCAN_TRUSTED_MEDIA_WITH_PATH_DEDUP",
        "HERMES_TRUST_TOOL_TTS_OVER_MODEL_MEDIA",
        "HERMES_IMPORT_EXPLICIT_VOICE_INTENT",
        "HERMES_TAG_EXPLICIT_VOICE_REPLY",
    ),
    "/opt/hermes/gateway/platforms/base.py": (
        "HERMES_CONFIRMED_TELEGRAM_VOICE_DELIVERY",
        "HERMES_EXPLICIT_TELEGRAM_VOICE_INTENT",
        "HERMES_DETERMINISTIC_EXPLICIT_VOICE_REPLY",
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


from gateway.config import Platform
from gateway.platforms.base import _explicit_voice_reply_requested
from tools.transcription_tools import _normalize_egyptian_voice_transcript

observed_transcript = (
    "صباح الفل يريد ترد علي بصوت وتعرفني متعبسك"
)
corrected_transcript = (
    "صباح الفل يا ريت ترد عليا بصوت وتعرفني إمكانياتك"
)
checks.update(
    {
        "stt_observed_egyptian_command_corrected": (
            _normalize_egyptian_voice_transcript(observed_transcript)
            == corrected_transcript
        ),
        "stt_unrelated_text_preserved": (
            _normalize_egyptian_voice_transcript(
                "عايز أعرف حالة السيرفر النهارده"
            )
            == "عايز أعرف حالة السيرفر النهارده"
        ),
        "explicit_voice_intent_from_observed_stt": (
            _explicit_voice_reply_requested(
                observed_transcript,
                Platform.TELEGRAM,
            )
            is True
        ),
        "explicit_voice_intent_from_typed_request": (
            _explicit_voice_reply_requested(
                "لو سمحت رد عليا بصوت",
                Platform.TELEGRAM,
            )
            is True
        ),
        "explicit_voice_intent_respects_negation": (
            _explicit_voice_reply_requested(
                "مش عايزك ترد عليا بصوت",
                Platform.TELEGRAM,
            )
            is False
        ),
        "explicit_voice_intent_telegram_only": (
            _explicit_voice_reply_requested(
                "reply to me by voice",
                Platform.DISCORD,
            )
            is False
        ),
    }
)


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
    explicit_path = Path(
        "/opt/data/tmp/gateway_explicit_voice_logic_test.ogg"
    )
    explicit_path.write_bytes(b"OggS-hermes-explicit-voice-test")
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

    async def run_explicit_case() -> list[tuple[str, str]]:
        import tools.tts_tool as tts_module

        adapter = FakeTelegramAdapter(True)

        async def handler(event):
            return "ده رد صوتي مؤكد."

        adapter.set_message_handler(handler)
        event = MessageEvent(
            text="لو سمحت رد عليا بصوت",
            message_type=MessageType.TEXT,
            source=SessionSource(
                platform=Platform.TELEGRAM,
                chat_id="validation",
                user_id="owner",
            ),
            message_id="validation-explicit-voice",
        )
        event._gateway_explicit_voice_reply = True

        original_check = tts_module.check_tts_requirements
        original_tts = tts_module.text_to_speech_tool
        try:
            tts_module.check_tts_requirements = lambda: True
            tts_module.text_to_speech_tool = lambda **kwargs: json.dumps(
                {
                    "success": True,
                    "file_path": str(explicit_path),
                    "voice_compatible": True,
                }
            )
            await adapter._process_message_background(
                event,
                "telegram:validation-explicit-voice",
            )
        finally:
            tts_module.check_tts_requirements = original_check
            tts_module.text_to_speech_tool = original_tts
        return adapter.events

    try:
        success_events = await run_case(True)
        failure_events = await run_case(False)
        explicit_events = await run_explicit_case()
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
            "gateway_explicit_voice_request_is_deterministic": (
                len(explicit_events) == 1
                and explicit_events[0][0] == "voice"
            ),
        }
    finally:
        test_path.unlink(missing_ok=True)
        explicit_path.unlink(missing_ok=True)


checks.update(asyncio.run(validate_gateway_voice_delivery()))


def validate_model_media_regression() -> dict[str, bool]:
    from gateway.config import Platform
    from gateway.run import (
        _canonicalize_telegram_tts_response,
        _collect_auto_append_media_tags,
    )

    call_id = "voice-regression-call"
    path = "/opt/data/audio_cache/voice_regression.ogg"
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "text_to_speech",
                        "arguments": '{"text":"test"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": call_id,
            "content": json.dumps(
                {
                    "success": True,
                    "file_path": path,
                    "media_tag": f"[[audio_as_voice]]\nMEDIA:{path}",
                    "provider": "edge",
                    "voice_compatible": True,
                }
            ),
        },
        {
            "role": "assistant",
            "content": (
                "تم إرسال الصوت بنجاح. الصوت هو ar-EG-AmanyNeural.\n"
                f"MEDIA:{path}"
            ),
        },
    ]
    # Reproduce the resumed-session shape that caused the regression: Hermes
    # passed a history offset equal to this current-turn-only result length.
    media_tags, has_voice = _collect_auto_append_media_tags(
        messages,
        history_offset=len(messages),
        history_media_paths=set(),
    )
    canonical = _canonicalize_telegram_tts_response(
        Platform.TELEGRAM,
        str(messages[-1]["content"]),
        media_tags,
        has_voice,
    )
    stale_tags, _ = _collect_auto_append_media_tags(
        messages,
        history_offset=len(messages),
        history_media_paths={path},
    )
    return {
        "model_media_regression_tool_path_detected": (
            media_tags == [f"MEDIA:{path}"]
        ),
        "model_media_regression_voice_directive_detected": has_voice is True,
        "model_media_regression_false_claim_removed": (
            canonical == f"[[audio_as_voice]]\nMEDIA:{path}"
        ),
        "model_media_regression_stale_path_not_redelivered": stale_tags == [],
    }


checks.update(validate_model_media_regression())

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
