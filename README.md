# 🚀 Hermes Agent Automation with Ngrok Tunneling on Ubuntu Server

> **Deploy Hermes Agent on your Ubuntu VM and make it accessible from anywhere on the internet using ngrok**

## 📘 Quick Overview

This project automates the deployment of **Hermes Agent** (NousResearch's LLM orchestration platform) on an Ubuntu Minimal Server with **ngrok** tunneling, following the proven pattern from [n8n-ngrok-automation](https://github.com/ahmed-el-mahdy/n8n-ngrok-automation).

**What you get:**
- **Open WebUI** accessible globally via HTTPS and prewired to Hermes Agent
- **Hermes Agent** dashboard/API kept internal behind Open WebUI
- 🔐 **ngrok Basic Auth** protection (auto-generated password)
- 🔄 **URL Watcher** systemd service (tracks ngrok URL changes automatically)
- 💾 **Persistent data** across container restarts and updates
- ⚡ **Fully automated** deployment (one command, 5 minutes)
- 🧠 **LLM-ready** for OpenRouter, Gemini, or any OpenAI-compatible API

---

## ⚡ 5-Minute Quick Start

### Step 1: Prerequisites Check

**On your Ubuntu machine:**

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Check you have internet and ~20GB free disk space for Docker images/data
df -h
free -h

# Verify basic tools exist
which curl wget git
```

### Step 2: Get ngrok Auth Token

1. **Create free ngrok account:** https://ngrok.com/signup
2. **Get your auth token:** https://dashboard.ngrok.com/get-started/your-authtoken
3. **Copy the token** (looks like: `2bPxx_1Bq1234567890abcdefghijklmnopqrst`)

### Step 3: Deploy (One Command)

```bash
# Download the deployment script
wget https://raw.githubusercontent.com/ahmed-el-mahdy/hermes-ngrok-automation/main/hermes-ngrok-deploy.sh

# Make it executable
chmod +x hermes-ngrok-deploy.sh

# Run the deployment
./hermes-ngrok-deploy.sh
```

**When prompted:**
- Paste your ngrok auth token
- Press ENTER
- Wait 3-5 minutes (script handles everything automatically)

### Step 4: Access Open WebUI

When deployment finishes, you'll see:

```
╔══════════════════════════════════════════════════════════╗
║          HERMES AGENT — DEPLOYMENT COMPLETE              ║
╠══════════════════════════════════════════════════════════╣
║  🌐  URL:       https://xyz123.ngrok-free.dev           ║
║  🔑  Username:  hermes                                   ║
║  🔑  Password:  a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6        ║
║                                                          ║
║  Credentials saved to: ~/hermes-ngrok/credentials.txt   ║
╚══════════════════════════════════════════════════════════╝
```

1. **Open the URL** in your browser (from anywhere in the world!)
2. **Enter credentials** when prompted (ngrok basic auth popup)
3. **Open WebUI appears** ✅

---

## 📋 What Gets Deployed

### Deployment Locations

```
Ubuntu Home Directory (~)
├── hermes-ngrok/                      # Project root
│   ├── .env                           # Configuration (chmod 600, secrets)
│   ├── docker-compose.yml             # Container orchestration
│   ├── current-url.txt                # Current ngrok public URL
│   ├── credentials.txt                # Dashboard credentials
│   ├── logs/                          # Application logs
│   │   └── url-watcher.log           # URL change history
│   └── scripts/                       # Helper scripts
│       ├── start.sh                  # Start all services
│       ├── stop.sh                   # Stop all services
│       ├── restart.sh                # Restart (data preserved)
│       ├── status.sh                 # Check service status
│       ├── get-url.sh                # Print current public URL
│       ├── logs.sh                   # View container logs
│       ├── update.sh                 # Update Hermes image
│       ├── setup-wizard.sh           # Interactive setup
│       └── url-watcher.sh            # URL tracking service
│
└── .hermes/                           # Persistent Hermes data
    ├── config.yaml                   # Hermes configuration
    ├── models/                       # Downloaded models
    ├── memory/                       # Chat history & sessions
    └── (other data)
```

### Docker Containers

| Container | Port | Role |
|-----------|------|------|
| **hermes-agent** | 9119 (dashboard), 8642 (API) | LLM orchestration engine, internal backend |
| **hermes-open-webui** | 3000 -> 8080 | Prebuilt Open WebUI chat dashboard |
| **hermes-ngrok** | 4040 (mgmt API) | HTTPS tunnel to Open WebUI |

### Systemd Service

- **Service Name:** `hermes-url-watcher`
- **Purpose:** Polls ngrok API, detects URL changes, logs them
- **Auto-starts:** On VM boot
- **Status:** `sudo systemctl status hermes-url-watcher`

---

## 🔧 What the Deployment Script Does

The `hermes-ngrok-deploy.sh` script automates 10 steps:

### ✅ Step 1: Check Prerequisites
- Detects OS (Ubuntu 20.04 LTS+)
- Checks for Docker, Python3, curl, jq, netcat, openssl
- Installs missing dependencies via apt

### ✅ Step 2: Install Docker (if needed)
- Installs Docker Engine + Compose v2
- Adds current user to `docker` group
- Starts Docker daemon
- (May require running `newgrp docker` after)

### ✅ Step 3: Collect Configuration
- **Prompts you for:** ngrok Auth Token
- **Auto-generates:** Dashboard password (24-char hex)
- **Auto-generates:** API server key (48-char hex)
- **Saves to:** `credentials.txt` (chmod 600)

### ✅ Step 4: Create Directory Structure
```
~/hermes-ngrok/          # Project root
~/.hermes/               # Persistent data (chmod 700)
~/hermes-ngrok/scripts/  # Helper scripts
~/hermes-ngrok/logs/     # Log files
```

### ✅ Step 5: Generate Configuration Files
- **`.env`** — Environment variables (chmod 600, not in Git)
- **`docker-compose.yml`** — Three-container setup: Hermes, Open WebUI, ngrok
- **`.gitignore`** — Prevents secret commits
- **`credentials.txt`** — Dashboard login info (chmod 600)

### ✅ Step 6: Generate Helper Scripts
Creates executable scripts in `~/hermes-ngrok/scripts/`:
- `start.sh`, `stop.sh`, `restart.sh`
- `status.sh`, `get-url.sh`, `logs.sh`
- `update.sh`, `setup-wizard.sh`
- `url-watcher.sh`

### ✅ Step 7: Create URL Watcher Script
- Polls `http://localhost:4040/api/tunnels` every 30 seconds
- Detects URL changes (free ngrok changes on restart)
- Logs changes with timestamps
- Updates `current-url.txt`

### ✅ Step 8: Install systemd Service
- Registers `hermes-url-watcher.service`
- Auto-starts on VM boot
- Restarts on failure
- Logs to systemd journal

### ✅ Step 9: Pull Docker Images
- Downloads `nousresearch/hermes-agent:latest`
- Downloads `ghcr.io/open-webui/open-webui:main`
- Downloads `ngrok/ngrok:latest`
- (Takes 2-5 minutes depending on internet)

### ✅ Step 10: Start Services
- Runs `docker compose up -d`
- Waits for containers to respond
- Starts URL watcher service
- Displays final access information

---

## 🎮 Daily Operations

### Get Current Public URL

**Free ngrok plan = random URL on each restart**

```bash
# Fastest way
bash ~/hermes-ngrok/scripts/get-url.sh

# Or read the file directly
cat ~/hermes-ngrok/current-url.txt

# Or check the logs
tail ~/hermes-ngrok/logs/url-watcher.log
```

### Check Service Status

```bash
bash ~/hermes-ngrok/scripts/status.sh
```

Shows:
- Container status (running/stopped)
- Current ngrok URL
- URL watcher service status
- Last 25 lines of Hermes logs

### Stop All Services (Data Preserved)

```bash
bash ~/hermes-ngrok/scripts/stop.sh
```

Your Hermes data remains in `~/.hermes/`. Start again anytime with `start.sh`.

### Restart Services

```bash
bash ~/hermes-ngrok/scripts/restart.sh
```

Useful after changing LLM API keys in `.env`.

### View Real-Time Logs

```bash
# All containers
docker compose -f ~/hermes-ngrok/docker-compose.yml logs -f

# Just Hermes
docker logs -f hermes-agent

# Just ngrok
docker logs -f hermes-ngrok

# URL watcher service
sudo journalctl -u hermes-url-watcher.service -f
```

---

## 🧠 Configure LLM Provider

### Option A: Via Web Portal (Recommended)

1. **Get Free API Key:**
   - **OpenRouter:** https://openrouter.ai/keys (recommended, free credits)
   - **Gemini:** https://aistudio.google.com/app/apikey (free tier)
   - **OpenAI:** https://platform.openai.com/api-keys (paid)

2. **Access Open WebUI:**
   - Open the ngrok URL from deployment output
   - Log in: `hermes` / (password from credentials.txt)

3. **Add API Key:**
   - Navigate to **Settings** → **API Keys**
   - Paste your API key
   - Save

4. **Test:**
   - Select a model from dropdown
   - Type a message
   - Submit

### Option B: Via Environment File

1. **Edit `.env`:**
   ```bash
   nano ~/hermes-ngrok/.env
   ```

2. **Add API key:**
   ```bash
   # Find this section and uncomment:
   OPENROUTER_API_KEY=sk-or-v1-xxxxx
   ```

3. **Restart:**
   ```bash
   bash ~/hermes-ngrok/scripts/restart.sh
   ```

4. **Verify:** Refresh browser, test a prompt

---

## 📂 File Structure Explained

| File/Directory | Purpose | Committed to Git? |
|---|---|---|
| `.env` | Secrets (ngrok token, API keys) | ❌ No (chmod 600) |
| `credentials.txt` | Dashboard login info | ❌ No (chmod 600) |
| `.env.example` | Template for `.env` | ✅ Yes |
| `docker-compose.yml` | Container config | ✅ Yes |
| `hermes-ngrok-deploy.sh` | Main deployment script | ✅ Yes |
| `scripts/` | Helper bash scripts | ✅ Yes |
| `docs/` | Implementation, deployment, troubleshooting | ✅ Yes |
| `.gitignore` | Prevents secret commits | ✅ Yes |
| `README.md` | This file | ✅ Yes |
| `~/.hermes/` | **All Hermes data** (config, models, memory) | ❌ No (local) |

---

## 🔐 Security Model

### Layers of Protection

```
Internet User
    ↓
ngrok HTTPS/TLS encryption
    ↓
ngrok Basic Auth Challenge (username + 24-char password)
    ↓
Open WebUI (public dashboard)
    ↓
Hermes API (internal OpenAI-compatible backend)
    ↓
Access to LLM features, chat history, configurations
```

### Why This is Secure

1. **External Gate:** ngrok's basic auth requires username + password
2. **Transport Security:** HTTPS/TLS encryption (ngrok terminates)
3. **Strong Credentials:** 24-character hex password (96 bits entropy)
4. **Local Data:** All Hermes data stays on your Ubuntu VM
5. **Secrets Not in Git:** `.env` and `credentials.txt` ignored

### What's NOT Protected Yet (Optional Additions)

- No rate limiting on login attempts (ngrok handles this)
- No 2FA (can add later via Hermes OAuth)
- No reverse proxy (Nginx optional)
- Public ngrok URL can be enumerated (free tier limitation)

**Recommendation:** This setup is secure for personal/internal use. For production internet-facing deployments:
- Upgrade to paid ngrok (static domain, IP allowlist)
- Add Hermes OAuth
- Add reverse proxy (Nginx) with rate limiting

---

## 🆘 Troubleshooting

### "Port 9119 is already in use"

```bash
# Find what's using it
sudo lsof -i :9119

# Kill the process
sudo kill -9 <PID>

# Or stop & restart
bash ~/hermes-ngrok/scripts/stop.sh
sleep 3
bash ~/hermes-ngrok/scripts/start.sh
```

### "Docker daemon is not running"

```bash
sudo systemctl start docker
sudo systemctl status docker
```

### "ngrok tunnel not establishing"

```bash
# Check ngrok logs
docker logs hermes-ngrok | tail -20

# Verify auth token is correct
grep NGROK_AUTHTOKEN ~/hermes-ngrok/.env
```

### "Can't log in to dashboard"

```bash
# Get credentials
cat ~/hermes-ngrok/credentials.txt

# Or re-run get-url script
bash ~/hermes-ngrok/scripts/get-url.sh

# Username is always: hermes
```

### "Dashboard is slow / API hanging"

```bash
# Check resources
free -h  # RAM
df -h    # Disk
top      # CPU

# Check if API key is configured
grep -E '^(OPENROUTER|GOOGLE|OPENAI)' ~/hermes-ngrok/.env | head -3
```

**For more help:** See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) (when created)

