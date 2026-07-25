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
    "description": "Generate speech audio for the current messaging reply. The gateway automatically attaches every successful current-turn TTS result as native media, including multiple comparison samples. Do not call send_message for the returned local path and do not expose it in prose. You may say the generated audio is attached by the gateway, but never claim Telegram confirmed receipt. Never promise a later upload or invent a helper bot. Voice and provider are centrally configured; do not pass provider_config or invent extra arguments.",
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
patch_once(
    gateway_path,
    "HERMES_LIVE_MODEL_STATUS",
    '''        _quick_key = self._session_key_for_source(source)
        _update_prompts = getattr(self, "_update_prompt_pending", {})
''',
    '''        _quick_key = self._session_key_for_source(source)

        # HERMES_LIVE_MODEL_STATUS: answer simple route-status questions from
        # the current config instead of asking an LLM that may repeat stale
        # model names from the conversation transcript.
        _status_query = (event.text or "").strip()
        _status_lower = _status_query.lower()
        _is_model_status_query = (
            len(_status_query) <= 180
            and not _status_query.startswith("/")
            and (
                bool(re.search(
                    r"(?:بتستخدم|المستخدم|شغال|الحالي|ايه|إيه|ما هو|ما هي).*موديل"
                    r"|موديل.*(?:بتستخدم|المستخدم|شغال|الحالي|ايه|إيه)",
                    _status_query,
                ))
                or bool(re.search(
                    r"\\b(?:what|which)\\s+(?:ai\\s+)?model\\b.*"
                    r"\\b(?:using|use|active|current)\\b"
                    r"|\\b(?:active|current)\\s+(?:ai\\s+)?model\\b",
                    _status_lower,
                ))
            )
        )
        if _is_model_status_query:
            _live_config = _load_gateway_config()
            _primary = _live_config.get("model") or {}
            _routes = [
                (_primary.get("provider"), _primary.get("default")),
                *[
                    (item.get("provider"), item.get("model"))
                    for item in (_live_config.get("fallback_providers") or [])
                    if isinstance(item, dict)
                ],
            ]
            _routes = [
                f"{provider}/{model}"
                for provider, model in _routes
                if provider and model
            ]
            _arabic = bool(re.search(r"[\\u0600-\\u06ff]", _status_query))
            if _arabic:
                _lines = [
                    "ده ترتيب الموديلات الفعلي من الإعدادات الحالية:",
                    *[
                        f"{index}. {route}"
                        + (" (Primary)" if index == 1 else "")
                        for index, route in enumerate(_routes, 1)
                    ],
                    "",
                    "القائمة دي مقروءة دلوقتي من الإعدادات الحية، مش من ذاكرة الشات.",
                ]
            else:
                _lines = [
                    "Current configured model route:",
                    *[
                        f"{index}. {route}"
                        + (" (Primary)" if index == 1 else "")
                        for index, route in enumerate(_routes, 1)
                    ],
                    "",
                    "This list was read from the live configuration, not chat memory.",
                ]
            return "\\n".join(_lines)

        _update_prompts = getattr(self, "_update_prompt_pending", {})
''',
)
patch_once(
    gateway_path,
    "HERMES_TELEGRAM_VOICE_TRUTH",
    r'''                    if has_voice_directive:
                        unique_tags.insert(0, "[[audio_as_voice]]")
                    final_response = final_response + "\n" + "\n".join(unique_tags)
''',
    r'''                    if has_voice_directive:
                        unique_tags.insert(0, "[[audio_as_voice]]")
                    final_response = final_response + "\n" + "\n".join(unique_tags)

            # HERMES_TELEGRAM_VOICE_TRUTH: a generated TTS file is not proof
            # that Telegram received it. For Telegram voice turns, keep only
            # the delivery directives in the persisted/final response. The
            # platform delivery layer sends the voice first and emits a clear
            # failure message only when Telegram does not return success.
            if (
                source.platform == Platform.TELEGRAM
                and "[[audio_as_voice]]" in final_response
                and "MEDIA:" in final_response
            ):
                _voice_paths = [
                    match.group(1)
                    for match in _TOOL_MEDIA_RE.finditer(final_response)
                ]
                if _voice_paths:
                    final_response = (
                        "[[audio_as_voice]]\n"
                        + "\n".join(f"MEDIA:{path}" for path in _voice_paths)
                    )
''',
)

