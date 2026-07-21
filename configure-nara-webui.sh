#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

stamp="$(date +%Y%m%d_%H%M%S)"
backup_dir="${HERMES_BACKUP_DIR:-$HOME/hermes-backups}/${stamp}-nara-webui"
mkdir -p "$backup_dir"

docker exec -i hermes-open-webui python - <<'PY'
import sqlite3
src = sqlite3.connect('/app/backend/data/webui.db')
dst = sqlite3.connect('/tmp/webui-nara-backup.db')
src.backup(dst)
dst.close()
src.close()
PY
docker cp hermes-open-webui:/tmp/webui-nara-backup.db "$backup_dir/webui.db.bak"
docker exec hermes-open-webui rm -f /tmp/webui-nara-backup.db

docker cp "$SCRIPT_DIR/configure-nara-webui.py" hermes-open-webui:/tmp/configure-nara-webui.py
docker exec hermes-open-webui python /tmp/configure-nara-webui.py
docker restart hermes-open-webui >/dev/null

for _ in $(seq 1 60); do
  status="$(docker inspect hermes-open-webui --format '{{.State.Health.Status}}' 2>/dev/null || true)"
  if [[ "$status" == "healthy" ]]; then
    echo 'webui=healthy'
    echo "backup_dir=$backup_dir"
    exit 0
  fi
  sleep 2
done

echo 'ERROR: Open WebUI failed health after NaraRouter configuration' >&2
exit 1
