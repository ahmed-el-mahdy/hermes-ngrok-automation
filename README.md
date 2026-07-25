# Hermes Open WebUI Automation

Deploy Hermes Agent behind Open WebUI and publish only the Open WebUI login through ngrok. The native Hermes dashboard is disabled; the Hermes API remains bound to the VM loopback interface.

The custom dashboard image is pinned to Open WebUI `v0.10.2` and adds Node.js for the canonical Code Executor tool. The custom Hermes image is pinned to the tested Hermes release `v2026.7.20` and adds local voice, document extraction, OCR, web parsing, and persistent Python package support. Release upgrades are deliberate and must pass the voice, Telegram, browser, document, and runtime checks before the pin moves.

## Architecture

```text
Browser
  -> ngrok HTTPS endpoint
  -> Open WebUI :8080
     -> Hermes OpenAI-compatible API :8642
        -> NaraRouter primary
        -> local Ollama bridge and GPU fallback
        -> OpenRouter and Gemini recovery routes
     -> Windows Ollama native API :11434
        -> qwen3-4b-gpu:latest
```

The deployment uses four containers on one private Docker bridge network:

| Container | Purpose | Host exposure |
| --- | --- | --- |
| `hermes-open-webui` | Authenticated chat dashboard | `127.0.0.1:3000` |
| `hermes-agent` | Agent gateway and model router | `127.0.0.1:8642` |
| `hermes-ollama-bridge` | Native Ollama to OpenAI compatibility bridge | None |
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

The validated automatic cloud routing policy inside Hermes is:

1. `mistral-large` through NaraRouter
2. `gpt-oss:20b` through Ollama Cloud when `OLLAMA_API_KEY` is configured
3. `nvidia/nemotron-3-super-120b-a12b:free` through OpenRouter
4. `qwen3-4b-gpu:latest` through the local Ollama bridge
5. `laguna-s-2.1` through NaraRouter
6. `openrouter/free`
7. `gemini-2.5-flash`

NaraRouter Mistral, Ollama Cloud GPT-OSS, OpenRouter Nemotron, NaraRouter Laguna, and local Qwen were live-tested with tool calling. The first three positions use independent free cloud allowances before local Qwen takes the fourth overall position. `glm-5.2-free` was removed after its live endpoint returned HTTP 404. Ollama Cloud uses its low-usage `gpt-oss:20b` model to stretch the rolling session and weekly allowance; OpenRouter is an additional independent route but its free account allowance is much smaller. A 15-second no-progress timeout moves a slow NaraRouter call to the next route instead of leaving the user waiting. The private `hermes-ollama-bridge` translates Hermes OpenAI-wire requests to Ollama's reliable native `/api/chat` endpoint; it is not exposed on the host or through ngrok. All auxiliary tasks use `provider: auto` and inherit the same failover chain instead of being pinned to Gemini. Open WebUI also keeps its direct native Ollama connection and publishes the local model separately as `hermes-local-gpu`. Provider credentials are runtime secrets and must never be committed.

Delegated workers are pinned independently to NaraRouter `mistral-large` when
that provider is configured and inherit the same fallback chain, including the
independent Ollama Cloud and OpenRouter allowances before local GPU Qwen.
Without NaraRouter they run locally from the start. Delegation is serialized to
one child at a time to protect provider request quotas and GPU capacity; each
child has 20 iterations and a ten-minute wall-clock budget for bounded,
verifiable work.

Use `bash validate-delegation-failover.sh` after a routing change to force only
the child route to return HTTP 429, prove recovery through local Qwen, and
restore the original configuration automatically.

`hermes-admin quota` reports the live public NaraRouter plan limits and probes
the authenticated model catalog without exposing credentials. The current free
baseline is 7,000,000 tokens per day and 10 requests per minute. NaraRouter does
not expose the account's exact remaining balance through its documented API or
response headers, so Hermes reports that value as dashboard-only instead of
claiming unlimited usage. Local Qwen has no cloud quota, but remains bounded by
GPU capacity, context, and request concurrency.

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