base_adapter_path = Path("/opt/hermes/gateway/platforms/base.py")
patch_once(
    base_adapter_path,
    "HERMES_CONFIRMED_TELEGRAM_VOICE_DELIVERY",
    '''                _final_thread_metadata = _mark_notify_metadata(_thread_metadata)

                # Auto-TTS: if voice message, generate audio FIRST (before sending text)
''',
    '''                _final_thread_metadata = _mark_notify_metadata(_thread_metadata)

                # HERMES_CONFIRMED_TELEGRAM_VOICE_DELIVERY: TTS generation
                # success is not delivery success. Send explicit Telegram
                # voice attachments before any text, record the platform ACK,
                # and replace model-authored delivery claims with a factual
                # failure notice only when Telegram rejects the attachment.
                if self.platform == Platform.TELEGRAM and media_files:
                    _remaining_media_files = []
                    _voice_delivery_total = 0
                    _voice_delivery_successes = 0
                    for media_path, is_voice in media_files:
                        ext = Path(media_path).suffix.lower()
                        if not should_send_media_as_audio(
                            self.platform, ext, is_voice=is_voice
                        ):
                            _remaining_media_files.append((media_path, is_voice))
                            continue

                        _voice_delivery_total += 1
                        try:
                            delivery_adapter = self._final_delivery_adapter(
                                event.source
                            )
                            media_result = await delivery_adapter.send_voice(
                                chat_id=event.source.chat_id,
                                audio_path=media_path,
                                reply_to=_reply_anchor_for_event(event),
                                metadata=_final_thread_metadata,
                            )
                            _record_delivery(media_result)
                            if getattr(media_result, "success", False) and getattr(
                                media_result, "message_id", None
                            ):
                                _voice_delivery_successes += 1
                            else:
                                logger.warning(
                                    "[%s] Telegram voice delivery was not "
                                    "confirmed: %s",
                                    self.name,
                                    getattr(media_result, "error", "no message ID"),
                                )
                        except Exception as media_err:
                            delivery_attempted = True
                            logger.warning(
                                "[%s] Telegram voice delivery failed: %s",
                                self.name,
                                media_err,
                                exc_info=True,
                            )

                    media_files = _remaining_media_files
                    if _voice_delivery_total:
                        if _voice_delivery_successes == _voice_delivery_total:
                            text_content = ""
                        elif _voice_delivery_successes:
                            text_content = (
                                "⚠️ وصل "
                                f"{_voice_delivery_successes} من "
                                f"{_voice_delivery_total} ملفات صوتية. "
                                "باقي الملفات فشل إرسالها، ومش هاعتبرها وصلت."
                            )
                        else:
                            text_content = (
                                "⚠️ اتعمل الملف الصوتي، لكن Telegram ما أكدش "
                                "إرساله. مش هاعتبره وصل؛ جرّب الطلب مرة تانية."
                            )

                # Auto-TTS: if voice message, generate audio FIRST (before sending text)
''',
)

telegram_adapter_path = Path(
    "/opt/hermes/plugins/platforms/telegram/adapter.py"
)
patch_once(
    telegram_adapter_path,
    "HERMES_TELEGRAM_VOICE_FAILURE_IS_FAILURE",
    '''        except Exception as e:
            logger.error(
                "[%s] Failed to send Telegram voice/audio, falling back to base adapter: %s",
                self.name,
                _redact_telegram_error_text(e),
                exc_info=True,
            )
            return await super().send_voice(chat_id, audio_path, caption, reply_to, metadata=metadata)
''',
    '''        except Exception as e:
            # HERMES_TELEGRAM_VOICE_FAILURE_IS_FAILURE: a fallback text notice
            # is not a successfully delivered voice message. Return a real
            # failure so the gateway can report the outcome truthfully.
            safe_error = _redact_telegram_error_text(e)
            logger.error(
                "[%s] Failed to send Telegram voice/audio: %s",
                self.name,
                safe_error,
                exc_info=True,
            )
            return SendResult(success=False, error=safe_error)
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
