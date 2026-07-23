# Hermes Open WebUI Automation

Deploy Hermes Agent behind Open WebUI and publish only the Open WebUI login through ngrok. The Hermes dashboard and API remain bound to the VM loopback interface.

The custom dashboard image is pinned to Open WebUI `v0.10.2` and adds Node.js for the canonical Code Executor tool. The custom Hermes image adds the supported local `faster-whisper` voice runtime.

## Architecture

```text
Browser
  -> ngrok HTTPS endpoint
  -> Open WebUI :8080
     -> Hermes OpenAI-compatible API :8642
        -> Gemini primary and cloud fallback
     -> Windows Ollama native API :11434
        -> qwen3-4b-gpu:latest
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

The validated cloud routing policy inside Hermes is:

1. `gemini-3.1-flash-lite`
2. `gemini-2.5-flash`

The local model is published separately as `hermes-local-gpu`. Open WebUI calls `qwen3-4b-gpu:latest` through Ollama's native `/api/chat` endpoint, which preserves Ollama reasoning behavior and avoids the empty-content responses seen through the OpenAI compatibility endpoint. Provider credentials are runtime secrets and must never be committed.

### Persistent Windows Ollama

Install the Windows boot task from an elevated PowerShell session:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\Install-HermesOllamaTask.ps1
```

The task runs Ollama as `SYSTEM` at startup, preloads `qwen3-4b-gpu:latest`, requires the model's full size to be resident in VRAM, keeps it loaded, restarts after failures, and creates an inbound firewall rule restricted to the Hermes VM address `192.168.1.5`.

Run a controlled restart test from an elevated PowerShell session:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\Test-HermesOllamaRecovery.ps1
```

### Persistent VMware Hermes VM

Install the interactive logon task from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\Install-HermesVMTask.ps1
```

The `Hermes VM Autostart` task opens VMware Workstation, starts `Ubuntu Mini Hermes` only when it is not already running, waits for SSH at `192.168.1.5`, and verifies the public Hermes portal. Its launcher is copied to `%LOCALAPPDATA%\HermesVMStartup`, and startup results are written to `startup.log` there. Docker and all three Hermes containers are configured to start automatically inside Ubuntu, so no Ubuntu password is stored in the Windows task.

After Ollama is reachable, configure the two supported portal connections and publish the model catalog:

```bash
OLLAMA_BASE_URL='http://192.168.1.2:11434' bash configure-openwebui-providers.sh
PORTAL_EMAIL='admin@hermes.local' PORTAL_PASSWORD='...' bash deploy-model-catalog.sh
```

Apply the routing policy without putting keys on disk in the repository:

```bash
GOOGLE_API_KEY='...' bash apply-model-routing.sh
```

Published Open WebUI profiles:

- `hermes`
- `orchestrator`, `searcher`, `scraper`, `builder`, `coder`
- `reviewer`, `designer`, `consultant`, `coordinator`
- `hermes-local-gpu` through the native Ollama API

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

### Telegram Images And Voice

Enable the low-cost media profile after Telegram activation:

```bash
bash configure-telegram-media.sh
```

This profile uses local `faster-whisper large-v3-turbo` with forced Arabic decoding, Egyptian Arabic context, beam search, and silence filtering for incoming voice messages. Free Edge TTS with `ar-EG-ShakirNeural` handles outgoing Arabic speech. The Whisper model is downloaded during setup and cached under persistent Hermes data, so container recreation does not download it again. Ordinary replies stay text-only; Hermes generates an OGG/Opus Telegram voice note when the user explicitly asks for a voice reply. Telegram photos, image documents, and static stickers are cached and passed to the configured vision-capable Gemini model. Hermes answers this user in clear Egyptian Arabic by default.

Override the defaults when needed:

```bash
STT_MODEL=small STT_LANGUAGE=ar TTS_VOICE=ar-EG-SalmaNeural \
  bash configure-telegram-media.sh
```

## Validation

The acceptance suite verifies:

- all seven tools
- all 11 model profiles
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
