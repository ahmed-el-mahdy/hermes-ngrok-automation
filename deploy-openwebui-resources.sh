#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${HERMES_PROJECT_DIR:-$HOME/hermes-ngrok}"
ENV_FILE="$PROJECT_DIR/.env"

env_value() {
  local key="$1"
  sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1
}

[[ -f "$ENV_FILE" ]] || {
  echo "ERROR: Missing $ENV_FILE" >&2
  exit 1
}

PORTAL_EMAIL="${PORTAL_EMAIL:-$(env_value OPEN_WEBUI_ADMIN_EMAIL)}"
PORTAL_PASSWORD="${PORTAL_PASSWORD:-$(env_value OPEN_WEBUI_ADMIN_PASSWORD)}"
: "${PORTAL_EMAIL:?Open WebUI admin email is required}"
: "${PORTAL_PASSWORD:?Open WebUI admin password is required}"

stamp="$(date +%Y%m%d_%H%M%S)"
backup_dir="${HERMES_BACKUP_DIR:-$HOME/hermes-backups}/${stamp}-openwebui-resources"
mkdir -p "$backup_dir"

docker exec -i hermes-open-webui python - <<'PY'
import sqlite3

src = sqlite3.connect("/app/backend/data/webui.db")
dst = sqlite3.connect("/tmp/webui-resources-backup.db")
src.backup(dst)
dst.close()
src.close()
PY
docker cp hermes-open-webui:/tmp/webui-resources-backup.db "$backup_dir/webui.db.bak"
docker exec hermes-open-webui rm -f /tmp/webui-resources-backup.db

PORTAL_EMAIL="$PORTAL_EMAIL" PORTAL_PASSWORD="$PORTAL_PASSWORD" \
  python3 "$SCRIPT_DIR/deploy-openwebui-resources.py"

echo "backup_dir=$backup_dir"
