#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
docker cp "$SCRIPT_DIR/validate-canonical-tools.py" hermes-open-webui:/tmp/validate-canonical-tools.py
docker exec hermes-open-webui python /tmp/validate-canonical-tools.py
