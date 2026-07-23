#!/usr/bin/env bash
set -euo pipefail

: "${PORTAL_EMAIL:?PORTAL_EMAIL is required}"
: "${PORTAL_PASSWORD:?PORTAL_PASSWORD is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${HERMES_PROJECT_DIR:-$HOME/hermes-ngrok}"
docker compose config --quiet
docker compose up -d --build --force-recreate

for _ in $(seq 1 90); do
  webui_health="$(docker inspect hermes-open-webui --format '{{.State.Health.Status}}' 2>/dev/null || true)"
  agent_state="$(docker inspect hermes-agent --format '{{.State.Status}}' 2>/dev/null || true)"
  ngrok_state="$(docker inspect hermes-ngrok --format '{{.State.Status}}' 2>/dev/null || true)"
  if [[ "$webui_health" == "healthy" && "$agent_state" == "running" && "$ngrok_state" == "running" ]]; then
    break
  fi
  sleep 2
done

[[ "$webui_health" == "healthy" ]] || { docker compose ps; exit 1; }
[[ "$agent_state" == "running" && "$ngrok_state" == "running" ]] || { docker compose ps; exit 1; }

docker exec hermes-agent /opt/hermes/.venv/bin/python -c \
  'import bs4, docx, edge_tts, faster_whisper, fitz, lxml, openpyxl, pdfplumber, pypdf' \
  >/dev/null
docker exec hermes-agent grep -q 'HERMES_STT_INITIAL_PROMPT' \
  /opt/hermes/tools/transcription_tools.py
docker exec hermes-agent sh -lc \
  'command -v hermes hermes-admin jq pdftotext pdfinfo tesseract file >/dev/null'
docker exec -u 10000 hermes-agent sh -lc \
  '. /opt/data/home/.hermes_env
   command -v hermes hermes-admin pip uv >/dev/null
   python -c "import bs4, docx, fitz, lxml, openpyxl, pdfplumber, pypdf"'
docker exec hermes-agent /opt/hermes/.venv/bin/python - <<'PY'
from pathlib import Path
import yaml

config = yaml.safe_load(Path("/opt/data/config.yaml").read_text()) or {}
assert config["approvals"]["mode"] == "smart"
assert config["approvals"]["cron_mode"] == "approve"
assert config["tool_loop_guardrails"]["hard_stop_enabled"] is True
assert config["terminal"]["shell_init_files"] == ["/opt/data/home/.hermes_env"]
assert config["cron"]["max_parallel_jobs"] == 1
assert config.get("fallback_providers")
assert "[HERMES_RUNTIME_POLICY]" in config["agent"]["system_prompt"]
for path in (Path("/opt/data/cache/uv"), Path("/opt/data/cache/huggingface")):
    assert path.stat().st_uid == 10000, f"wrong owner: {path}"
PY
docker exec hermes-agent hermes-admin status
docker exec -u 10000 hermes-agent sh -lc \
  '. /opt/data/home/.hermes_env && timeout 30s validate-hermes-runtime --network'
docker exec hermes-agent timeout 15s validate-telegram
docker exec -u 10000 hermes-agent timeout 25s \
  /opt/hermes/.venv/bin/python /opt/data/home/.hermes/scripts/monitor_gold.py \
  --state /tmp/hermes-gold-validation.json --always-report
docker exec hermes-agent rm -f \
  /tmp/hermes-gold-validation.json /tmp/hermes-gold-validation.json.lock

public_url=""
for _ in $(seq 1 45); do
  public_url="$(curl -fsS http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(next((x['public_url'] for x in d.get('tunnels',[]) if x.get('proto')=='https'), ''))" 2>/dev/null || true)"
  [[ -n "$public_url" ]] && break
  sleep 2
done
[[ -n "$public_url" ]] || exit 1

PORTAL_EMAIL="$PORTAL_EMAIL" PORTAL_PASSWORD="$PORTAL_PASSWORD" PUBLIC_URL="$public_url" \
  EXPECTED_OPEN_WEBUI_VERSION="${EXPECTED_OPEN_WEBUI_VERSION:-}" \
  python3 "$SCRIPT_DIR/validate-deployment.py"

docker compose ps
df -h /
echo "public_url=$public_url"
