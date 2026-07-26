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
    "description": "Generate speech audio for the current messaging reply. The gateway automatically attaches every successful current-turn TTS result as native media, including multiple comparison samples. After a successful call, return no final prose: do not announce creation or delivery, name a voice, show a path, provide Telegram instructions, or call send_message. Never promise a later upload or invent a helper bot. Voice and provider are centrally configured; do not pass provider_config or invent extra arguments.",
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
    "HERMES_SCAN_TRUSTED_MEDIA_WITH_PATH_DEDUP",
    '''    # Only trust the slice boundary when the message list still contains the
    # full history prefix. Otherwise scan everything (compression-safe fallback).
    if history_offset and len(messages) >= history_offset:
        new_messages = messages[history_offset:]
    else:
        new_messages = messages
''',
    '''    # HERMES_SCAN_TRUSTED_MEDIA_WITH_PATH_DEDUP: providers and resumed
    # sessions do not all return the same message shape. Some return full
    # history plus the current turn, while others return only current-turn
    # messages. A numeric history offset can therefore slice away the exact TTS
    # call/result pair we need. Scan every returned producer-tool message and
    # use history_media_paths as the authoritative stale-delivery guard.
    new_messages = messages
''',
)
patch_once(
    gateway_path,
    "HERMES_CANONICALIZE_TELEGRAM_TTS",
    '''    return media_tags, has_voice_directive


def _collect_history_media_paths(agent_history: List[Dict[str, Any]]) -> set:
''',
    '''    return media_tags, has_voice_directive


def _canonicalize_telegram_tts_response(
    platform: Any,
    final_response: str,
    media_tags: List[str],
    has_voice_directive: bool,
) -> str:
    """Return trusted TTS directives only for an explicit Telegram voice turn."""
    # HERMES_CANONICALIZE_TELEGRAM_TTS: a model-authored MEDIA path or
    # delivery claim is never evidence that Telegram received the artifact.
    if (
        getattr(platform, "value", platform) != "telegram"
        or not has_voice_directive
    ):
        return final_response
    trusted_voice_tags = [
        tag
        for tag in media_tags
        if Path(tag.removeprefix("MEDIA:")).suffix.lower()
        in {".ogg", ".opus", ".mp3", ".wav", ".m4a", ".flac"}
    ]
    if not trusted_voice_tags:
        return final_response
    return "[[audio_as_voice]]\\n" + "\\n".join(trusted_voice_tags)


def _collect_history_media_paths(agent_history: List[Dict[str, Any]]) -> set:
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
patch_once(
    gateway_path,
    "HERMES_TRUST_TOOL_TTS_OVER_MODEL_MEDIA",
    r'''            if "MEDIA:" not in final_response:
                media_tags, has_voice_directive = _collect_auto_append_media_tags(
                    result.get("messages", []),
                    history_offset=len(agent_history),
                    history_media_paths=_history_media_paths,
                )

                if media_tags:
                    seen = set()
                    unique_tags = []
                    for tag in media_tags:
                        if tag not in seen:
                            seen.add(tag)
                            unique_tags.append(tag)
                    if has_voice_directive:
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
    r'''            # HERMES_TRUST_TOOL_TTS_OVER_MODEL_MEDIA: always inspect the
            # current turn's producer-tool results, even when the model copied a
            # MEDIA path into its prose. Tool output is the delivery source of
            # truth; model-authored paths and delivery claims are untrusted.
            media_tags, has_voice_directive = _collect_auto_append_media_tags(
                result.get("messages", []),
                history_offset=len(agent_history),
                history_media_paths=_history_media_paths,
            )

            seen = set()
            unique_tags = []
            for tag in media_tags:
                if tag not in seen:
                    seen.add(tag)
                    unique_tags.append(tag)

            if unique_tags:
                missing_tags = [
                    tag for tag in unique_tags if tag not in final_response
                ]
                if missing_tags:
                    prefix = ""
                    if (
                        has_voice_directive
                        and "[[audio_as_voice]]" not in final_response
                    ):
                        prefix = "[[audio_as_voice]]\n"
                    final_response = (
                        final_response
                        + "\n"
                        + prefix
                        + "\n".join(missing_tags)
                    )

            # A successful TTS tool result means an audio artifact exists, not
            # that Telegram has received it. Canonicalize Telegram TTS turns to
            # trusted audio directives only. The platform layer then sends the
            # voice first and emits text solely when delivery is not confirmed.
            final_response = _canonicalize_telegram_tts_response(
                source.platform,
                final_response,
                unique_tags,
                has_voice_directive,
            )
''',
)

patch_once(
    gateway_path,
    "HERMES_IMPORT_EXPLICIT_VOICE_INTENT",
    '''    MessageEvent,
    MessageType,
    _prefix_within_utf16_limit,
''',
    '''    MessageEvent,
    MessageType,
    # HERMES_IMPORT_EXPLICIT_VOICE_INTENT
    _explicit_voice_reply_requested,
    _prefix_within_utf16_limit,
''',
)

