#!/usr/bin/env bash
set -euo pipefail

echo "apply-model-routing.sh is retained as a compatibility entrypoint." >&2
echo "Routing is managed by configure-hermes-runtime.sh." >&2
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/configure-hermes-runtime.sh"
