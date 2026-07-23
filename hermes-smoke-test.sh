#!/bin/sh
set -eu

export PATH="/opt/data/.local/bin:/opt/data/bin:/usr/local/bin:/opt/hermes/bin:/opt/hermes/.venv/bin:/usr/bin:/bin"
export PIP_TARGET="/opt/data/python-packages"
export PYTHONPATH="/opt/data/python-packages${PYTHONPATH:+:$PYTHONPATH}"
export UV_CACHE_DIR="/opt/data/cache/uv"
export XDG_CACHE_HOME="/opt/data/cache"
export HF_HOME="/opt/data/cache/huggingface"
export TMPDIR="/opt/data/tmp"
export PYTEST_ADDOPTS="-o cache_dir=/opt/data/cache/pytest"

printf '%s\n' "Running bounded Hermes capability checks..."
timeout 35s validate-hermes-runtime --network
timeout 15s validate-telegram
printf '%s\n' "hermes_smoke_test=passed"