patch_once(
    gateway_path,
    "HERMES_TAG_EXPLICIT_VOICE_REPLY",
    '''        if "@" in message_text:
''',
    '''        # HERMES_TAG_EXPLICIT_VOICE_REPLY: keep the LLM focused on the
        # substantive answer while the gateway owns TTS and Telegram delivery.
        # This covers typed requests and imperfect STT transcripts.
        if _explicit_voice_reply_requested(message_text, source.platform):
            setattr(event, "_gateway_explicit_voice_reply", True)
            _voice_delivery_note = (
                "[Trusted gateway delivery note: The user explicitly requested "
                "a Telegram voice reply. Answer the substantive request normally "
                "in the user's language. Do not discuss voice capability or "
                "refuse. The gateway will synthesize and deliver the final answer "
                "as a Telegram voice note if no TTS artifact is produced. Only "
                "call text_to_speech when the user requested multiple distinct "
                "voice samples; never call send_message for the voice reply.]"
            )
            message_text = f"{_voice_delivery_note}\\n\\n{message_text}"

        if "@" in message_text:
''',
)

base_adapter_path = Path("/opt/hermes/gateway/platforms/base.py")
patch_once(
    base_adapter_path,
    "HERMES_EXPLICIT_TELEGRAM_VOICE_INTENT",
    r'''def _mark_notify_metadata(metadata: dict | None) -> dict:
    """Clone metadata and mark a user-visible reply as notify-worthy."""
    notify_metadata = dict(metadata) if metadata else {}
    notify_metadata["notify"] = True
    return notify_metadata


def _reply_anchor_for_event(event) -> str | None:
''',
    r'''def _mark_notify_metadata(metadata: dict | None) -> dict:
    """Clone metadata and mark a user-visible reply as notify-worthy."""
    notify_metadata = dict(metadata) if metadata else {}
    notify_metadata["notify"] = True
    return notify_metadata


def _explicit_voice_reply_requested(text: str, platform: object) -> bool:
    """Recognize an explicit Telegram voice-reply request without an LLM."""
    # HERMES_EXPLICIT_TELEGRAM_VOICE_INTENT: speech recognition can preserve
    # "reply to me by voice" while missing surrounding words. Keep this
    # decision deterministic so TTS does not depend on the selected model's
    # tool use. Negation wins to avoid surprising audio replies.
    if _platform_name(platform) != "telegram":
        return False

    normalized = str(text or "").lower().translate(
        str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي"})
    )
    normalized = re.sub(r"[\u064b-\u065f\u0670]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return False

    negative_patterns = (
        r"(?:مش|لا|بدون|من غير|ما\s*تردش|ماتردش).{0,45}(?:صوت|فويس)",
        r"\b(?:do not|don't|dont|without|no)\b.{0,45}\b(?:voice|audio)\b",
    )
    if any(re.search(pattern, normalized) for pattern in negative_patterns):
        return False

    positive_patterns = (
        r"(?:ترد|رد|جاوب|تجاوب|كلمني|اتكلم|تكلم|قول|ابعت|ابعث|ارسل)"
        r".{0,35}(?:علي|عليا)?\s*(?:ب?صوت|فويس)",
        r"(?:بصوت|صوتي|فويس).{0,35}"
        r"(?:ترد|رد|جاوب|تجاوب|كلمني|اتكلم|تكلم|قول|ابعت|ابعث|ارسل)",
        r"\b(?:reply|respond|answer|speak|send)\b.{0,45}"
        r"\b(?:voice|audio)\b",
        r"\b(?:voice|audio)\b.{0,45}"
        r"\b(?:reply|respond|answer|speak|send)\b",
    )
    return any(re.search(pattern, normalized) for pattern in positive_patterns)


def _reply_anchor_for_event(event) -> str | None:
''',
)

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

patch_once(
    base_adapter_path,
    "HERMES_DETERMINISTIC_EXPLICIT_VOICE_REPLY",
    '''                _tts_path = None
                if (self._should_auto_tts_for_chat(event.source.chat_id)
                        and event.message_type == MessageType.VOICE
                        and text_content
                        and not media_files):
''',
    '''                _tts_path = None
                # HERMES_DETERMINISTIC_EXPLICIT_VOICE_REPLY: an explicit
                # request is sufficient even when auto-TTS is globally off.
                # The trusted marker is set after STT on this MessageEvent.
                _explicit_voice_reply = bool(
                    getattr(event, "_gateway_explicit_voice_reply", False)
                )
                if (
                    (
                        _explicit_voice_reply
                        or (
                            self._should_auto_tts_for_chat(event.source.chat_id)
                            and event.message_type == MessageType.VOICE
                        )
                    )
                    and text_content
                    and not media_files
                ):
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
