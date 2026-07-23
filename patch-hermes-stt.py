from pathlib import Path


SOURCE_PATH = Path("/opt/hermes/tools/transcription_tools.py")
PATCH_MARKER = "HERMES_STT_INITIAL_PROMPT"

source = SOURCE_PATH.read_text(encoding="utf-8")
if PATCH_MARKER in source:
    raise SystemExit(0)

needle = '''        transcribe_kwargs = {"beam_size": 5}
        if _forced_lang:
'''
replacement = '''        _stt_initial_prompt = os.getenv(
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
'''

if source.count(needle) != 1:
    raise RuntimeError(
        "Hermes local STT implementation changed; refusing to apply an unsafe patch"
    )

SOURCE_PATH.write_text(source.replace(needle, replacement), encoding="utf-8")
