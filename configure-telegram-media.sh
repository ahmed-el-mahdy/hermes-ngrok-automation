#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${HERMES_PROJECT_DIR:-$HOME/hermes-ngrok}"
BACKUP_ROOT="${HERMES_BACKUP_DIR:-$HOME/hermes-backups}"
STT_MODEL="${STT_MODEL:-large-v3-turbo}"
STT_LANGUAGE="${STT_LANGUAGE:-ar}"
TTS_VOICE="${TTS_VOICE:-ar-EG-SalmaNeural}"

case "$STT_MODEL" in
  tiny|base|small|medium|large-v3|large-v3-turbo|turbo) ;;
  *) echo "ERROR: unsupported STT_MODEL=$STT_MODEL" >&2; exit 1 ;;
esac

cd "$PROJECT_DIR"
stamp="$(date +%Y%m%d_%H%M%S)"
backup_dir="${BACKUP_ROOT}/${stamp}-telegram-media"
mkdir -p "$backup_dir"
docker cp hermes-agent:/opt/data/config.yaml "$backup_dir/config.yaml.bak"

docker exec -u root \
  -e STT_MODEL="$STT_MODEL" \
  -e STT_LANGUAGE="$STT_LANGUAGE" \
  -e TTS_VOICE="$TTS_VOICE" \
  -i hermes-agent /opt/hermes/.venv/bin/python - <<'PY'
from pathlib import Path
import os
import re
import yaml

path = Path('/opt/data/config.yaml')
config = yaml.safe_load(path.read_text()) or {}

tts = config.setdefault('tts', {})
tts['provider'] = 'edge'
tts.setdefault('edge', {})['voice'] = os.environ['TTS_VOICE']

stt = config.setdefault('stt', {})
stt['enabled'] = True
stt['provider'] = 'local'
stt.setdefault('local', {})['model'] = os.environ['STT_MODEL']
stt['local']['language'] = os.environ['STT_LANGUAGE']

voice = config.setdefault('voice', {})
voice['auto_tts'] = False
voice['max_recording_seconds'] = 120

telegram_display = (
    config.setdefault('display', {})
    .setdefault('platforms', {})
    .setdefault('telegram', {})
)
telegram_display.update({
    'tool_progress': 'off',
    'streaming': False,
    'interim_assistant_messages': False,
    'busy_ack_detail': False,
    'cleanup_progress': True,
    'long_running_notifications': True,
})

has_openrouter = bool(os.environ.get('OPENROUTER_API_KEY', '').strip())
has_nararouter = bool(os.environ.get('NARAROUTER_API_KEY', '').strip())
has_gemini = any(
    os.environ.get(name, '').strip()
    for name in ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_GENAI_API_KEY')
)
vision = config.setdefault('auxiliary', {}).setdefault('vision', {})
vision.update({
    'timeout': 120,
    'temperature': 0.1,
    'download_timeout': 30,
    'base_url': '',
    'api_key': '',
    'fallback_chain': [],
})
if has_nararouter:
    vision['provider'] = 'nararouter'
    vision['model'] = 'mistral-medium-3-5'
    if has_gemini:
        vision['fallback_chain'] = [{
            'provider': 'gemini',
            'model': 'gemini-2.5-flash',
        }]
elif has_gemini:
    vision['provider'] = 'gemini'
    vision['model'] = 'gemini-2.5-flash'
elif has_openrouter:
    vision['provider'] = 'openrouter'
    vision['model'] = 'google/gemma-4-26b-a4b-it:free'
else:
    vision['provider'] = 'auto'
    vision['model'] = ''

