# Hermes Open WebUI Automation

Deploy Hermes Agent behind Open WebUI and publish only the Open WebUI login through ngrok. The Hermes dashboard and API remain bound to the VM loopback interface.

The custom dashboard image is pinned to Open WebUI `v0.10.2` and adds Node.js for the canonical Code Executor tool.

## Architecture

```text
Browser
  -> ngrok HTTPS endpoint
  -> Open WebUI :8080
  -> Hermes OpenAI-compatible API :8642
  -> Gemini primary
     -> NaraRouter cloud fallbacks
     -> Windows Ollama GPU fallback
```

The deployment uses three containers on one private Docker bridge network:

| Container | Purpose | Host exposure |
| --- | --- | --- |
| `hermes-open-webui` | Authenticated chat dashboard | `127.0.0.1:3000` |
| `hermes-agent` | Agent gateway and model router | `127.0.0.1:8642`, `127.0.0.1:9119` |
| `hermes-ngrok` | HTTPS tunnel to Open WebUI | `127.0.0.1:4040` management API |

ngrok Basic Auth and OAuth are intentionally absent. Users authenticate once with the Open WebUI email/password form.

## Requirements

- Ubuntu VM with Docker Engine and Docker Compose v2
- 8 GB RAM recommended
- 20 GB free disk space recommended
- ngrok account and auth token
- At least one valid LLM provider key
- Optional Ollama endpoint reachable from the VM

## Deploy

```bash
git clone https://github.com/ahmed-el-mahdy/hermes-ngrok-automation.git
cd hermes-ngrok-automation
chmod +x hermes-ngrok-deploy.sh
./hermes-ngrok-deploy.sh
```

The script preserves an existing `~/hermes-ngrok/.env`, generates missing local secrets, builds the Node-enabled Open WebUI image, starts the stack, and prints the current ngrok URL. Secrets are stored only in `~/hermes-ngrok/.env` with mode `0600`.

Useful commands:

```bash
./hermes-ngrok-deploy.sh --status
./hermes-ngrok-deploy.sh --url
./hermes-ngrok-deploy.sh --restart
docker compose -f ~/hermes-ngrok/docker-compose.yml logs -f
```

## Persistent Data

| Host path or volume | Contents |
| --- | --- |
| `~/.hermes` | Hermes configuration, memory, sessions, and provider routing |
| `~/hermes_workspace` | Tool, specialist, workflow, and acceptance artifacts |
| `~/hermes-ngrok/logs` | Hermes logs |
| `open-webui-data` | Open WebUI users, chats, models, tools, and prompts |
| `~/hermes-backups` | Timestamped configuration and database backups |

Container recreation does not remove these locations. Do not use `docker compose down -v` unless Open WebUI data should be deleted.

## Model Routing

The validated routing policy is:

1. `gemini-3.1-flash-lite`
2. `gemini-2.5-flash`
3. `qwen3-4b-gpu:latest` through a trusted LAN Ollama endpoint

NaraRouter presets remain available for manual use but are excluded from automatic fallback so a provider outage cannot stall normal chats. Provider credentials are runtime secrets and must never be committed.

Apply the routing policy without putting keys on disk in the repository:

```bash
GOOGLE_API_KEY='...' NARA_ROUTER_API_KEY='...' \
OLLAMA_BASE_URL='http://trusted-host:11434' bash apply-model-routing.sh
```

Published Open WebUI profiles:

- `hermes`
- `orchestrator`, `searcher`, `scraper`, `builder`, `coder`
- `reviewer`, `designer`, `consultant`, `coordinator`
- `nara-writer`, `nara-reasoner`, `nara-general`

## Canonical Tools

Seven audited tools are maintained under `openwebui-tools/`:

- File System Manager
- Code Executor
- Shell Command Runner
- Git Operations
- Web Research
- Hermes Persistent Memory
- Agent Evaluator

Path traversal, shell operators, and private-network URL requests are rejected. Tool deployment and validation scripts create timestamped Open WebUI database backups before changes.

## Dashboard Prompts

The deployment library contains ten reusable prompts for coding, research, project building, review, orchestration, continuation, durable memory, recommendations, scraping, and debugging. They are installed through Open WebUI's prompt API, not direct database edits.

## Telegram

Telegram is disabled until `TELEGRAM_BOT_TOKEN` is set. Enable it only with an explicit numeric user allowlist:

```dotenv
TELEGRAM_BOT_TOKEN=replace_with_botfather_token
TELEGRAM_ALLOWED_USERS=123456789
TELEGRAM_GROUP_ALLOWED_USERS=123456789
TELEGRAM_GROUP_ALLOWED_CHATS=-1001234567890
TELEGRAM_REQUIRE_MENTION=true
```

Compose forces `TELEGRAM_ALLOW_ALL_USERS=false` and `GATEWAY_ALLOW_ALL_USERS=false`. Restart `hermes-agent` after adding the token and allowlist.

## Validation

The acceptance suite verifies:

- all seven tools
- all 13 model profiles
- all nine specialist artifacts
- all ten prompt patterns
- the 30-skill matrix
- four workflows: FastAPI, research, shell automation, and UI build

Evidence is written to `~/hermes_workspace/shared/outputs/`. See [Deployment Guide](docs/DEPLOYMENT_GUIDE.md) for commands and [Implementation Plan](docs/IMPLEMENTATION_PLAN.md) for the current architecture and acceptance gates.

## Security

- Only Open WebUI is exposed through ngrok.
- Local service ports bind to `127.0.0.1`.
- Open WebUI signup is disabled.
- ngrok browser-level auth is disabled to prevent login loops.
- Telegram and the global gateway remain deny-by-default.
- Provider keys and portal credentials stay in `.env` or persistent Hermes configuration.
- Rotate any token that has been pasted into chat or logs.

This deployment is suitable for a personal workstation VM. For wider production use, add a static domain, rate limiting, monitored backups, and an identity-aware edge policy.
