#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${HERMES_PROJECT_DIR:-$HOME/hermes-ngrok}"
BACKUP_ROOT="${HERMES_BACKUP_DIR:-$HOME/hermes-backups}"
STT_MODEL="${STT_MODEL:-small}"
STT_LANGUAGE="${STT_LANGUAGE:-ar}"
TTS_VOICE="${TTS_VOICE:-ar-EG-ShakirNeural}"

case "$STT_MODEL" in
  tiny|base|small|medium|large-v3) ;;
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

marker = '[TELEGRAM_MEDIA_POLICY]'
policy = '''[TELEGRAM_MEDIA_POLICY]
For Telegram media: analyze attached images directly and explain what is visible, while stating uncertainty when needed. Incoming voice messages are transcribed automatically; answer their meaning rather than discussing the audio file path. When the user explicitly asks for a voice or audio reply in Arabic or English, call the text_to_speech tool so Telegram receives a playable voice message. Do not generate voice for ordinary text replies unless explicitly requested.'''
agent = config.setdefault('agent', {})
existing = str(agent.get('system_prompt') or '').strip()
if marker in existing:
    existing = existing.split(marker, 1)[0].rstrip()
agent['system_prompt'] = (existing + '\n\n' + policy).strip()

path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
PY

docker exec -u root hermes-agent sh -lc \
  'chown 10000:10000 /opt/data/config.yaml && chmod 600 /opt/data/config.yaml'
docker compose --env-file .env -f docker-compose.yml up -d --build --force-recreate hermes-agent

for _ in $(seq 1 60); do
  if docker exec hermes-agent /opt/hermes/.venv/bin/python -c \
    'import faster_whisper, edge_tts' >/dev/null 2>&1 \
    && docker logs --since 2m hermes-agent 2>&1 | grep -q 'Hermes Gateway Starting'; then
    echo 'telegram_media=ready'
    echo "stt=local/$STT_MODEL"
    echo "stt_language=${STT_LANGUAGE:-auto}"
    echo "tts=edge/$TTS_VOICE"
    echo 'auto_tts=false'
    echo "backup_dir=$backup_dir"
    exit 0
  fi
  sleep 2
done

echo 'ERROR: Hermes media runtime failed to become ready' >&2
exit 1
