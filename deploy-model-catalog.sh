#!/usr/bin/env bash
set -euo pipefail

: "${PORTAL_EMAIL:?PORTAL_EMAIL is required}"
: "${PORTAL_PASSWORD:?PORTAL_PASSWORD is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

stamp="$(date +%Y%m%d_%H%M%S)"
backup_dir="${HERMES_BACKUP_DIR:-$HOME/hermes-backups}/${stamp}-model-catalog"
mkdir -p "$backup_dir"
docker exec -i hermes-open-webui python - <<'PY'
import sqlite3
src = sqlite3.connect('/app/backend/data/webui.db')
dst = sqlite3.connect('/tmp/webui-model-catalog-backup.db')
src.backup(dst)
dst.close()
src.close()
PY
docker cp hermes-open-webui:/tmp/webui-model-catalog-backup.db "$backup_dir/webui.db.bak"
docker exec hermes-open-webui rm -f /tmp/webui-model-catalog-backup.db

PORTAL_EMAIL="$PORTAL_EMAIL" PORTAL_PASSWORD="$PORTAL_PASSWORD" \
  python3 "$SCRIPT_DIR/deploy-model-catalog.py"
echo "backup_dir=$backup_dir"
