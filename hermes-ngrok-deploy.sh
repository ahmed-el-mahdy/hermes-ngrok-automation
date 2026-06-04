#!/usr/bin/env bash
# =============================================================================
#  hermes-ngrok-deploy.sh  —  v2  (confirmed config)
#  Hermes Agent (NousResearch) + ngrok on Ubuntu Minimal Server
#
#  Confirmed settings:
#    ✔  ngrok FREE plan  (random URL, watcher tracks changes automatically)
#    ✔  VM in NAT mode   (ngrok handles outbound tunnel — no port-forward needed)
#    ✔  ngrok Basic Auth (auto-generated password — protects the dashboard)
#    ✔  LLM: OpenRouter + Google Gemini API (configure later via web portal)
#    ✔  HERMES_DASHBOARD_INSECURE=1 (safe because ngrok basic-auth is the gate)
#
#  Security model:
#    Internet → ngrok basic-auth challenge → Hermes dashboard (port 9119)
#    The dashboard runs in insecure mode INTERNALLY but is protected
#    by ngrok's own authentication layer EXTERNALLY.
#
#  Pattern mirrors n8n-ngrok-automation project:
#    Two containers on shared bridge network  (hermes-net)
#    ngrok sidecar tunnels dashboard port to internet
#    URL watcher service tracks ngrok URL changes
#
#  Usage:
#    chmod +x hermes-ngrok-deploy.sh && ./hermes-ngrok-deploy.sh
#    ./hermes-ngrok-deploy.sh --status
#    ./hermes-ngrok-deploy.sh --url
#    ./hermes-ngrok-deploy.sh --uninstall
# =============================================================================

set -euo pipefail

# ─────────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────────
readonly PROJECT_DIR="$HOME/hermes-ngrok"
readonly HERMES_DATA_DIR="$HOME/.hermes"
readonly COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
readonly ENV_FILE="$PROJECT_DIR/.env"
readonly CREDS_FILE="$PROJECT_DIR/credentials.txt"
readonly SCRIPTS_DIR="$PROJECT_DIR/scripts"
readonly LOGS_DIR="$PROJECT_DIR/logs"
readonly URL_FILE="$PROJECT_DIR/current-url.txt"
readonly WATCHER_LOG="$LOGS_DIR/url-watcher.log"
readonly WATCHER_SERVICE="hermes-url-watcher"
readonly NGROK_API="http://localhost:4040/api/tunnels"

# Docker images
readonly HERMES_IMAGE="nousresearch/hermes-agent:latest"
readonly NGROK_IMAGE="ngrok/ngrok:latest"

# Ports
readonly HERMES_DASHBOARD_PORT="9119"
readonly HERMES_API_PORT="8642"
readonly NGROK_MGMT_PORT="4040"

# Auth
readonly NGROK_AUTH_USER="hermes"

# ─────────────────────────────────────────────────────────────────
#  COLORS
# ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

