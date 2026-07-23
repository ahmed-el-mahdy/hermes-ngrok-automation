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
bash configure-openwebui-providers.sh
bash deploy-model-catalog.sh
bash deploy-prompt-library.sh
bash validate-model-catalog.sh
```

Each deployment wrapper creates a timestamped database backup under `~/hermes-backups`.

## Model Routing

Cloud routing is stored in `~/.hermes/config.yaml` and provider secrets remain in the Compose environment or persistent Hermes environment. Run `bash configure-hermes-runtime.sh` after adding provider keys. The automatic order is NaraRouter Mistral, local GPU Qwen, NaraRouter GLM, OpenRouter Nemotron, OpenRouter's free router, and Gemini 2.5 Flash. The local route is deliberately second so exhausted cloud quotas cannot stop the task.

`hermes-ollama-bridge` is private to the Compose network. It converts Hermes'
OpenAI-compatible requests to Ollama's native `/api/chat`, including streaming
and tool calls. All auxiliary tasks use `provider: auto`, so they inherit this
same chain instead of being pinned to Gemini. NaraRouter has a 15-second
no-progress timeout; a healthy streaming response may continue normally, while a
silent or queued request moves to local Qwen.

Validate each provider independently before adding it to the fallback chain. Interpret common responses as follows:

| HTTP status | Meaning |
| --- | --- |
| 200 | Route works |
| 401 | Invalid or malformed credential |
| 402 | Provider credit required |
| 404 | Model ID or endpoint does not exist |
| 429 | Quota or rate limit reached |

Do not publish a preset for a route that does not return a successful chat completion.

Use `docker exec hermes-agent hermes-admin status` to inspect routing and `hermes-admin models` to list approved aliases without displaying credentials.

## Runtime Tooling

The custom Hermes image includes Poppler, Tesseract Arabic OCR, PyMuPDF, pypdf, pdfplumber, python-docx, openpyxl, Beautiful Soup, lxml, `jq`, and `file`. Runtime setup fixes the persistent uv/Hugging Face cache ownership and provides a user-writable persistent Python package target.

```bash
bash configure-hermes-runtime.sh
docker exec -u 10000 hermes-agent sh -lc \
  '. /opt/data/home/.hermes_env; hermes-admin status; pip --version'
