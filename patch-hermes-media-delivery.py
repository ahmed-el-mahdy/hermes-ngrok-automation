from pathlib import Path
import re


def patch_once(path: Path, marker: str, needle: str, replacement: str) -> None:
    source = path.read_text(encoding="utf-8")
    if marker in source:
        return
    if source.count(needle) != 1:
        raise RuntimeError(
            f"{path} changed; refusing to apply unsafe media patch {marker}"
        )
    path.write_text(source.replace(needle, replacement), encoding="utf-8")


tts_path = Path("/opt/hermes/tools/tts_tool.py")
patch_once(
    tts_path,
    "HERMES_EDGE_TTS_OUTPUT_PATH_FIX",
    '''        file_path = Path(output_path).expanduser()
        if command_provider_config is not None:
''',
    '''        file_path = Path(output_path).expanduser()
        # HERMES_EDGE_TTS_OUTPUT_PATH_FIX: Edge always writes MP3 first.
        # Avoid creating MP3 bytes under an .ogg/.opus name, then let the
        # existing Telegram conversion produce a real Ogg/Opus file.
        if provider == "edge" and file_path.suffix.lower() in {".ogg", ".opus"}:
            file_path = file_path.with_suffix(".mp3")
        if command_provider_config is not None:
''',
)
patch_once(
    tts_path,
    "HERMES_TTS_GATEWAY_AUTODELIVERY_SCHEMA",
    '''    "description": "Convert text to speech audio. Returns a MEDIA: path that the platform delivers as native audio. Compatible providers render as a voice bubble on Telegram; otherwise audio is sent as a regular attachment. In CLI mode, saves to ~/voice-memos/. Voice and provider are user-configured (built-in providers like edge/openai or custom command providers under tts.providers.<name>), not model-selected.",
''',
    '''    # HERMES_TTS_GATEWAY_AUTODELIVERY_SCHEMA: the gateway collects every
    # successful current-turn TTS artifact and delivers it as native media.
    "description": "Generate speech audio for the current messaging reply. The gateway automatically attaches every successful current-turn TTS result as native media, including multiple comparison samples. Do not call send_message for the returned local path and do not expose it in prose. Say that audio is attached below, never that Telegram confirmed delivery. Voice and provider are centrally configured; do not pass provider_config or invent extra arguments.",
''',
)

gateway_path = Path("/opt/hermes/gateway/run.py")
patch_once(
    gateway_path,
    "HERMES_AUTODELIVER_TTS_MEDIA",
    '''_AUTO_APPEND_MEDIA_TOOL_NAMES = {
    "text_to_speech",
    "text_to_speech_tool",
    "image_generate",
}
''',
    '''# HERMES_AUTODELIVER_TTS_MEDIA: keep delivery deterministic even when a
# model omits MEDIA tags or forgets to call a second messaging tool. Current
# turn isolation and history-path dedup below prevent stale audio re-delivery.
_AUTO_APPEND_MEDIA_TOOL_NAMES = {
    "text_to_speech",
    "text_to_speech_tool",
    "image_generate",
}
''',
)

send_message_path = Path("/opt/hermes/tools/send_message_tool.py")
patch_once(
    send_message_path,
    "HERMES_TELEGRAM_VOICE_RETRY",
    '''
SEND_MESSAGE_SCHEMA = {
''',
    '''
# HERMES_TELEGRAM_VOICE_RETRY: retry short Telegram media flood waits while
# failing fast on long waits so the agent can report a real delivery failure
# instead of hanging until the gateway timeout.
async def _send_telegram_voice_with_retry(
    bot,
    voice_file,
    *,
    attempts: int = 3,
    max_retry_after: float = 30.0,
    **kwargs,
):
    for attempt in range(attempts):
        try:
            return await bot.send_voice(voice=voice_file, **kwargs)
        except Exception as exc:
            delay = _telegram_retry_delay(exc, attempt)
            if (
                delay is None
                or delay > max_retry_after
                or attempt >= attempts - 1
            ):
                raise
            logger.warning(
                "Transient Telegram voice failure (attempt %d/%d), "
                "retrying in %.1fs: %s",
                attempt + 1,
                attempts,
                delay,
                _sanitize_error_text(exc),
            )
            try:
                voice_file.seek(0)
            except Exception:
                pass
            await asyncio.sleep(delay)


SEND_MESSAGE_SCHEMA = {
''',
)

send_source = send_message_path.read_text(encoding="utf-8")
voice_pattern = re.compile(
    r"(?P<indent>[ \t]+)last_msg = await bot\.send_voice\(\n"
    r"[ \t]+chat_id=int_chat_id, voice=f, \*\*media_kwargs\n"
    r"[ \t]+\)"
)
if "last_msg = await _send_telegram_voice_with_retry(" not in send_source:
    def replace_voice_send(match: re.Match[str]) -> str:
        indent = match.group("indent")
        return (
            f"{indent}last_msg = await _send_telegram_voice_with_retry(\n"
            f"{indent}    bot,\n"
            f"{indent}    f,\n"
            f"{indent}    chat_id=int_chat_id,\n"
            f"{indent}    **media_kwargs,\n"
            f"{indent})"
        )

    send_source, replacement_count = voice_pattern.subn(
        replace_voice_send,
        send_source,
    )
    if replacement_count != 2:
        raise RuntimeError(
            "Telegram voice send implementation changed; refusing unsafe patch"
        )
    send_message_path.write_text(
        send_source,
        encoding="utf-8",
    )