The `Hermes VM Autostart` task opens VMware Workstation, starts `Ubuntu Mini Hermes` only when it is not already running, waits for SSH at `192.168.1.5`, and verifies the public Hermes portal. Its launcher is copied to `%LOCALAPPDATA%\HermesVMStartup`, and startup results are written to `startup.log` there. Docker and all four Hermes containers are configured to start automatically inside Ubuntu, so no Ubuntu password is stored in the Windows task.

After Ollama is reachable, configure the two supported portal connections and publish the model catalog:

```bash
OLLAMA_BASE_URL='http://192.168.1.2:11434' bash configure-openwebui-providers.sh
PORTAL_EMAIL='admin@hermes.local' PORTAL_PASSWORD='...' bash deploy-model-catalog.sh
```

Apply the routing policy and runtime hardening without putting keys in the repository:

```bash
bash configure-hermes-runtime.sh
```

The standalone command performs one controlled Hermes restart so the new
configuration is loaded. During a deployment, `hermes-ngrok-deploy.sh` applies
the profile with `HERMES_RUNTIME_SKIP_RESTART=1` before replacing the affected
services once. This avoids repeated Telegram shutdown notices and interrupted
tasks.

Published Open WebUI profiles:

- `hermes`
- `orchestrator`, `searcher`, `scraper`, `builder`, `coder`
- `reviewer`, `designer`, `consultant`, `coordinator`
- `hermes-local-gpu` through the native Ollama API

Inspect or switch an approved Hermes route without printing credentials:

```bash
docker exec hermes-agent hermes-admin status
docker exec hermes-agent hermes-admin models
docker exec hermes-agent hermes-admin use nara-mistral
docker exec hermes-agent hermes-admin use local-gpu
```

Changes selected with `hermes-admin use` apply to new sessions.

## Autonomous Runtime

`configure-hermes-runtime.sh` fixes persistent cache ownership, applies the resilient cloud/local failover policy, and installs a shell profile that exposes `hermes`, `hermes-admin`, `pip`, and `uv` to agent terminal sessions. Python packages installed with `pip` persist under `/opt/data/python-packages`.

The image includes:

- PDF text extraction with Poppler, PyMuPDF, pypdf, and pdfplumber
- DOCX and XLSX handling with python-docx and openpyxl
- PPTX creation with PptxGenJS, extraction with MarkItDown, and rendering with
  LibreOffice Impress
- Arabic and English OCR with Tesseract
- HTML parsing with Beautiful Soup and lxml
- `jq`, `file`, and the Hermes CLI on `PATH`

Runtime loop guardrails stop repeated failures, terminal and delegated work have bounded timeouts, and cron runs only one job at a time. OpenRouter requests stop after 60 seconds, silent streams stop after 45 seconds, a complete gateway request stops after five minutes, and a delegated child gets up to ten minutes. The agent policy tells Hermes to use the installed key-free DDGS `web_search` backend and `browser_snapshot` instead of looking for a nonexistent `web-search` skill.

Generated files are not considered complete until they exist, pass a
format-specific validation, and, when requested in Telegram, are delivered as
a native attachment through `send_message` with a successful tool result.

Run the bounded readiness check instead of the upstream Hermes test suite:

```bash
docker exec -u 10000 hermes-agent hermes-smoke-test
```

The terminal starts in writable `/opt/data/home`; pytest cache and temporary files stay under `/opt/data/cache/pytest` and `/opt/data/tmp`. `/opt/hermes` remains immutable. Full source and gateway integration suites are not routine health checks and should only be run as targeted, explicitly requested tests.

Gateway progress such as `iteration 1/20` means the agent completed its first tool/reasoning loop out of a maximum of 20; it is not a test counter. The smoke report exposes explicit `passed_count` and `check_count` fields. Telegram uses a recent secret-free live-health attestation when terminal security removes bot credentials from the child process.

### Gold Monitor