```

The runtime profile also enables repeated-failure hard stops, limits OpenRouter requests to 60 seconds and silent streams to 45 seconds, limits the complete gateway request to five minutes, serializes cron jobs, installs the key-free DDGS search backend, and documents the correct direct web-tool names for the agent.

Use the bounded smoke test for routine readiness:

```bash
docker exec -u 10000 hermes-agent hermes-smoke-test
docker exec -u 10000 hermes-agent validate-model-routes
```

After routing changes, run the controlled recovery test once:

```bash
bash validate-automatic-failover.sh
```

It temporarily makes the primary route return HTTP 429, proves that the same
request completes through local Qwen, and restores the original configuration
even when the test exits early.

Do not change ownership of `/opt/hermes` or run the complete upstream test suite as a health check. The agent terminal starts in `/opt/data/home`, with pytest cache at `/opt/data/cache/pytest` and temporary test output at `/opt/data/tmp`. When a source regression test is explicitly required, run only the relevant file with `timeout`, `--basetemp=/opt/data/tmp/pytest`, and `-o cache_dir=/opt/data/cache/pytest`.

`iteration X/Y` is the agent loop count, not the number of tests. Read `passed_count/check_count` from the smoke output. Telegram status falls back to a recent secret-free live-health record when terminal secret scrubbing removes the bot token from the test process.

The gold monitor lives at `~/.hermes/scripts/monitor_gold.py`; cron must reference only `monitor_gold.py`, not an absolute path. Its 21K value is an indicative global spot conversion and excludes dealer margins and workmanship.

## Local Ollama Model

The Windows Ollama listener must be reachable only from the trusted LAN/VM network. From the VM:

```bash
curl -fsS http://WINDOWS_LAN_IP:11434/api/tags
```

Confirm the requested model is loaded and inspect `ollama ps` on Windows. Configure Open WebUI with `configure-openwebui-providers.sh`, then select `HERMES LOCAL GPU` in the portal. Open WebUI uses native `/api/chat` directly; Hermes reaches the same native endpoint through the private compatibility bridge when automatic fallback is needed.

For persistent startup, run `windows/Install-HermesOllamaTask.ps1` from elevated PowerShell. It installs the `Hermes Ollama Service` startup task and limits inbound port `11434` to the VM address. Validate from the VM with `/api/tags`, `/api/chat`, and `/api/ps`; the last check must report `size_vram` equal to `size` for `qwen3-4b-gpu:latest`.

Use `windows/Test-HermesOllamaRecovery.ps1` for a controlled failure test. It terminates the serving process once and passes only when Task Scheduler starts a new process and reloads the complete model into VRAM.

## Windows VM Startup

Run `windows/Install-HermesVMTask.ps1` from the Windows repository checkout. It registers `Hermes VM Autostart` for the current interactive user at logon, copies the launcher to `%LOCALAPPDATA%\HermesVMStartup`, opens VMware Workstation, and starts `E:\VM\Ubuntu Mini Serv2\Clone of Ubuntu 64-bit.vmx` only when needed.

The launcher waits for SSH at `192.168.1.5` and then for the public portal. Failures are retried by Task Scheduler and logged to `%LOCALAPPDATA%\HermesVMStartup\startup.log`. The VM must retain bridged networking and its reserved address. Inside Ubuntu, Docker and `open-vm-tools` must be enabled, while the three Compose services must keep `restart: unless-stopped`.

Inspect the task after installation:

```powershell
Get-ScheduledTask -TaskName "Hermes VM Autostart"
Get-ScheduledTaskInfo -TaskName "Hermes VM Autostart"
Get-Content "$env:LOCALAPPDATA\HermesVMStartup\startup.log" -Tail 30
```

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

### Telegram Media

Run `bash configure-telegram-media.sh` to enable the persistent media profile. It builds `Dockerfile.hermes-agent` with Hermes' pinned `faster-whisper` dependencies and a guarded STT tuning patch, configures forced-Arabic transcription with Egyptian context and silence filtering, selects an Egyptian Arabic Edge TTS voice, keeps automatic TTS disabled, and adds instructions for Egyptian Arabic conversation and on-demand audio replies.

The default `large-v3-turbo` model was selected from a real Egyptian Telegram sample: it preserved the Egyptian wording while transcribing in 16.4 seconds, compared with 21.8 seconds for `medium`; `small` was faster but misheard important words. Setup prefetches the selected model into `/opt/data/cache/huggingface`. Set `STT_MODEL=small` only when lower latency matters more than transcription accuracy.

Validation should cover all three paths:

```text
Telegram voice -> cached OGG -> local Whisper -> agent response
Telegram photo -> cached image -> Gemini vision -> agent response
Explicit voice request -> Edge TTS -> OGG/Opus -> Telegram voice note
```

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

## Phone Access

Open WebUI is a Progressive Web App, so the ngrok portal can be installed directly from the phone browser. Use Chrome's **Install app** on Android or Safari's **Share > Add to Home Screen** on iPhone/iPad. Use Open WebUI for full dashboard work and Telegram for quick voice/photo requests and notifications.

See the official [Open WebUI phone guide](https://docs.openwebui.com/ecosystem/computer/phone-and-remote/phone-app/).

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

Check all four containers and confirm ngrok targets `open-webui:8080` on the shared Compose network.

### Open WebUI login loops

Remove ngrok Basic Auth/OAuth, use the Open WebUI email login, and clear cached browser credentials.

### Agent does not answer

Inspect `hermes-agent` logs, run `hermes-admin status`, verify its authenticated `/v1/models` endpoint, test the primary provider, then test each fallback independently. A repeated `429` means quota exhaustion; do not keep retrying the same provider.

### Agent repeats commands or appears stuck

Confirm `tool_loop_guardrails.hard_stop_enabled` is true and rerun `configure-hermes-runtime.sh`. Every external operation should have a timeout; after two identical failures Hermes is instructed to change approach instead of repeating the command.

### Node execution fails

Rebuild `hermes-open-webui:local` from `Dockerfile.open-webui`; the stock image does not guarantee a Node runtime.

### Workspace permission error

Confirm the host path is mounted at `/app/backend/data/hermes_workspace`. Keep normal artifacts user-writable and avoid using container-root-owned test folders for host-side writes.
