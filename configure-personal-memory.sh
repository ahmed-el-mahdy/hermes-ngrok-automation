#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${HERMES_PROJECT_DIR:-$HOME/hermes-ngrok}"
IMPORT_DIR="${HERMES_PERSONAL_IMPORT_DIR:-$HOME/hermes-personal-import}"
DATA_DIR="${HERMES_DATA_DIR:-$HOME/.hermes}"
IMAGE="${HERMES_AGENT_IMAGE:-hermes-agent:local}"

cd "$PROJECT_DIR"

if [[ ! -d "$IMPORT_DIR/source_chats" || ! -d "$IMPORT_DIR/dossiers" ]]; then
  echo "ERROR: private personal import is incomplete: $IMPORT_DIR" >&2
  exit 1
fi

docker run --rm \
  --user 0:0 \
  --entrypoint sh \
  -v "$DATA_DIR:/opt/data" \
  -v "$IMPORT_DIR:/private-import:ro" \
  "$IMAGE" -lc '
    set -eu
    install -d -o 10000 -g 10000 -m 0700 /opt/data/personal_memory
    cp -a /private-import/. /opt/data/personal_memory/
    chown -R 10000:10000 /opt/data/personal_memory
    find /opt/data/personal_memory -type d -exec chmod 0700 {} +
    find /opt/data/personal_memory -type f -exec chmod 0600 {} +
  '

run_personal_tool() {
  docker run --rm \
    --user 10000:10000 \
    --entrypoint /usr/local/bin/hermes-personal-memory \
    -v "$DATA_DIR:/opt/data" \
    "$IMAGE" "$@"
}

docker run --rm \
  --user 10000:10000 \
  --entrypoint /usr/local/bin/hermes-personal-ocr \
  -v "$DATA_DIR:/opt/data" \
  "$IMAGE" --documents-only

run_personal_tool normalize
run_personal_tool build
run_personal_tool sync-core
run_personal_tool validate

echo "personal_memory=ready"
run_personal_tool stats