The daily cron script is installed at `~/.hermes/scripts/monitor_gold.py`. It reads live XAU/USD and USD/EGP JSON feeds, calculates an indicative 21K EGP price, stores an atomic history under `~/.hermes/state`, and alerts only when the configured percentage is crossed. The result excludes Egyptian dealer margin and workmanship, so it must be confirmed locally before a purchase.

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

## Agent Identity

HERMES is a general-purpose personal assistant and execution agent for research, software, automation, documents, planning, learning, communication, and analysis. Specialist knowledge is loaded only for the task that needs it. Egyptian real-estate analysis remains an available consultant capability, not the agent's primary identity or objective.

The current verified tools, model routes, skill bundles, acceptance results, and
deliberately deferred integrations are recorded in
[Capability Baseline](docs/CAPABILITY_BASELINE.md).

## Phone Access

Open WebUI is an installable Progressive Web App. Open the same ngrok URL on the phone, sign in, then:

- Android Chrome: menu, then **Install app** or **Add to Home screen**
- iPhone/iPad Safari: **Share**, then **Add to Home Screen**

Use the installed Open WebUI app for the full dashboard, long chats, files, and model selection. Use Telegram for quick requests, voice, photos, scheduled alerts, and notifications. The two interfaces complement each other; Telegram does not need to replace the portal.

Official references: [Open WebUI getting started](https://docs.openwebui.com/getting-started/) and [phone/PWA guide](https://docs.openwebui.com/ecosystem/computer/phone-and-remote/phone-app/).

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

This profile uses local `faster-whisper large-v3-turbo` with forced Arabic decoding, Egyptian Arabic context, beam search, and silence filtering for incoming voice messages. Free Edge TTS with the Egyptian female voice `ar-EG-SalmaNeural` handles outgoing Arabic speech. The Whisper model is downloaded during setup and cached under persistent Hermes data, so container recreation does not download it again. Ordinary replies stay text-only; for an explicit voice reply Hermes generates real OGG/Opus and the gateway automatically attaches every current-turn TTS result, including multiple comparison samples. This avoids relying on the model to remember a second delivery tool call. Telegram tool progress, token streaming, and interim assistant chatter are disabled to reduce Flood Control risk. Telegram photos, image documents, and static stickers are cached and sent first to NaraRouter's multimodal `mistral-medium-3-5`; direct Gemini 2.5 Flash is the automatic vision fallback when configured. OpenRouter's free multimodal Gemma route is used only when neither NaraRouter nor Gemini is available. Hermes answers this user in clear Egyptian Arabic by default.

The chat model decides which tool to call, but it does not synthesize or
transcribe the audio itself. Changing between NaraRouter Mistral and local Qwen
does not change the Edge TTS voice, local Whisper transcription, or the
separate multimodal vision route.

Override the defaults when needed:

```bash
STT_MODEL=small STT_LANGUAGE=ar TTS_VOICE=ar-EG-ShakirNeural \
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
- document/OCR dependencies, persistent Python installs, cache ownership, loop guardrails, model routing, and the live gold monitor

Evidence is written to `~/hermes_workspace/shared/outputs/`. See [Deployment Guide](docs/DEPLOYMENT_GUIDE.md) for commands, [Implementation Plan](docs/IMPLEMENTATION_PLAN.md) for the current architecture and acceptance gates, and [Capability Baseline](docs/CAPABILITY_BASELINE.md) for the last live-verified capability inventory.

## Security

- Only Open WebUI is exposed through ngrok.
- Local service ports bind to `127.0.0.1`.
- Open WebUI signup is disabled.
- ngrok browser-level auth is disabled to prevent login loops.
- Telegram and the global gateway remain deny-by-default.
- Provider keys and portal credentials stay in `.env` or persistent Hermes configuration.
- Rotate any token that has been pasted into chat or logs.

This deployment is suitable for a personal workstation VM. For wider production use, add a static domain, rate limiting, monitored backups, and an identity-aware edge policy.