# ─────────────────────────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────────────────────────
log_info()  { echo -e "${BLUE}[INFO]${RESET}  $*"; }
log_ok()    { echo -e "${GREEN}[  OK ]${RESET} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
log_error() { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
log_step()  { echo -e "\n${BOLD}${CYAN}━━━  $*  ━━━${RESET}"; }
log_sep()   { echo -e "${DIM}──────────────────────────────────────────────────────${RESET}"; }

banner() {
  clear 2>/dev/null || true
  echo -e "${CYAN}${BOLD}"
  cat <<'BANNER'

   ██╗  ██╗███████╗██████╗ ███╗   ███╗███████╗███████╗
   ██║  ██║██╔════╝██╔══██╗████╗ ████║██╔════╝██╔════╝
   ███████║█████╗  ██████╔╝██╔████╔██║█████╗  ███████║
   ██╔══██║██╔══╝  ██╔══██╗██║╚██╔╝██║██╔══╝  ╚════██║
   ██║  ██║███████╗██║  ██║██║ ╚═╝ ██║███████╗███████║
   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝╚══════╝

BANNER
  echo -e "${RESET}"
  echo -e "  ${BOLD}Hermes Agent  +  ngrok  —  Ubuntu Minimal Server${RESET}"
  echo -e "  ${DIM}NousResearch Hermes Agent  |  Docker  |  ngrok Tunnel${RESET}"
  echo -e "  ${DIM}NAT VM  ·  Free ngrok plan  ·  Basic-Auth protected  ·  OpenRouter + Gemini${RESET}"
  echo ""
  log_sep
  echo ""
}

# ─────────────────────────────────────────────────────────────────
#  UTILITY
# ─────────────────────────────────────────────────────────────────
command_exists() { command -v "$1" &>/dev/null; }

sudo() {
  if command sudo -n true 2>/dev/null; then
    command sudo "$@"
    return
  fi

  if [[ -n "${SUDO_PASSWORD:-}" ]]; then
    printf '%s\n' "$SUDO_PASSWORD" | command sudo -S -v
    command sudo "$@"
    return
  fi

  command sudo "$@"
}

gen_password() {
  # 24-char hex — safe in all shell/YAML contexts, no special chars
  openssl rand -hex 12 2>/dev/null \
    || head -c 24 /dev/urandom | xxd -p 2>/dev/null \
    || cat /proc/sys/kernel/random/uuid 2>/dev/null | tr -d '-' | head -c 24 \
    || echo "changeme$(date +%s)"
}

get_ngrok_url() {
  curl -sf "$NGROK_API" 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['tunnels'][0]['public_url'])" \
    2>/dev/null || echo ""
}

wait_for_port() {
  local port=$1 label=$2 max=${3:-40} delay=${4:-3}
  log_info "Waiting for $label (port $port)..."
  for ((i=1; i<=max; i++)); do
    if nc -z 127.0.0.1 "$port" 2>/dev/null; then
      log_ok "$label is up"
      return 0
    fi
    printf "."
    sleep "$delay"
  done
  echo ""
  log_warn "$label did not respond after $((max * delay))s — check logs"
  return 1
}

require_sudo() {
  [[ $EUID -eq 0 ]] && return 0
  log_warn "Requesting sudo for this step..."
  sudo -v || { log_error "Cannot get sudo. Exiting."; exit 1; }
}

# ─────────────────────────────────────────────────────────────────
#  STEP 1 — PREREQUISITES
# ─────────────────────────────────────────────────────────────────
check_prerequisites() {
  log_step "Step 1/10 — Checking Prerequisites"

  [[ -f /etc/os-release ]] && { source /etc/os-release; log_info "OS: $PRETTY_NAME"; }

  INSTALL_DOCKER=false

  if command_exists docker; then
    log_ok "Docker $(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1)"
  else
    log_warn "Docker not found — will install"
    INSTALL_DOCKER=true
  fi

  if docker compose version &>/dev/null 2>&1; then
    log_ok "Docker Compose v2 found"
  else
    log_warn "Docker Compose v2 not found — will install with Docker"
    INSTALL_DOCKER=true
  fi

  for pkg in curl python3; do
    if command_exists "$pkg"; then
      log_ok "$pkg found"
    else
      log_info "Installing $pkg..."
      sudo apt-get install -y "$pkg" -qq
    fi
  done

  if command_exists nc; then
    log_ok "netcat found"
  else
    sudo apt-get install -y netcat-openbsd -qq
    log_ok "netcat installed"
  fi

  if command_exists openssl; then
    log_ok "openssl found"
  else
    sudo apt-get install -y openssl -qq
    log_ok "openssl installed"
  fi
}

# ─────────────────────────────────────────────────────────────────
#  STEP 2 — INSTALL DOCKER
# ─────────────────────────────────────────────────────────────────
install_docker() {
  [[ "$INSTALL_DOCKER" == "false" ]] && { log_step "Step 2/10 — Docker Already Installed (skip)"; return 0; }

  log_step "Step 2/10 — Installing Docker Engine"
  require_sudo

  log_info "Removing old Docker packages..."
  sudo apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

  sudo apt-get update -qq
  sudo apt-get install -y -qq \
    ca-certificates curl gnupg lsb-release

  log_info "Adding Docker GPG key and repository..."
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

  sudo apt-get update -qq
  sudo apt-get install -y \
    docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin

  sudo usermod -aG docker "$USER"
  sudo systemctl enable --now docker

  log_ok "Docker Engine installed and started"
  log_warn "If docker commands fail later, run: newgrp docker  (group membership refresh)"
}

# ─────────────────────────────────────────────────────────────────
#  STEP 3 — COLLECT CONFIG
# ─────────────────────────────────────────────────────────────────
collect_config() {
  log_step "Step 3/10 — Configuration"

  # ── ngrok auth token ──
  echo ""
  echo -e "  ${BOLD}ngrok Auth Token${RESET}"
  echo -e "  ${DIM}Get yours free → https://dashboard.ngrok.com/get-started/your-authtoken${RESET}"
  echo ""

  # Re-use existing token if available
  if [[ -f "$ENV_FILE" ]]; then
    _existing=$(grep '^NGROK_AUTHTOKEN=' "$ENV_FILE" 2>/dev/null | cut -d= -f2 || true)
    if [[ -n "${_existing:-}" && "$_existing" != "PASTE_YOUR_NGROK_TOKEN_HERE" ]]; then
      NGROK_AUTHTOKEN="$_existing"
      log_ok "Reusing existing ngrok token from .env"
    fi
  fi

  if [[ -z "${NGROK_AUTHTOKEN:-}" ]]; then
    read -rp "  Enter your ngrok Auth Token: " NGROK_AUTHTOKEN
    if [[ -z "${NGROK_AUTHTOKEN:-}" ]]; then
      log_warn "Token left blank — placeholder written. Edit $ENV_FILE before starting."
      NGROK_AUTHTOKEN="PASTE_YOUR_NGROK_TOKEN_HERE"
    fi
  fi

  # ── dashboard basic-auth credentials ──
  # Re-use existing password if credentials file exists
  if [[ -f "$CREDS_FILE" ]]; then
    _existing_pass=$(grep '^Password:' "$CREDS_FILE" 2>/dev/null | awk '{print $2}' || true)
    if [[ -n "${_existing_pass:-}" ]]; then
      NGROK_AUTH_PASS="$_existing_pass"
      log_ok "Reusing existing dashboard password from credentials.txt"
    fi
  fi

  if [[ -z "${NGROK_AUTH_PASS:-}" ]]; then
    log_info "Generating secure ngrok basic-auth password..."
    NGROK_AUTH_PASS=$(gen_password)
    log_ok "Password generated (24-char hex — alphanumeric only)"
  fi

  echo ""
  log_ok "Config ready"
  log_info "ngrok token:        ${NGROK_AUTHTOKEN:0:8}****"
  log_info "Dashboard user:     ${NGROK_AUTH_USER}"
  log_info "Dashboard password: ${NGROK_AUTH_PASS}"
}

# ─────────────────────────────────────────────────────────────────
#  STEP 4 — DIRECTORY STRUCTURE
# ─────────────────────────────────────────────────────────────────
create_directories() {
  log_step "Step 4/10 — Creating Directory Structure"

  mkdir -p "$PROJECT_DIR" "$SCRIPTS_DIR" "$LOGS_DIR" "$HERMES_DATA_DIR"
  chmod 700 "$HERMES_DATA_DIR"   # only owner can read hermes data

  log_ok "$PROJECT_DIR"
  log_ok "$HERMES_DATA_DIR  (chmod 700)"
  log_ok "$SCRIPTS_DIR"
  log_ok "$LOGS_DIR"
}

# ─────────────────────────────────────────────────────────────────
#  STEP 5 — GENERATE CONFIG FILES
# ─────────────────────────────────────────────────────────────────
generate_configs() {
  log_step "Step 5/10 — Generating Configuration Files"

  # ── .env ─────────────────────────────────────────────────────
  cat > "$ENV_FILE" <<EOF
# =================================================================
# Hermes Agent + ngrok  —  Environment Variables
# DO NOT commit this file to git  |  chmod 600 enforced by script
# =================================================================

# ── ngrok ────────────────────────────────────────────────────────
NGROK_AUTHTOKEN=${NGROK_AUTHTOKEN}

# ── ngrok Basic Auth (auto-generated — protects dashboard) ───────
# This is the login for the Hermes web portal via ngrok URL
NGROK_AUTH_USER=${NGROK_AUTH_USER}
NGROK_AUTH_PASS=${NGROK_AUTH_PASS}

# ── Hermes Gateway API (auto-generated strong key) ───────────────
API_SERVER_KEY=$(gen_password)$(gen_password)

# ── LLM API Keys  (add after first web portal access) ────────────
# Provider 1 — OpenRouter  (free tier available)
# Get key → https://openrouter.ai/keys
# OPENROUTER_API_KEY=sk-or-v1-

# Provider 2 — Google Gemini  (free tier available)
# Get key → https://aistudio.google.com/app/apikey
# GOOGLE_API_KEY=AIza

# Provider 3 — Anthropic  (optional)
# ANTHROPIC_API_KEY=sk-ant-

# Provider 4 — OpenAI  (optional)
# OPENAI_API_KEY=sk-
EOF
  chmod 600 "$ENV_FILE"
  log_ok ".env  ->  $ENV_FILE  (chmod 600)"

  # docker-compose.yml
  cat > "$COMPOSE_FILE" <<EOF
services:
  hermes-agent:
    image: ${HERMES_IMAGE}
    container_name: hermes-agent
    restart: unless-stopped
    command: gateway run
    ports:
      - "127.0.0.1:${HERMES_DASHBOARD_PORT}:${HERMES_DASHBOARD_PORT}"
      - "127.0.0.1:${HERMES_API_PORT}:${HERMES_API_PORT}"
    env_file:
      - .env
    environment:
      HERMES_DASHBOARD: "1"
      HERMES_DASHBOARD_HOST: "0.0.0.0"
      HERMES_DASHBOARD_PORT: "${HERMES_DASHBOARD_PORT}"
      HERMES_DASHBOARD_INSECURE: "1"
      API_SERVER_ENABLED: "true"
      API_SERVER_HOST: "0.0.0.0"
      LOG_LEVEL: "\${LOG_LEVEL:-INFO}"
      API_SERVER_KEY: "\${API_SERVER_KEY}"
      API_SERVER_CORS_ORIGINS: "*"
    volumes:
      - "${HERMES_DATA_DIR}:/opt/data"
      - "${LOGS_DIR}:/var/log/hermes"
    networks:
      - hermes_net

  ngrok-hermes:
    image: ${NGROK_IMAGE}
    container_name: hermes-ngrok
    restart: unless-stopped
    command:
      - http
      - hermes-agent:${HERMES_DASHBOARD_PORT}
      - --log=stdout
      - --region=eu
      - --basic-auth=\${NGROK_AUTH_USER}:\${NGROK_AUTH_PASS}
    environment:
      NGROK_AUTHTOKEN: "\${NGROK_AUTHTOKEN}"
    ports:
      - "127.0.0.1:${NGROK_MGMT_PORT}:${NGROK_MGMT_PORT}"
    depends_on:
      - hermes-agent
    networks:
      - hermes_net

networks:
  hermes_net:
    driver: bridge
    name: hermes_net
EOF
  log_ok "docker-compose.yml  ->  $COMPOSE_FILE"

  # credentials.txt
  cat > "$CREDS_FILE" <<EOF
Hermes Dashboard Access

URL: run bash ${SCRIPTS_DIR}/get-url.sh after startup
Username: ${NGROK_AUTH_USER}
Password: ${NGROK_AUTH_PASS}

Credentials protect the ngrok public URL with HTTP Basic Auth.
EOF
  chmod 600 "$CREDS_FILE"
  log_ok "credentials.txt  ->  $CREDS_FILE  (chmod 600)"
  log_ok ".env  →  $ENV_FILE  (chmod 600)"

  # ── .gitignore ───────────────────────────────────────────────
  cat > "$PROJECT_DIR/.gitignore" <<'EOF'
.env
credentials.txt
current-url.txt
logs/
*.log
EOF
  log_ok ".gitignore created"
}

# ─────────────────────────────────────────────────────────────────
#  STEP 6 — GENERATE HELPER SCRIPTS
# ─────────────────────────────────────────────────────────────────
generate_scripts() {
  log_step "Step 6/10 — Generating Helper Scripts"

  # ── get-url.sh ───────────────────────────────────────────────
  cat > "$SCRIPTS_DIR/get-url.sh" <<'GETURL_EOF'
#!/usr/bin/env bash
set -euo pipefail
URL_FILE="$HOME/hermes-ngrok/current-url.txt"
NGROK_API="http://localhost:4040/api/tunnels"
CREDS="$HOME/hermes-ngrok/credentials.txt"

if [[ -f "$URL_FILE" ]]; then
  URL=$(cat "$URL_FILE")
else
  URL=$(curl -sf "$NGROK_API" 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['tunnels'][0]['public_url'])" \
    2>/dev/null || echo "")
  [[ -n "$URL" ]] && echo "$URL" > "$URL_FILE"
fi

echo ""
if [[ -n "$URL" ]]; then
  echo "  🌐  Hermes Dashboard URL:"
  echo "      $URL"
  echo ""
  echo "  🔑  Login credentials:"
  grep -E '^[[:space:]]*(Username|Password):' "$CREDS" 2>/dev/null || echo "      See: $CREDS"
else
  echo "  ⚠   No URL found. Check services are running:"
  echo "      docker compose -f $HOME/hermes-ngrok/docker-compose.yml ps"
fi
echo ""
GETURL_EOF
  chmod +x "$SCRIPTS_DIR/get-url.sh"
  log_ok "get-url.sh"

  # ── start.sh ─────────────────────────────────────────────────
  cat > "$SCRIPTS_DIR/start.sh" <<'STARTEOF'
#!/usr/bin/env bash
set -euo pipefail
echo "Starting Hermes Agent + ngrok..."
cd "$HOME/hermes-ngrok"
docker compose up -d
echo "Waiting for ngrok tunnel..."
sleep 12
bash "$HOME/hermes-ngrok/scripts/get-url.sh"
STARTEOF
  chmod +x "$SCRIPTS_DIR/start.sh"
  log_ok "start.sh"

  # ── stop.sh ──────────────────────────────────────────────────
  cat > "$SCRIPTS_DIR/stop.sh" <<'STOPEOF'
#!/usr/bin/env bash
set -euo pipefail
echo "Stopping Hermes Agent + ngrok..."
cd "$HOME/hermes-ngrok"
docker compose down
echo "All services stopped."
STOPEOF
  chmod +x "$SCRIPTS_DIR/stop.sh"
  log_ok "stop.sh"

  # ── restart.sh ───────────────────────────────────────────────
  cat > "$SCRIPTS_DIR/restart.sh" <<'RESTARTEOF'
#!/usr/bin/env bash
set -euo pipefail
echo "Restarting all services (data preserved)..."
cd "$HOME/hermes-ngrok"
docker compose restart
echo "Waiting for ngrok tunnel..."
sleep 12
bash "$HOME/hermes-ngrok/scripts/get-url.sh"
RESTARTEOF
  chmod +x "$SCRIPTS_DIR/restart.sh"
  log_ok "restart.sh"

  # ── status.sh ────────────────────────────────────────────────
  cat > "$SCRIPTS_DIR/status.sh" <<'STATUSEOF'
#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/hermes-ngrok"
echo ""
echo "═══════════════════════════════════════════"
echo "  Container Status"
echo "═══════════════════════════════════════════"
docker compose ps
echo ""
echo "═══════════════════════════════════════════"
echo "  Current Access URL"
echo "═══════════════════════════════════════════"
bash "$HOME/hermes-ngrok/scripts/get-url.sh"
echo ""
echo "═══════════════════════════════════════════"
echo "  URL Watcher Service"
echo "═══════════════════════════════════════════"
sudo systemctl status hermes-url-watcher --no-pager -l 2>/dev/null || \
  echo "  Watcher not running as systemd service"
echo ""
echo "═══════════════════════════════════════════"
echo "  Recent Hermes Logs (last 25 lines)"
echo "═══════════════════════════════════════════"
docker compose logs --tail=25 hermes-agent
STATUSEOF
  chmod +x "$SCRIPTS_DIR/status.sh"
  log_ok "status.sh"

  log_ok "All helper scripts created in $SCRIPTS_DIR"
}

# ─────────────────────────────────────────────────────────────────
#  STEP 7 — GENERATE URL WATCHER
# ─────────────────────────────────────────────────────────────────
generate_watcher() {
  log_step "Step 7/10 — Creating URL Watcher Script"

  cat > "$SCRIPTS_DIR/url-watcher.sh" <<'WATCHER_EOF'
#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$HOME/hermes-ngrok"
URL_FILE="$PROJECT_DIR/current-url.txt"
LOG_FILE="$PROJECT_DIR/logs/url-watcher.log"
NGROK_API="http://localhost:4040/api/tunnels"
POLL_INTERVAL=30
MAX_STARTUP_WAIT=120

GREEN='\033[0;32m' CYAN='\033[0;36m' YELLOW='\033[1;33m'
BOLD='\033[1m' RESET='\033[0m'

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*" | tee -a "$LOG_FILE"; }

get_url() {
  local resp url
  resp=$(curl -sf "$NGROK_API" 2>/dev/null) || { echo ""; return; }
  url=$(echo "$resp" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['tunnels'][0]['public_url'])" \
    2>/dev/null) || { echo ""; return; }
  echo "$url"
}

print_url_banner() {
  local url="$1"
  echo -e ""
  echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════╗${RESET}"
  echo -e "${CYAN}${BOLD}║         HERMES DASHBOARD  —  LIVE ACCESS URL              ║${RESET}"
  echo -e "${CYAN}${BOLD}╠══════════════════════════════════════════════════════════╣${RESET}"
  echo -e "${CYAN}${BOLD}║${RESET}  🌐  ${GREEN}${BOLD}${url}${RESET}"
  echo -e "${CYAN}${BOLD}╠══════════════════════════════════════════════════════════╣${RESET}"
  echo -e "${CYAN}${BOLD}║${RESET}  🔑  Login: see  ${YELLOW}~/hermes-ngrok/credentials.txt${RESET}"
  echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════╝${RESET}"
  echo -e ""
}

mkdir -p "$(dirname "$LOG_FILE")"
log "━━━ URL Watcher started (poll every ${POLL_INTERVAL}s) ━━━"

log "Waiting for ngrok management API..."
WAIT=0
until curl -sf "$NGROK_API" &>/dev/null; do
  sleep 2; WAIT=$((WAIT + 2))
  if (( WAIT >= MAX_STARTUP_WAIT )); then
    log "ERROR: ngrok API not responding after ${MAX_STARTUP_WAIT}s — is the container up?"
    log "  Check: docker compose -f $PROJECT_DIR/docker-compose.yml ps"
    break
  fi
done
log "ngrok management API is up"

LAST_URL=""
while true; do
  CURRENT_URL=$(get_url)

  if [[ -n "$CURRENT_URL" && "$CURRENT_URL" != "null" ]]; then
    if [[ "$CURRENT_URL" != "$LAST_URL" ]]; then
      if [[ -n "$LAST_URL" ]]; then
        log "URL CHANGED  →  $LAST_URL  →  $CURRENT_URL"
      else
        log "URL ACQUIRED →  $CURRENT_URL"
      fi
      echo "$CURRENT_URL" > "$URL_FILE"
      LAST_URL="$CURRENT_URL"
      print_url_banner "$CURRENT_URL"
    fi
  else
    log "WARNING: Could not read ngrok URL — ngrok may be restarting..."
  fi

  sleep "$POLL_INTERVAL"
done
WATCHER_EOF
  chmod +x "$SCRIPTS_DIR/url-watcher.sh"
  log_ok "url-watcher.sh"
}

# ─────────────────────────────────────────────────────────────────
#  STEP 8 — SYSTEMD SERVICE
# ─────────────────────────────────────────────────────────────────
setup_watcher_service() {
  log_step "Step 8/10 — Installing URL Watcher as systemd Service"
  require_sudo

  local svc="/etc/systemd/system/${WATCHER_SERVICE}.service"

  sudo tee "$svc" > /dev/null <<SVCEOF
[Unit]
Description=Hermes Agent — ngrok URL Watcher
Documentation=n8n-ngrok-automation pattern
After=network-online.target docker.service
Requires=docker.service
Wants=network-online.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${SCRIPTS_DIR}/url-watcher.sh
Restart=on-failure
RestartSec=15
StandardOutput=journal
StandardError=journal
SyslogIdentifier=hermes-url-watcher
ExecStartPre=/bin/sleep 15

[Install]
WantedBy=multi-user.target
SVCEOF

  sudo systemctl daemon-reload
  sudo systemctl enable "${WATCHER_SERVICE}"
  log_ok "systemd service registered: ${WATCHER_SERVICE}"
  log_ok "Service auto-starts on VM boot"
}

# ─────────────────────────────────────────────────────────────────
#  STEP 9 — PULL DOCKER IMAGES
# ─────────────────────────────────────────────────────────────────
pull_images() {
  log_step "Step 9/10 — Pulling Docker Images"

  log_info "Pulling $HERMES_IMAGE ..."
  sudo docker pull "$HERMES_IMAGE"
  log_ok "Hermes Agent image ready"

  log_info "Pulling $NGROK_IMAGE ..."
  sudo docker pull "$NGROK_IMAGE"
  log_ok "ngrok image ready"
}

# ─────────────────────────────────────────────────────────────────
#  STEP 10 — START SERVICES & DISPLAY INFO
# ─────────────────────────────────────────────────────────────────
start_services() {
  log_step "Step 10/10 — Starting All Services"

  cd "$PROJECT_DIR"

  log_info "Starting docker compose stack..."
  sudo docker compose up -d

  echo ""
  sudo docker compose ps
  echo ""

  wait_for_port "$HERMES_DASHBOARD_PORT" "Hermes Dashboard" 40 3 || true
  wait_for_port "$NGROK_MGMT_PORT"       "ngrok Mgmt API"   20 2 || true

  log_info "Starting URL watcher service..."
  if sudo systemctl start "${WATCHER_SERVICE}" 2>/dev/null; then
    log_ok "systemd URL watcher started"
  else
    log_warn "systemd start failed — starting watcher in background"
    mkdir -p "$LOGS_DIR"
    nohup bash "$SCRIPTS_DIR/url-watcher.sh" >> "$WATCHER_LOG" 2>&1 &
    echo $! > "$PROJECT_DIR/url-watcher.pid"
    log_ok "URL watcher running (PID: $(cat "$PROJECT_DIR/url-watcher.pid"))"
  fi

  log_info "Waiting for ngrok to establish tunnel (10s)..."
  sleep 10
}

display_final_info() {
  log_sep

  LIVE_URL=$(get_ngrok_url 2>/dev/null || cat "$URL_FILE" 2>/dev/null || echo "")
  [[ -n "$LIVE_URL" ]] && echo "$LIVE_URL" > "$URL_FILE"

  echo ""
  echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════════╗${RESET}"
  echo -e "${GREEN}${BOLD}║              HERMES AGENT — DEPLOYMENT COMPLETE               ║${RESET}"
  echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════════════╝${RESET}"
  echo ""
  echo -e "${BOLD}  ┌─  DASHBOARD ACCESS  ───────────────────────────────────────┐${RESET}"
  if [[ -n "$LIVE_URL" ]]; then
    echo -e "  │  🌐  URL:       ${CYAN}${BOLD}${LIVE_URL}${RESET}"
  else
    echo -e "  │  🌐  URL:       ${YELLOW}run  bash ${SCRIPTS_DIR}/get-url.sh${RESET}"
  fi
  echo -e "  │  🔑  Username:  ${BOLD}${NGROK_AUTH_USER}${RESET}"
  echo -e "  │  🔑  Password:  ${BOLD}${YELLOW}${NGROK_AUTH_PASS}${RESET}"
  echo -e "  │"
  echo -e "  │  Credentials saved to: ${CYAN}${CREDS_FILE}${RESET}"
  echo -e "  └────────────────────────────────────────────────────────────"
  echo ""
  echo -e "${BOLD}  ┌─  LLM API KEYS (configure after portal access)  ──────────┐${RESET}"
  echo -e "  │  OpenRouter:  https://openrouter.ai/keys"
  echo -e "  │  Gemini:      https://aistudio.google.com/app/apikey"
  echo -e "  │  After getting keys, uncomment in: ${CYAN}${ENV_FILE}${RESET}"
  echo -e "  │  Then restart:  ${CYAN}bash ${SCRIPTS_DIR}/restart.sh${RESET}"
  echo -e "  └────────────────────────────────────────────────────────────"
  echo ""
  echo -e "${BOLD}  ┌─  QUICK COMMANDS  ──────────────────────────────────────────┐${RESET}"
  echo -e "  │  Get URL now:    ${CYAN}bash ${SCRIPTS_DIR}/get-url.sh${RESET}"
  echo -e "  │  Full status:    ${CYAN}bash ${SCRIPTS_DIR}/status.sh${RESET}"
  echo -e "  │  Stop all:       ${CYAN}bash ${SCRIPTS_DIR}/stop.sh${RESET}"
  echo -e "  │  Restart all:    ${CYAN}bash ${SCRIPTS_DIR}/restart.sh${RESET}"
  echo -e "  └────────────────────────────────────────────────────────────"
  echo ""
  echo -e "${BOLD}  ┌─  DOCKER LOGS  ──────────────��──────────────────────────────┐${RESET}"
  echo -e "  │  Hermes:    ${CYAN}docker logs -f hermes-agent${RESET}"
  echo -e "  │  ngrok:     ${CYAN}docker logs -f hermes-ngrok${RESET}"
  echo -e "  │  Both:      ${CYAN}cd ${PROJECT_DIR} && docker compose logs -f${RESET}"
  echo -e "  └────────────────────────────────────────────────────────────"
  echo ""
  echo -e "${BOLD}  ┌─  NEXT STEPS  ──────────────────────────────────────────────┐${RESET}"
  echo -e "  │  1. Open the URL above in your browser"
  echo -e "  │  2. Enter the username/password above when prompted"
  echo -e "  │  3. Get your LLM API keys (OpenRouter or Gemini — free tier)"
  echo -e "  │  4. Add keys via the web portal  OR  edit ${ENV_FILE}"
  echo -e "  │     and restart with: bash ${SCRIPTS_DIR}/restart.sh"
  echo -e "  └────────────────────────────────────────────────────────────"
  echo ""
  log_sep
  echo -e "  ${DIM}URL watcher tracks ngrok URL changes automatically${RESET}"
  echo -e "  ${DIM}Free plan = random URL on ngrok restart — watcher handles it${RESET}"
  echo ""
}

uninstall() {
  echo ""
  echo -e "${RED}${BOLD}⚠  UNINSTALL${RESET}"
  echo -e "  Stops and removes containers + project files."
  echo -e "  ${GREEN}Your data in ~/.hermes is PRESERVED.${RESET}"
  echo ""
  read -rp "  Type 'yes' to confirm: " CONFIRM
  [[ "$CONFIRM" != "yes" ]] && { echo "Aborted."; exit 0; }

  sudo systemctl stop "${WATCHER_SERVICE}"  2>/dev/null || true
  sudo systemctl disable "${WATCHER_SERVICE}" 2>/dev/null || true
  sudo rm -f "/etc/systemd/system/${WATCHER_SERVICE}.service"
  sudo systemctl daemon-reload

  [[ -f "$COMPOSE_FILE" ]] && { cd "$PROJECT_DIR"; docker compose down --remove-orphans 2>/dev/null || true; }

  echo ""
  log_warn "Project dir preserved: $PROJECT_DIR"
  log_warn "Hermes data preserved: $HERMES_DATA_DIR"
  log_ok   "Uninstall complete"
  exit 0
}

main() {
  case "${1:-deploy}" in
    --uninstall|-u)   banner; uninstall ;;
    --status|-s)      bash "$SCRIPTS_DIR/status.sh" 2>/dev/null || echo "Not deployed yet."; exit 0 ;;
    --url)            bash "$SCRIPTS_DIR/get-url.sh" 2>/dev/null || echo "Not deployed yet."; exit 0 ;;
    --creds)          [[ -f "$CREDS_FILE" ]] && cat "$CREDS_FILE" || echo "Not deployed yet."; exit 0 ;;
    --help|-h)
      echo "Usage: $0 [OPTION]"
      echo "  (no args)    Full deployment"
      echo "  --status     Container status + URL"
      echo "  --url        Print current ngrok URL"
      echo "  --creds      Print dashboard credentials"
      echo "  --uninstall  Stop containers + remove project"
      echo "  --help       This message"
      exit 0 ;;
    deploy|"") ;;
    *) log_error "Unknown: ${1}"; echo "Run with --help"; exit 1 ;;
  esac

  banner
  check_prerequisites
  install_docker
  collect_config
  create_directories
  generate_configs
  generate_scripts
  generate_watcher
  setup_watcher_service
  pull_images
  start_services
  display_final_info
}

main "$@"
