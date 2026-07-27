#!/usr/bin/env bash
set -euo pipefail

CONTAINER="${HERMES_AGENT_CONTAINER:-hermes-agent}"

declare -a SKILLS=(
  "official/communication/one-three-one-rule|one-three-one-rule"
  "official/finance/excel-author|excel-author"
  "official/productivity/memento-flashcards|memento-flashcards"
  "official/research/duckduckgo-search|duckduckgo-search"
  "official/software-development/code-wiki|code-wiki"
)

declare -a REJECTED_SKILLS=(
  "watchers"
  "fitness-nutrition"
  "rest-graphql-debug"
)

container_exec() {
  docker exec -i -u 10000:10000 "$CONTAINER" "$@"
}

container_uninstall() {
  printf 'y\n' \
    | docker exec -i -u 10000:10000 "$CONTAINER" \
        hermes skills uninstall "$1"
}

skill_is_installed() {
  local name="$1"
  container_exec sh -lc \
    "find /opt/data/skills -type f -path '*/${name}/SKILL.md' -print -quit | grep -q ."
}

for row in "${SKILLS[@]}"; do
  identifier="${row%%|*}"
  name="${row##*|}"
  if skill_is_installed "$name"; then
    printf '[OK] skill already installed: %s\n' "$name"
    continue
  fi
  printf '[INFO] installing reviewed official skill: %s\n' "$identifier"
  container_exec hermes skills install "$identifier" --yes
  skill_is_installed "$name" \
    || { printf 'ERROR: skill was not installed: %s\n' "$name" >&2; exit 1; }
done

for name in "${REJECTED_SKILLS[@]}"; do
  if skill_is_installed "$name"; then
    printf '[INFO] removing skill blocked by the deep security audit: %s\n' "$name"
    container_uninstall "$name"
  fi
done

container_exec /opt/hermes/.venv/bin/python - <<'PY'
from pathlib import Path
import os
import tempfile

import yaml


path = Path("/opt/data/config.yaml")
config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
skills = config.setdefault("skills", {})
disabled = set(skills.get("disabled") or [])
disabled.update(
    {
        "apple-productivity",
        "audiocraft-audio-generation",
        "fitness-nutrition",
        "godmode",
        "heartmula",
        "obliteratus",
        "openhue",
        "petdex",
        "polymarket",
        "spotify",
        "touchdesigner-mcp",
        "rest-graphql-debug",
        "watchers",
        "xurl",
        "yuanbao",
    }
)
skills["disabled"] = sorted(disabled)

stat = path.stat()
payload = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
with tempfile.NamedTemporaryFile(
    "w",
    encoding="utf-8",
    dir=path.parent,
    delete=False,
) as handle:
    handle.write(payload)
    temporary = Path(handle.name)
os.chmod(temporary, stat.st_mode & 0o777)
os.replace(temporary, path)
print(f"disabled_skill_count={len(skills['disabled'])}")
PY

for row in "${SKILLS[@]}"; do
  name="${row##*|}"
  skill_is_installed "$name" \
    || { printf 'ERROR: required skill is missing: %s\n' "$name" >&2; exit 1; }
done

container_exec hermes skills audit --deep
container_exec hermes prompt-size
printf 'curated_skills=ready\n'
