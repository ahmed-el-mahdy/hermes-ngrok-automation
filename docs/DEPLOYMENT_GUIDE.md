# Deployment Guide

The repository currently pins Open WebUI `v0.10.2`. Review the official release notes and run the recreation validation before changing this version.

## Initial Setup

1. Clone the repository on the Ubuntu VM.
2. Run `chmod +x hermes-ngrok-deploy.sh`.
3. Run `./hermes-ngrok-deploy.sh` and enter the ngrok token when prompted.
4. Add valid provider keys to `~/hermes-ngrok/.env` or the persistent Hermes configuration.
5. Open the ngrok URL and sign in with the Open WebUI account saved in `~/hermes-ngrok/credentials.txt`.

The public URL must load Open WebUI directly. A browser-native username/password popup means ngrok Basic Auth or an edge traffic policy is still enabled and must be removed.

## Deploy the Agent Catalog

Copy the repository automation files to the VM, then run them from the project root. Supply portal credentials as environment variables rather than embedding them in files.

```bash
export PORTAL_EMAIL='admin@hermes.local'
read -rsp 'Open WebUI password: ' PORTAL_PASSWORD
export PORTAL_PASSWORD

bash deploy-canonical-tools.sh
bash deploy-model-catalog.sh
bash deploy-prompt-library.sh
bash validate-model-catalog.sh
```

Each deployment wrapper creates a timestamped database backup under `~/hermes-backups`.

## Model Routing

Model routing is stored in `~/.hermes/config.yaml` and secrets in `~/.hermes/.env`. The recommended automatic order is Gemini 3.1 Flash Lite, Gemini 2.5 Flash, then the LAN-restricted Ollama GPU endpoint. NaraRouter presets are manual-only because an unavailable cloud route can otherwise delay fallback.

Validate each provider independently before adding it to the fallback chain. Interpret common responses as follows:

| HTTP status | Meaning |
| --- | --- |
| 200 | Route works |
| 401 | Invalid or malformed credential |
| 402 | Provider credit required |
| 404 | Model ID or endpoint does not exist |
| 429 | Quota or rate limit reached |

Do not publish a preset for a route that does not return a successful chat completion.

## Local Ollama Fallback

The Windows Ollama listener must be reachable only from the trusted LAN/VM network. From the VM:

```bash
curl -fsS http://WINDOWS_LAN_IP:11434/api/tags
```

Confirm the requested model is loaded and inspect `ollama ps` on Windows. Keep local Qwen as the final fallback because it is reliable offline but generally weaker than the selected cloud routes.

## Telegram Activation

Create a bot with BotFather and obtain the numeric Telegram user ID that is allowed to use it. Add these to `~/hermes-ngrok/.env`:

```dotenv
TELEGRAM_BOT_TOKEN=replace_me
TELEGRAM_ALLOWED_USERS=123456789
TELEGRAM_REQUIRE_MENTION=true
```

For group use, also set `TELEGRAM_GROUP_ALLOWED_USERS` and `TELEGRAM_GROUP_ALLOWED_CHATS`. Then run:

```bash
cd ~/hermes-ngrok
docker compose up -d --force-recreate hermes-agent
docker logs --tail 100 hermes-agent
```

Never set `GATEWAY_ALLOW_ALL_USERS=true` or `TELEGRAM_ALLOW_ALL_USERS=true` on an internet-connected deployment.

## Operations

```bash
# Stack status
docker compose -f ~/hermes-ngrok/docker-compose.yml ps

# Public URL
curl -fsS http://127.0.0.1:4040/api/tunnels

# Logs
docker logs --tail 100 hermes-agent
docker logs --tail 100 hermes-open-webui
docker logs --tail 100 hermes-ngrok

# Recreate services while preserving data
cd ~/hermes-ngrok
docker compose up -d --build --force-recreate
```

## Backup

Back up these locations before upgrades:

```text
~/.hermes
~/hermes_workspace
~/hermes-ngrok/.env
Docker volume open-webui-data
```

The automation scripts place SQLite and configuration snapshots in `~/hermes-backups` before catalog changes.

## Troubleshooting

### ngrok endpoint offline

Check all three containers and confirm ngrok targets `open-webui:8080` on the shared Compose network.

### Open WebUI login loops

Remove ngrok Basic Auth/OAuth, use the Open WebUI email login, and clear cached browser credentials.

### Agent does not answer

Inspect `hermes-agent` logs, verify its authenticated `/v1/models` endpoint, test the primary provider, then test each fallback independently.

### Node execution fails

Rebuild `hermes-open-webui:local` from `Dockerfile.open-webui`; the stock image does not guarantee a Node runtime.

### Workspace permission error

Confirm the host path is mounted at `/app/backend/data/hermes_workspace`. Keep normal artifacts user-writable and avoid using container-root-owned test folders for host-side writes.
