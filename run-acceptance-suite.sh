#!/usr/bin/env bash
set -euo pipefail

: "${PORTAL_EMAIL:?PORTAL_EMAIL is required}"
: "${PORTAL_PASSWORD:?PORTAL_PASSWORD is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PORTAL_EMAIL="$PORTAL_EMAIL" PORTAL_PASSWORD="$PORTAL_PASSWORD" \
  python3 "$SCRIPT_DIR/run-acceptance-suite.py"