marker = '[TELEGRAM_MEDIA_POLICY]'
policy = '''[TELEGRAM_MEDIA_POLICY]
Speak to this user in natural, clear Egyptian Arabic by default, using familiar Egyptian wording without exaggerating slang. Switch languages when the user asks. For Telegram media: analyze attached images directly and explain what is visible, while stating uncertainty when needed. An attached image path means the image is available: never claim that image analysis is unsupported when pre-analysis or vision_analyze returned visual content. If a vision result is a refusal such as "cannot view" or "cannot analyze", treat it as a failed vision route and retry through the configured vision fallback rather than repeating the refusal. If the image contains text or the user's correction depends on visual details, call vision_analyze on the supplied image path instead of relying only on a generic pre-analysis. Never infer that a Telegram display name such as PersonalAgent identifies a different bot. Incoming voice messages are transcribed automatically; answer their meaning rather than discussing the audio file path. When the user explicitly requests a Telegram voice reply, answer the substantive request normally and never claim that voice generation or delivery is unavailable. The gateway deterministically synthesizes and sends the final answer as a voice note when no TTS artifact was produced. Only call text_to_speech when the user explicitly requests multiple distinct voice samples; use only its documented arguments. The gateway automatically attaches every successful TTS result from the current turn, including multiple voice samples. After a successful TTS call, return no final prose: do not announce creation or delivery, name a voice, show a file path, provide Telegram troubleshooting steps, or call send_message. Never promise a later upload, invent a helper bot, or tell the user to wait for an upload that was not actually scheduled. The provider and default voice are centrally configured, so never invent unsupported arguments. Do not generate voice for ordinary text replies unless explicitly requested.'''
agent = config.setdefault('agent', {})
existing = str(agent.get('system_prompt') or '').strip()
if marker in existing:
    start = existing.index(marker)
    following = re.search(
        r'\n\n\[[A-Z0-9_]+_POLICY\]',
        existing[start + len(marker):],
    )
    end = (
        start + len(marker) + following.start()
        if following
        else len(existing)
    )
    existing = '\n\n'.join(
        part
        for part in (existing[:start].strip(), existing[end:].strip())
        if part
    )
agent['system_prompt'] = (existing + '\n\n' + policy).strip()

path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
PY

docker exec -u root hermes-agent sh -lc \
  'chown 10000:10000 /opt/data/config.yaml && chmod 600 /opt/data/config.yaml'

for _ in $(seq 1 120); do
  active_agents="$(docker exec hermes-agent jq -r \
    '.active_agents // 0' /opt/data/gateway_state.json 2>/dev/null || echo 0)"
  [[ "$active_agents" == "0" ]] && break
  sleep 5
done
if [[ "${active_agents:-0}" != "0" ]]; then
  echo 'ERROR: Hermes is busy; configuration was saved but restart was deferred' >&2
  exit 2
fi

docker compose --env-file .env -f docker-compose.yml up -d --build --force-recreate hermes-agent

docker exec \
  -e STT_MODEL="$STT_MODEL" \
  -i hermes-agent /opt/hermes/.venv/bin/python - <<'PY'
import os
from faster_whisper import WhisperModel

model_name = os.environ['STT_MODEL']
WhisperModel(model_name, device='cpu', compute_type='int8')
print(f'stt_model_cached={model_name}')
PY

for _ in $(seq 1 60); do
  if docker exec hermes-agent /opt/hermes/.venv/bin/python -c \
    'import faster_whisper, edge_tts; from gateway.platforms.base import _explicit_voice_reply_requested' >/dev/null 2>&1 \
    && docker exec hermes-agent grep -q 'HERMES_STT_INITIAL_PROMPT' \
      /opt/hermes/tools/transcription_tools.py \
    && docker exec hermes-agent grep -q 'HERMES_AUTODELIVER_TTS_MEDIA' \
      /opt/hermes/gateway/run.py \
    && docker logs --since 2m hermes-agent 2>&1 | grep -q 'Hermes Gateway Starting'; then
    echo 'telegram_media=ready'
    echo "stt=local/$STT_MODEL"
    echo "stt_language=${STT_LANGUAGE:-auto}"
    echo "tts=edge/$TTS_VOICE"
    docker exec -u 10000 hermes-agent hermes config get auxiliary.vision
    docker exec -u 10000 hermes-agent validate-telegram-media
    echo 'auto_tts=false'
    echo "backup_dir=$backup_dir"
    exit 0
  fi
  sleep 2
done

echo 'ERROR: Hermes media runtime failed to become ready' >&2
exit 1
