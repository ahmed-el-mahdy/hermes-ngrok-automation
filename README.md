# 🚀 Hermes Agent Automation Setup with Ngrok on Ubuntu Server

## 📘 Overview

This project sets up a complete **Hermes Agent** (LLM-powered automation) on an Ubuntu Minimal Server using **Docker Compose**. It integrates **Ngrok** tunneling and a smart **auto-update script** to maintain a working public URL for the Hermes web dashboard, while **preserving data** across updates.

**Pattern**: Identical deployment methodology to the [n8n-ngrok-automation](https://github.com/ahmed-el-mahdy/n8n-ngrok-automation) project—**same VM, different containers and ports**.

---

## 🧩 Project Structure

```
/opt/hermes
├── hermes_data/              # Persistent Hermes data & configurations
├── .env                      # Environment variables (secured, chmod 600)
├── .env.example              # Template for environment variables
├── .gitignore                # Git ignore patterns
├── docker-compose.yml        # Docker Compose configuration
├── hermes-ngrok-deploy.sh    # Main deployment & setup script
├── scripts/
│   ├── start.sh              # Start Hermes + Ngrok
│   ├── stop.sh               # Stop Hermes + Ngrok
│   ├── status.sh             # Check status of all services
│   ├── get-url.sh            # Get current Ngrok public URL
│   ├── url-watcher.sh        # Auto-update script for Ngrok URL changes
│   └── logs.sh               # View container logs
├── systemd/
│   └── hermes-url-watcher.service  # Systemd service for persistent URL monitoring
└── docs/
    ├── IMPLEMENTATION_PLAN.md       # Architecture & detailed setup guide
    ├── DEPLOYMENT_GUIDE.md          # Step-by-step deployment instructions
    └── TROUBLESHOOTING.md           # Common issues & solutions
```

---

## ⚙️ Docker Services

### 1️⃣ **Hermes Agent**
- **Container Name**: `hermes-agent`
- **Image**: `nousresearch/hermes-agent:latest`
- **Dashboard Port**: `9119` (Web GUI - tunneled via Ngrok)
- **API Port**: `8642` (OpenAI-compatible API endpoint)
- **Data Persistence**: `/opt/hermes/hermes_data/`
- **Environment**: Loaded from `.env` file

### 2️⃣ **Ngrok**
- **Container Name**: `ngrok-hermes`
- **Image**: `ngrok/ngrok:latest`
- **Command**: Tunnels port 9119 (dashboard) to the internet
- **Management API**: Port 4040 (used by URL watcher)
- **Network**: `hermes_net` (shared with Hermes container)

---

## 🔐 Environment Variables

**File**: `.env` (auto-generated during setup, chmod 600)

```bash
# Ngrok Authentication
NGROK_AUTHTOKEN=your_ngrok_auth_token_here

# Optional: Static Ngrok Domain (paid plan)
NGROK_DOMAIN=your-static-domain.ngrok-free.dev

# Hermes Configuration
HERMES_PORT=9119
HERMES_API_PORT=8642

# LLM Provider Configuration (configured after first access)
# OPENROUTER_API_KEY=your_api_key_here
# GEMINI_API_KEY=your_api_key_here
# OPENAI_API_KEY=your_api_key_here (optional)
```

> 🔒 Sensitive credentials are stored in `.env` (not committed to Git).

---

## 🔄 Persistent Data

- **`hermes_data/`** directory is mounted as a Docker volume
- Stores all Hermes configurations, models, and data files
- Safely rebuild or update containers without losing data
- Location: `/opt/hermes/hermes_data/`

---

## 🚀 Quick Start

### Prerequisites
- Ubuntu Minimal Server (20.04 LTS or newer)
- Sudo access
- Internet connection
- Ngrok account (free tier acceptable)

### Automated Deployment (Recommended)

```bash
# 1. Download the deployment script
wget https://raw.githubusercontent.com/ahmed-el-mahdy/hermes-ngrok-automation/main/hermes-ngrok-deploy.sh

# 2. Make it executable
chmod +x hermes-ngrok-deploy.sh

# 3. Run the setup
./hermes-ngrok-deploy.sh
```

The script will:
- ✅ Check prerequisites (Docker, curl, jq, python3)
- ✅ Install Docker & Docker Compose if needed
- ✅ Create directory structure (`/opt/hermes`)
- ✅ Generate `.env` with your Ngrok token
- ✅ Create `docker-compose.yml`
- ✅ Set up helper scripts
- ✅ Configure systemd service for URL watcher
- ✅ Pull container images
- ✅ Start Hermes + Ngrok
- ✅ Display your public Ngrok URL

---

## 🧰 Helper Scripts

All scripts are executable from `/opt/hermes/scripts/` or via main script:

| Script | Usage | Purpose |
|--------|-------|----------|
| `start.sh` | `./start.sh` | Start Hermes + Ngrok containers |
| `stop.sh` | `./stop.sh` | Stop all containers gracefully |
| `status.sh` | `./status.sh` | Display container & network status |
| `get-url.sh` | `./get-url.sh` | Print current public Ngrok URL |
| `logs.sh` | `./logs.sh [hermes\|ngrok]` | View container logs (real-time) |
| `url-watcher.sh` | Auto-run via systemd | Polls Ngrok API, updates on URL changes |
| `hermes-ngrok-deploy.sh --url` | Check URL anytime | Get live Ngrok tunnel URL |

---

## 🔄 URL Watcher (Auto-Update)

**File**: `/opt/hermes/scripts/url-watcher.sh`

This script runs as a **systemd service** and:

1. **Polls** `http://localhost:4040/api/tunnels` every 30 seconds
2. **Detects** URL changes (happens when ngrok restarts on free tier)
3. **Logs** every change with ISO8601 timestamp
4. **Updates** `current-url.txt` with the live URL
5. **Notifies** (optional) via Telegram webhook when URL changes

**View logs**:
```bash
sudo journalctl -u hermes-url-watcher.service -f
```

**Manual trigger**:
```bash
./scripts/url-watcher.sh
```

---

## 🌐 Accessing Hermes from the Internet

### Step 1: Get Your Public URL
```bash
./scripts/get-url.sh
# Output: https://abc123.ngrok-free.dev
```

### Step 2: Open in Browser
Visit the URL in any web browser from anywhere in the world:
```
https://abc123.ngrok-free.dev
```

### Step 3: Configure LLM Providers
After accessing the dashboard, configure your LLM provider:
- **OpenRouter** (recommended for free tier access)
- **Gemini** (Google's free tier)
- **OpenAI** (if you have API key)

---

## 📋 Co-Deployment with n8n (Same VM)

Both **n8n** and **Hermes** run on the same Ubuntu VM:

```
┌─────────────────────────────────────────────────┐
│         Ubuntu Minimal Server (VM)              │
├─────────────────────────────────────────────────┤
│  Docker Daemon                                  │
├─────────────────────────────────────────────────┤
│ n8n Stack                  Hermes Stack         │
│ ├─ n8n (port 5678)        ├─ Hermes (9119)    │
│ ├─ Nginx (80, 443)        ├─ Ngrok (4040)     │
│ └─ Ngrok (4040)           └─ URL Watcher      │
│    └─ URL Watcher              (systemd)      │
│       (systemd)                                 │
├─────────────────────────────────────────────────┤
│ Shared: Docker network, same Ngrok account     │
│ Isolated: Separate tunnels, separate data      │
└─────────────────────────────────────────────────┘
```

**Ngrok Setup for Both**:
- **n8n tunnel**: `ngrok http n8n:5678` → separate public URL
- **Hermes tunnel**: `ngrok http hermes-agent:9119` → separate public URL
- **Same auth token**: One Ngrok account, multiple tunnels allowed

---

## 🔐 Security Notes

1. **`.env` file**: Contains secrets (chmod 600) — never commit to Git
2. **Ngrok URL**: Public — anyone can access; add auth layer later if needed
3. **Hermes initial access**: No login required on first access (can add OAuth later)
4. **Firewall**: VM firewall can restrict ports; Ngrok provides encrypted tunnel
5. **Data privacy**: All Hermes data stored locally in `/opt/hermes/hermes_data/`

---

## 📦 Commands Cheat Sheet

```bash
# Deploy & Start
./hermes-ngrok-deploy.sh

# Stop all services
cd /opt/hermes && ./scripts/stop.sh

# Start services
cd /opt/hermes && ./scripts/start.sh

# Check current status
cd /opt/hermes && ./scripts/status.sh

# Get public URL
cd /opt/hermes && ./scripts/get-url.sh

# View Hermes logs
cd /opt/hermes && ./scripts/logs.sh hermes

# View Ngrok logs
cd /opt/hermes && ./scripts/logs.sh ngrok

# View URL watcher logs
sudo journalctl -u hermes-url-watcher.service -f

# Check Docker compose status
cd /opt/hermes && docker compose ps

# Restart a specific container
cd /opt/hermes && docker compose restart hermes-agent

# View ngrok tunnels via API
curl -s http://localhost:4040/api/tunnels | jq '.tunnels'

# Manually trigger URL update
cd /opt/hermes && ./scripts/url-watcher.sh
```

---

## 📚 Documentation

1. **[IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)** — Architecture, deployment strategy, and design decisions
2. **[DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md)** — Step-by-step deployment instructions with screenshots
3. **[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** — Common issues, debugging, and solutions

---

## 🔗 Architecture Comparison

| Component | n8n Project | Hermes Project | Notes |
|-----------|-----------|---|---|
| Container | n8nio/n8n:latest | nousresearch/hermes-agent:latest | Different LLM platforms |
| Main Port | 5678 | 9119 (Dashboard) | Different dashboard ports |
| API Port | Internal API | 8642 (OpenAI-compatible) | Hermes has external API |
| Ngrok Tunnel | Port 5678 → Public | Port 9119 → Public | Same pattern, different targets |
| Data Volume | `/opt/n8n/n8n_data/` | `/opt/hermes/hermes_data/` | Both persistent |
| URL Watcher | Restarts n8n container | Logs URL only (no restart needed) | Different injection models |
| Network | n8n_net | hermes_net | Isolated networks |

---

## 🕒 Development Timeline

| Phase | Status | Description |
|-------|--------|-------------|
| Architecture Design | ✅ Complete | Modeled after n8n-ngrok-automation |
| Docker Setup | ✅ Complete | docker-compose.yml configured |
| Deployment Script | ✅ Complete | Automated setup & initialization |
| Helper Scripts | ✅ Complete | start, stop, status, get-url, logs |
| URL Watcher | ✅ Complete | Auto-detect changes, log updates |
| Systemd Integration | ✅ Complete | URL watcher runs as service |
| Documentation | ✅ Complete | Implementation, deployment, troubleshooting |

---

## 🌍 Author & Support

**Project**: Hermes Agent + Ngrok Automation  
**Inspired by**: [n8n-ngrok-automation](https://github.com/ahmed-el-mahdy/n8n-ngrok-automation)  
**Created by**: Ahmed El-Mahdy  
**Role**: Senior System Admin | DevOps Engineer  

For issues, questions, or improvements:
1. Check [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
2. Review logs: `journalctl -u hermes-url-watcher.service -f`
3. Test manually: `./scripts/get-url.sh`
4. Open a GitHub Issue with logs attached

---

## 📄 License

This project is licensed under the same terms as the original n8n-ngrok-automation project.

---

## 🚀 Next Steps After Deployment

1. ✅ Run deployment script → Get public URL
2. ✅ Access Hermes dashboard via public URL
3. ✅ Configure LLM provider (OpenRouter or Gemini)
4. ✅ Test dashboard functionality
5. ⚠️ (Optional) Add password/OAuth authentication
6. ⚠️ (Optional) Configure Telegram notifications for URL changes
7. ⚠️ (Optional) Set up custom domain (paid Ngrok plan)

---

**Status**: Production-ready | Tested on Ubuntu 20.04 LTS