---

## 📚 Documentation

1. **[IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)**
   - Architecture overview
   - Security model
   - Component design
   - LLM integration strategy

2. **[DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md)**
   - Step-by-step walkthrough
   - Screenshots & examples
   - Configuration methods
   - Daily operations

3. **[.env.example](.env.example)**
   - Complete configuration template
   - All available options
   - Comments explaining each setting

---

## 🎯 Key Commands Reference

```bash
# ═══════════════════════════════════════════════════════════
# DEPLOYMENT & SETUP
# ═══════════════════════════════════════════════════════════
wget https://raw.githubusercontent.com/ahmed-el-mahdy/hermes-ngrok-automation/main/hermes-ngrok-deploy.sh
chmod +x hermes-ngrok-deploy.sh
./hermes-ngrok-deploy.sh

# ═══════════════════════════════════════════════════════════
# SERVICE CONTROL
# ═══════════════════════════════════════════════════════════
bash ~/hermes-ngrok/scripts/start.sh      # Start all services
bash ~/hermes-ngrok/scripts/stop.sh       # Stop all services
bash ~/hermes-ngrok/scripts/restart.sh    # Restart (data preserved)
bash ~/hermes-ngrok/scripts/status.sh     # Full status report

# ═══════════════════════════════════════════════════════════
# ACCESS & CONNECTIVITY
# ═══════════════════════════════════════════════════════════
bash ~/hermes-ngrok/scripts/get-url.sh         # Get current public URL
cat ~/hermes-ngrok/current-url.txt             # Read URL from file
cat ~/hermes-ngrok/credentials.txt             # View login credentials

# ═══════════════════════════════════════════════════════════
# MONITORING & DEBUGGING
# ═══════════════════════════════════════════════════════════
bash ~/hermes-ngrok/scripts/logs.sh hermes     # View Hermes logs
bash ~/hermes-ngrok/scripts/logs.sh ngrok      # View ngrok logs
docker compose -f ~/hermes-ngrok/docker-compose.yml ps   # Container status
sudo journalctl -u hermes-url-watcher.service -f         # URL watcher logs

# ═══════════════════════════════════════════════════════════
# MAINTENANCE & UPDATES
# ═══════════════════════════════════════════════════════════
bash ~/hermes-ngrok/scripts/update.sh                     # Update Hermes image
bash ~/hermes-ngrok/scripts/setup-wizard.sh               # Interactive setup
cd ~/hermes-ngrok && docker compose ps                    # Raw docker status

# ═══════════════════════════════════════════════════════════
# BACKUP & RESTORE
# ═══════════════════════════════════════════════════════════
tar czf ~/hermes-backup-$(date +%s).tar.gz ~/.hermes/     # Backup data
cd ~ && tar xzf hermes-backup-XXXX.tar.gz                # Restore data
bash ~/hermes-ngrok/scripts/restart.sh                    # Restart after restore

# ═══════════════════════════════════════════════════════════
# UNINSTALL (preserves ~/.hermes data)
# ═══════════════════════════════════════════════════════════
./hermes-ngrok-deploy.sh --uninstall
```

