#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${HERMES_PROJECT_DIR:-$HOME/hermes-ngrok}"
ENV_FILE="$PROJECT_DIR/.env"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
CREDS_FILE="$PROJECT_DIR/credentials.txt"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
info() { printf '[INFO] %s\n' "$*"; }
ok() { printf '[OK] %s\n' "$*"; }

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

wait_for_agent_idle() {
  local active_agents=0
  [[ "$(docker inspect -f '{{.State.Running}}' hermes-agent 2>/dev/null || true)" == "true" ]] \
    || return 0
  for _ in $(seq 1 120); do
    active_agents="$(docker exec hermes-agent jq -r \
      '.active_agents // 0' /opt/data/gateway_state.json 2>/dev/null || echo 0)"
    [[ "$active_agents" == "0" ]] && return 0
    sleep 5
  done
  die "Hermes is still handling a task; restart was cancelled to avoid interruption"
}

random_secret() {
  openssl rand -hex "${1:-24}"
}

env_value() {
  local key="$1"
  [[ -f "$ENV_FILE" ]] || return 0
  sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1
}

current_url() {
  curl -fsS http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c \
    "import json,sys; d=json.load(sys.stdin); print(next((x['public_url'] for x in d.get('tunnels',[]) if x.get('proto')=='https'), ''))" \
    2>/dev/null || true
}

status() {
  [[ -f "$COMPOSE_FILE" && -f "$ENV_FILE" ]] || die "No deployment found at $PROJECT_DIR"
  compose ps
  printf 'Public URL: %s\n' "$(current_url)"
}

restart() {
  [[ -f "$COMPOSE_FILE" && -f "$ENV_FILE" ]] || die "No deployment found at $PROJECT_DIR"
  wait_for_agent_idle
  compose up -d --build --force-recreate
  status
}

uninstall() {
  [[ -f "$COMPOSE_FILE" && -f "$ENV_FILE" ]] || die "No deployment found at $PROJECT_DIR"
  read -r -p "Remove deployment containers but preserve persistent data? [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || exit 0
  compose down
  ok "Containers removed. Persistent data and $PROJECT_DIR were preserved."
}

case "${1:-}" in
  --status) status; exit 0 ;;
  --url) current_url; exit 0 ;;
  --restart) restart; exit 0 ;;
  --uninstall) uninstall; exit 0 ;;
  --help|-h)
    printf 'Usage: %s [--status|--url|--restart|--uninstall]\n' "$0"
    exit 0
    ;;
  "") ;;
  *) die "Unknown option: $1" ;;
esac

command -v docker >/dev/null || die "Docker is required"
docker compose version >/dev/null || die "Docker Compose v2 is required"
command -v curl >/dev/null || die "curl is required"
command -v python3 >/dev/null || die "python3 is required"
command -v openssl >/dev/null || die "openssl is required"
docker info >/dev/null 2>&1 || die "Docker daemon is not available to this user"

mkdir -p "$PROJECT_DIR" "$HOME/.hermes" "$HOME/hermes_workspace" "$PROJECT_DIR/logs" "$HOME/hermes-backups"
mkdir -p "$PROJECT_DIR/scripts"
install -m 0644 "$SOURCE_DIR/docker-compose.yml" "$COMPOSE_FILE"
install -m 0644 "$SOURCE_DIR/Dockerfile.hermes-agent" "$PROJECT_DIR/Dockerfile.hermes-agent"
install -m 0644 "$SOURCE_DIR/patch-hermes-stt.py" "$PROJECT_DIR/patch-hermes-stt.py"
install -m 0644 "$SOURCE_DIR/patch-hermes-media-delivery.py" "$PROJECT_DIR/patch-hermes-media-delivery.py"
install -m 0755 "$SOURCE_DIR/ollama-openai-bridge.py" "$PROJECT_DIR/ollama-openai-bridge.py"
install -m 0755 "$SOURCE_DIR/hermes-admin.py" "$PROJECT_DIR/hermes-admin.py"
install -m 0755 "$SOURCE_DIR/configure-hermes-runtime.py" "$PROJECT_DIR/configure-hermes-runtime.py"
install -m 0755 "$SOURCE_DIR/configure-hermes-runtime.sh" "$PROJECT_DIR/configure-hermes-runtime.sh"
install -m 0755 "$SOURCE_DIR/hermes-smoke-test.sh" "$PROJECT_DIR/hermes-smoke-test.sh"
install -m 0755 "$SOURCE_DIR/validate-hermes-runtime.py" "$PROJECT_DIR/validate-hermes-runtime.py"
install -m 0755 "$SOURCE_DIR/validate-telegram.py" "$PROJECT_DIR/validate-telegram.py"
install -m 0755 "$SOURCE_DIR/validate-model-routes.py" "$PROJECT_DIR/validate-model-routes.py"
install -m 0755 "$SOURCE_DIR/validate-vision.py" "$PROJECT_DIR/validate-vision.py"
install -m 0755 "$SOURCE_DIR/validate-telegram-media.py" "$PROJECT_DIR/validate-telegram-media.py"
install -m 0755 "$SOURCE_DIR/validate-automatic-failover.sh" "$PROJECT_DIR/validate-automatic-failover.sh"
install -m 0755 "$SOURCE_DIR/validate-delegation-failover.sh" "$PROJECT_DIR/validate-delegation-failover.sh"
install -m 0755 "$SOURCE_DIR/scripts/monitor_gold.py" "$PROJECT_DIR/scripts/monitor_gold.py"
install -m 0644 "$SOURCE_DIR/Dockerfile.open-webui" "$PROJECT_DIR/Dockerfile.open-webui"

