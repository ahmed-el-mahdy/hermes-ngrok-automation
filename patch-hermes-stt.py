from pathlib import Path


def patch_once(path: Path, marker: str, needle: str, replacement: str) -> None:
    source = path.read_text(encoding="utf-8")
    if marker in source:
        return
    if source.count(needle) != 1:
        raise RuntimeError(
            f"{path} changed; refusing to apply unsafe STT patch {marker}"
        )
    path.write_text(source.replace(needle, replacement), encoding="utf-8")


source_path = Path("/opt/hermes/tools/transcription_tools.py")

patch_once(
    source_path,
    "HERMES_STT_INITIAL_PROMPT",
    '''        transcribe_kwargs = {"beam_size": 5}
        if _forced_lang:
''',
    '''        _stt_initial_prompt = os.getenv(
            "HERMES_STT_INITIAL_PROMPT",
            "تفريغ دقيق لرسالة صوتية باللهجة المصرية العامية، مع الحفاظ على الكلمات التقنية والأسماء.",
        ).strip()
        _stt_hotwords = os.getenv(
            "HERMES_STT_HOTWORDS",
            "هيرمس تليجرام واتساب API Ollama Gemini ngrok عقارات المقطم أكتوبر بدر",
        ).strip()
        transcribe_kwargs = {
            "beam_size": int(os.getenv("HERMES_STT_BEAM_SIZE", "8")),
            "patience": float(os.getenv("HERMES_STT_PATIENCE", "1.2")),
            "vad_filter": os.getenv("HERMES_STT_VAD_FILTER", "true").lower()
            in {"1", "true", "yes", "on"},
            "vad_parameters": {
                "min_silence_duration_ms": int(
                    os.getenv("HERMES_STT_MIN_SILENCE_MS", "300")
                )
            },
            "hallucination_silence_threshold": float(
                os.getenv("HERMES_STT_HALLUCINATION_SILENCE", "2.0")
            ),
        }
        if _stt_initial_prompt:
            transcribe_kwargs["initial_prompt"] = _stt_initial_prompt
        if _stt_hotwords:
            transcribe_kwargs["hotwords"] = _stt_hotwords
        if _forced_lang:
''',
)

patch_once(
    source_path,
    "HERMES_STT_EGYPTIAN_COMMAND_CORRECTIONS",
    '''logger = logging.getLogger(__name__)
''',
    '''logger = logging.getLogger(__name__)


def _normalize_egyptian_voice_transcript(transcript: str) -> str:
    """Repair narrow, observed Whisper confusions in Egyptian voice commands."""
    # HERMES_STT_EGYPTIAN_COMMAND_CORRECTIONS: these substitutions are gated
    # by an explicit voice-reply phrase and only target impossible or strongly
    # implausible strings observed in real Telegram samples. Ordinary Arabic
    # transcription is returned byte-for-byte unchanged.
    text = str(transcript or "").strip()
    if "بصوت" not in text and "فويس" not in text:
        return text

    replacements = (
        ("يريد ترد علي بصوت", "يا ريت ترد عليا بصوت"),
        ("يريد ترد عليا بصوت", "يا ريت ترد عليا بصوت"),
        ("ترد علي بصوت", "ترد عليا بصوت"),
        ("وتعرفني متعبسك", "وتعرفني إمكانياتك"),
        ("وتعرفني بتعبسك", "وتعرفني إمكانياتك"),
        ("وتعرفني نمتعبسك", "وتعرفني إمكانياتك"),
        ("وتعرف نمتعب بسك", "وتعرفني إمكانياتك"),
    )
    for mistaken, corrected in replacements:
        text = text.replace(mistaken, corrected)
    return text
''',
)

patch_once(
    source_path,
    "HERMES_APPLY_STT_EGYPTIAN_COMMAND_CORRECTIONS",
    '''        logger.info(
            "Transcribed %s via local whisper (%s, lang=%s, %.1fs audio)",
''',
    '''        # HERMES_APPLY_STT_EGYPTIAN_COMMAND_CORRECTIONS
        transcript = _normalize_egyptian_voice_transcript(transcript)

        logger.info(
            "Transcribed %s via local whisper (%s, lang=%s, %.1fs audio)",
''',
)