---

## 🌐 Accessing from Different Devices

**Hermes is accessible from:**
- ✅ Your Ubuntu VM (localhost:3000)
- ✅ Same network as VM through the chosen local bind policy
- ✅ **Anywhere on the internet** (ngrok public URL to Open WebUI)
- ✅ Mobile phones, tablets, other computers
- ✅ Different countries/regions

**Just use the ngrok URL:**
```
https://your-random-url.ngrok-free.dev
```

### Backup Your Data

```bash
# Create timestamped backup
tar czf ~/hermes-backup-$(date +%Y%m%d-%H%M%S).tar.gz ~/.hermes/

# Restore from backup
cd ~ && tar xzf hermes-backup-20260602-150000.tar.gz
bash ~/hermes-ngrok/scripts/restart.sh
```

### Uninstall (Keep Data)

```bash
# Remove containers & project files, but keep ~/.hermes/
./hermes-ngrok-deploy.sh --uninstall

# Your data is preserved! Can reinstall anytime
```

---

## 🏗️ Architecture Overview

Current public route:

```text
Internet browser
  -> ngrok HTTPS + Basic Auth
  -> hermes-open-webui:8080
  -> OpenAI-compatible backend
  -> hermes-agent:8642/v1

Native Hermes dashboard:
  hermes-agent:9119 (internal/local only, not the ngrok target)
```