if [[ ! -f "$ENV_FILE" ]]; then
  read -r -s -p "ngrok auth token: " NGROK_AUTHTOKEN
  printf '\n'
  [[ -n "$NGROK_AUTHTOKEN" ]] || die "ngrok auth token is required"
  read -r -p "Open WebUI admin email [admin@hermes.local]: " OPEN_WEBUI_ADMIN_EMAIL
  OPEN_WEBUI_ADMIN_EMAIL="${OPEN_WEBUI_ADMIN_EMAIL:-admin@hermes.local}"
  OPEN_WEBUI_ADMIN_PASSWORD="$(random_secret 16)"
  API_SERVER_KEY="$(random_secret 24)"
  WEBUI_SECRET_KEY="$(random_secret 32)"
  umask 077
  cat > "$ENV_FILE" <<EOF
NGROK_AUTHTOKEN=$NGROK_AUTHTOKEN
API_SERVER_KEY=$API_SERVER_KEY
HERMES_API_PORT=8642
OPEN_WEBUI_PORT=3000
OPEN_WEBUI_NAME=Hermes Open WebUI
OPEN_WEBUI_ADMIN_EMAIL=$OPEN_WEBUI_ADMIN_EMAIL
OPEN_WEBUI_ADMIN_PASSWORD=$OPEN_WEBUI_ADMIN_PASSWORD
OPEN_WEBUI_SECRET_KEY=$WEBUI_SECRET_KEY
OPEN_WEBUI_PUBLIC_URL=
DOCKER_NETWORK=hermes_net
LOG_LEVEL=INFO
HERMES_DATA_DIR=$HOME/.hermes
HERMES_LOG_DIR=$PROJECT_DIR/logs
HERMES_WORKSPACE_DIR=$HOME/hermes_workspace
TELEGRAM_REQUIRE_MENTION=true
EOF
  chmod 600 "$ENV_FILE"
else
  info "Preserving existing $ENV_FILE"
fi

[[ -n "$(env_value NGROK_AUTHTOKEN)" ]] || die "NGROK_AUTHTOKEN is missing in $ENV_FILE"
[[ -n "$(env_value API_SERVER_KEY)" ]] || die "API_SERVER_KEY is missing in $ENV_FILE"
[[ -n "$(env_value OPEN_WEBUI_ADMIN_PASSWORD)" ]] || die "OPEN_WEBUI_ADMIN_PASSWORD is missing in $ENV_FILE"
[[ -n "$(env_value OPEN_WEBUI_SECRET_KEY)" ]] || die "OPEN_WEBUI_SECRET_KEY is missing in $ENV_FILE"

existing_agent=0
if [[ "$(docker inspect -f '{{.State.Running}}' hermes-agent 2>/dev/null || true)" == "true" ]]; then
  existing_agent=1
  info "Applying the durable runtime profile before the single service replacement"
  HERMES_PROJECT_DIR="$PROJECT_DIR" HERMES_RUNTIME_SKIP_RESTART=1 \
    bash "$PROJECT_DIR/configure-hermes-runtime.sh"
fi

info "Building and starting Hermes, the local GPU bridge, Open WebUI, and ngrok"
if [[ "$existing_agent" -eq 1 ]]; then
  wait_for_agent_idle
  compose up -d --build --force-recreate ollama-bridge hermes-agent
  compose up -d open-webui ngrok-hermes
else
  compose up -d --build
fi

for _ in $(seq 1 45); do
  if docker exec hermes-agent test -s /opt/data/config.yaml 2>/dev/null; then
    break
  fi
  sleep 2
done
docker exec hermes-agent test -s /opt/data/config.yaml \
  || die "Hermes did not create its persistent config"

if [[ "$existing_agent" -eq 0 ]]; then
  info "Applying the durable Hermes runtime profile"
  HERMES_PROJECT_DIR="$PROJECT_DIR" bash "$PROJECT_DIR/configure-hermes-runtime.sh"
fi

for _ in $(seq 1 60); do
  health="$(docker inspect hermes-open-webui --format '{{.State.Health.Status}}' 2>/dev/null || true)"
  [[ "$health" == "healthy" ]] && break
  sleep 2
done
[[ "${health:-}" == "healthy" ]] || die "Open WebUI did not become healthy; inspect docker logs hermes-open-webui"

url=""
for _ in $(seq 1 30); do
  url="$(current_url)"
  [[ -n "$url" ]] && break
  sleep 2
done
[[ -n "$url" ]] || die "ngrok did not publish an HTTPS endpoint"

umask 077
cat > "$CREDS_FILE" <<EOF
URL=$url
EMAIL=$(env_value OPEN_WEBUI_ADMIN_EMAIL)
PASSWORD=$(env_value OPEN_WEBUI_ADMIN_PASSWORD)
EOF
chmod 600 "$CREDS_FILE"

ok "Open WebUI is healthy"
printf 'URL: %s\n' "$url"
printf 'Credentials: %s\n' "$CREDS_FILE"
printf 'Next: configure valid provider keys, then deploy the tool/model/prompt catalogs.\n'