---

## 🎓 Learning Resources

- **Hermes Agent:** https://github.com/NousResearch/Hermes
- **ngrok Documentation:** https://ngrok.com/docs/
- **Docker Compose:** https://docs.docker.com/compose/
- **OpenRouter API:** https://openrouter.ai/docs
- **Google Gemini API:** https://ai.google.dev/

---

## ✅ Deployment Checklist

Before you start:

- [ ] Ubuntu 20.04 LTS or newer
- [ ] ~20 GB free disk space for Docker images and app data
- [ ] Internet connection
- [ ] Sudo access
- [ ] ngrok account created (free at https://ngrok.com/signup)
- [ ] ngrok auth token copied

After deployment:

- [ ] Public URL accessible from browser
- [ ] Can log in with hermes / password
- [ ] Open WebUI loads
- [ ] LLM provider API key obtained
- [ ] API key added via portal or .env
- [ ] Chat message sends successfully
- [ ] ~/hermes-ngrok/ directory exists with scripts
- [ ] ~/.hermes/ directory exists with Hermes data
- [ ] systemd service is running: `sudo systemctl status hermes-url-watcher`

---

## 🚀 Next Steps

1. **Deploy:** Run the one-command deployment script
2. **Access:** Open the ngrok URL in your browser
3. **Authenticate:** Use username/password from credentials.txt
4. **Configure LLM:** Get a free API key (OpenRouter or Gemini)
5. **Test:** Send a chat message through Hermes
6. **Explore:** Check settings, configure models, test API endpoints

---

## 📞 Support & Issues

If something doesn't work:

1. **Check the logs:**
   ```bash
   bash ~/hermes-ngrok/scripts/status.sh
   docker logs hermes-agent
   docker logs hermes-ngrok
   ```

2. **Verify configuration:**
   ```bash
   cat ~/hermes-ngrok/.env
   cat ~/hermes-ngrok/credentials.txt
   ```

3. **Test connectivity:**
   ```bash
   bash ~/hermes-ngrok/scripts/get-url.sh
   curl -s http://localhost:4040/api/tunnels | jq
   ```

4. **Open a GitHub Issue:**
   - Include error messages from logs
   - Include OS and Docker versions
   - Include output of `df -h` and `free -h`

---

## 📊 Specifications

| Item | Specification |
|------|---|
| **OS Support** | Ubuntu 20.04 LTS+ (minimal install OK) |
| **RAM Required** | 1 GB minimum (2 GB recommended) |
| **Disk Required** | 20 GB free recommended for Hermes, Open WebUI, and Docker data |
| **Deployment Time** | 3-5 minutes (depending on internet) |
| **Open WebUI** | Port 3000 locally, HTTPS via ngrok |
| **Hermes API** | Port 8642 (OpenAI-compatible) |
| **ngrok URL Type** | HTTPS encrypted (http://s to browser) |
| **Auth Method** | ngrok Basic Auth (auto-generated password) |
| **Data Persistence** | ~/.hermes/ (Docker volume) |
| **Network Mode** | NAT (no port forwarding needed) |
| **Cost** | Free (ngrok free tier) |

---

## 📄 License

This project is licensed under the same terms as the original [n8n-ngrok-automation](https://github.com/ahmed-el-mahdy/n8n-ngrok-automation) project.

---

## 🙏 Credits

**Inspired by:** [n8n-ngrok-automation](https://github.com/ahmed-el-mahdy/n8n-ngrok-automation)  
**Created by:** Ahmed El-Mahdy (Senior DevOps Engineer)  
**Project:** Hermes Agent + Ngrok Automation  

**Key Technologies:**
- 🤖 [Hermes Agent](https://github.com/NousResearch/Hermes) by NousResearch
- 🌐 [ngrok](https://ngrok.com) for HTTPS tunneling
- 🐳 [Docker](https://docker.com) for containerization
- 🔄 [Docker Compose](https://docs.docker.com/compose/) for orchestration
- 🐧 [Ubuntu](https://ubuntu.com) as base OS

---

**Status:** ✅ **Production Ready**  
**Last Updated:** 2026-06-02  
**Version:** 1.0
