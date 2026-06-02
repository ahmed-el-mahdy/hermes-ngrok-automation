# 🚀 DEPLOYMENT GUIDE — Hermes Agent + Ngrok Automation

## Quick Start (5 minutes)

### Prerequisites
- Ubuntu 20.04 LTS or newer (minimal install OK)
- ~2 GB free disk space
- ngrok account (free tier at https://ngrok.com/)
- Internet connection
- Optional: OpenRouter or Gemini API key (can add later)

### Step 1: Get Ngrok Token

1. Go to https://dashboard.ngrok.com/get-started/your-authtoken
2. Copy your **Auth Token** (looks like: `2bPxx_1Bxxxxxx`)
3. Keep it handy — you'll need it during deployment

### Step 2: Download & Run Deploy Script

```bash
# Download the script
wget https://raw.githubusercontent.com/ahmed-el-mahdy/hermes-ngrok-automation/main/hermes-ngrok-deploy.sh

# Make it executable
chmod +x hermes-ngrok-deploy.sh

# Run the deployment
./hermes-ngrok-deploy.sh
```

### Step 3: Follow Interactive Prompts

The script will ask:

1. **"Enter your ngrok Auth Token"**
   - Paste the token you copied above
   - Press ENTER

2. **The script will auto-generate:**
   - Dashboard username: `hermes`
   - Dashboard password: 24-character hex string (saved to credentials.txt)
   - API server key: auto-generated

3. **Sit back and relax!**
   - The script handles:
     - Docker installation (if needed)
     - Directory setup
     - Configuration generation
     - Container pulls
     - Service startup
     - URL watcher setup
   - Total time: ~3-5 minutes (depends on internet speed)

### Step 4: Access Hermes Dashboard

When deployment completes, you'll see:

```
╔══════════════════════════════════════════════════════════════╗
║              HERMES AGENT — DEPLOYMENT COMPLETE               ║
╚══════════════════════════════════════════════════════════════╝

  ┌─  DASHBOARD ACCESS  ───────────────────────────────────────┐
  │  🌐  URL:       https://abc123.ngrok-free.dev
  │  🔑  Username:  hermes
  │  🔑  Password:  a1b2c3d4e5f6g7h8i9j0k1l2
  │
  │  Credentials saved to: ~/hermes-ngrok/credentials.txt
  └────────────────────────────────────────────────────────────
```

**Open the URL in your browser:**
- Browser will show a login prompt (ngrok's basic auth)
- Enter username: `hermes`
- Enter password: (from above or from `credentials.txt`)
- Press **Authenticate**
- **Hermes Dashboard** opens!

---

## Full Deployment Walkthrough

### Phase 1: Prerequisites (5 min)

#### 1.1 VM Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install minimal essentials (if not already present)
sudo apt install -y curl wget git

# Check available disk space
df -h
# Need at least 2 GB free in root partition
```

#### 1.2 Get Ngrok Token

1. Create free account: https://ngrok.com/signup
2. Go to Auth Token: https://dashboard.ngrok.com/get-started/your-authtoken
3. Copy the token (save in password manager for later reference)

**Your token looks like:**
```
2bPxx_1Bq1234567890abcdefghijklmnopqrst
```

### Phase 2: Deployment (5-10 min)

#### 2.1 Download Script

```bash
# Create a working directory (optional, but clean)
mkdir -p ~/deployment
cd ~/deployment

# Download the deployment script
wget https://raw.githubusercontent.com/ahmed-el-mahdy/hermes-ngrok-automation/main/hermes-ngrok-deploy.sh

# Verify it downloaded
ls -lh hermes-ngrok-deploy.sh
```

#### 2.2 Make Script Executable

```bash
chmod +x hermes-ngrok-deploy.sh

# Verify permissions
ls -l hermes-ngrok-deploy.sh
# Should show: -rwxr-xr-x (executable)
```

#### 2.3 Run the Deployment

```bash
./hermes-ngrok-deploy.sh
```

**What you'll see:**

1. **Banner** (ASCII art with project info)
2. **Step 1: Checking Prerequisites** (2 sec)
   ```
   [INFO]  OS: Ubuntu 20.04.3 LTS
   [  OK ] Docker $(version)
   [  OK ] curl found
   ...
   ```

3. **Step 2: Docker Installation** (if needed, ~1 min)
   ```
   [INFO] Installing Docker Engine...
   [  OK ] Docker Engine installed and started
   ```

4. **Step 3: Configuration** (interactive)
   ```
   ━━━  Step 3/10 — Configuration  ━━━
   
     ngrok Auth Token
     Get yours free → https://dashboard.ngrok.com/...
   
     Enter your ngrok Auth Token: 2bPxx_1Bq1234567890abcdef...
   ```
   - Paste your token here
   - Press ENTER

5. **Steps 4-10: Automated** (3-5 min)
   - Directories created
   - Config files generated
   - Docker images pulled (~1-2 GB download)
   - Containers started
   - Services registered

#### 2.4 Monitor Progress

The script outputs progress for each step. If it gets stuck:

```bash
# In another terminal, check Docker
docker ps

# Check system resources
free -h  # RAM usage
df -h    # Disk usage
```

#### 2.5 Success Output

When done, you'll see:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

╔══════════════════════════════════════════════════════════════╗
║              HERMES AGENT — DEPLOYMENT COMPLETE               ║
╚══════════════════════════════════════════════════════════════╝

  ┌─  DASHBOARD ACCESS  ───────────────────────────────────────┐
  │  🌐  URL:       https://xyz789.ngrok-free.dev
  │  🔑  Username:  hermes
  │  🔑  Password:  (24-char hex password)
  │
  │  Credentials saved to: ~/hermes-ngrok/credentials.txt
  └────────────────────────────────────────────────────────────

  ┌─  LLM API KEYS (configure after portal access)  ─────────┐
  │  OpenRouter:  https://openrouter.ai/keys
  │  Gemini:      https://aistudio.google.com/app/apikey
  └────────────────────────────────────────────────────────────

  ┌─  QUICK COMMANDS  ────────────────────────────────────────┐
  │  Get URL now:    bash ~/hermes-ngrok/scripts/get-url.sh
  │  Full status:    bash ~/hermes-ngrok/scripts/status.sh
  │  Stop all:       bash ~/hermes-ngrok/scripts/stop.sh
  │  Restart all:    bash ~/hermes-ngrok/scripts/restart.sh
  └────────────────────────────────────────────────────────────

  ┌─  DOCKER LOGS  ───────────────────────────────────────────┐
  │  Hermes:    docker logs -f hermes-agent
  │  ngrok:     docker logs -f hermes-ngrok
  │  Both:      cd ~/hermes-ngrok && docker compose logs -f
  └────────────────────────────────────────────────────────────

  ┌─  NEXT STEPS  ────────────────────────────────────────────┐
  │  1. Open the URL above in your browser
  │  2. Enter the username/password above when prompted
  │  3. Get your LLM API keys (OpenRouter or Gemini — free tier)
  │  4. Add keys via the web portal  OR  edit .env
  └────────────────────────────────────────────────────────────
```

### Phase 3: First Access (2 min)

#### 3.1 Open the URL

```
Copy this URL:  https://xyz789.ngrok-free.dev
```

1. Open your browser
2. Paste the URL
3. Press ENTER

#### 3.2 Authenticate

You'll see either:

**Option A: ngrok Interstitial Page**
- Shows "Visit Site" button
- Click it
- Taken to basic auth prompt

**Option B: Browser Basic Auth Popup**
- Browser shows a login dialog
- Username: `hermes`
- Password: (from credentials.txt or deployment output)
- Click OK

#### 3.3 Hermes Dashboard Loads

You'll see:
- Hermes logo
- Welcome message
- Model selection dropdown
- Chat interface
- Settings menu (top-right)

**Congratulations! Hermes is live on the internet! 🎉**

---

## Phase 4: Configure LLM Provider (5-10 min)

### Option A: Configure via Web Portal (Recommended)

#### 4A.1 Get an API Key

Choose one:

**OpenRouter** (recommended, free tier available)
1. Go to https://openrouter.ai/keys
2. Sign up / log in
3. Copy your API key (looks like: `sk-or-v1-xxx...`)

**Google Gemini** (free tier available)
1. Go to https://aistudio.google.com/app/apikey
2. Sign in with Google
3. Create new API key
4. Copy it

#### 4A.2 Add to Hermes via Web Portal

1. Open Hermes dashboard (URL from deployment output)
2. Click **Settings** (top-right ⚙️)
3. Look for **API Keys** or **Provider Configuration**
4. Paste your API key
5. **Save**
6. Back in chat, select a model from the dropdown
7. Type a message
8. **Submit**

**First response may take 5-10 seconds (API cold start)**

### Option B: Configure via Environment File

#### 4B.1 Edit .env File

```bash
# Open the .env file
nano ~/hermes-ngrok/.env
```

Find the LLM section:

```bash
# ── LLM API Keys  (add after first web portal access) ───────────
# Provider 1 — OpenRouter  (free tier available)
OPENROUTER_API_KEY=sk-or-v1-xxxxx

# Provider 2 — Google Gemini  (free tier available)
GOOGLE_API_KEY=AIza....
```

Uncomment and fill in:

```bash
# Remove the leading "#" and paste your key
OPENROUTER_API_KEY=sk-or-v1-1234567890abcdefgh
```

Save: Press `Ctrl+X`, then `Y`, then ENTER

#### 4B.2 Restart Services

```bash
bash ~/hermes-ngrok/scripts/restart.sh
```

Wait 15 seconds for services to come back up.

Then test:
1. Refresh browser
2. Verify API key is loaded
3. Try a chat prompt

---

## Daily Operations

### Getting the Current URL

**ngrok free tier = random URL on every container restart**

So the URL might change. Here's how to find the current one:

#### Method 1: Quick Script (Recommended)

```bash
bash ~/hermes-ngrok/scripts/get-url.sh
```

Output:
```
  🌐  Hermes Dashboard URL:
      https://new-random-url.ngrok-free.dev

  🔑  Login credentials:
    Username: hermes
    Password: (from credentials.txt)
```

#### Method 2: Read File

```bash
cat ~/hermes-ngrok/current-url.txt
```

#### Method 3: View URL Watcher Logs

```bash
tail -f ~/hermes-ngrok/logs/url-watcher.log
```

### Checking Service Status

```bash
bash ~/hermes-ngrok/scripts/status.sh
```

Shows:
- Container status (running/stopped)
- Current URL
- URL watcher service status
- Last 25 lines of Hermes logs

### Stopping Services

```bash
bash ~/hermes-ngrok/scripts/stop.sh
```

**Data is preserved!** Next time you run `start.sh`, all your Hermes config/memory is intact.

### Starting Services

```bash
bash ~/hermes-ngrok/scripts/start.sh
```

Waits for ngrok tunnel to establish, then prints the new URL.

### Restarting (Keep Data)

```bash
bash ~/hermes-ngrok/scripts/restart.sh
```

Useful after changing LLM API keys in `.env`.

---

## Troubleshooting

### "Port 9119 is already in use"

```bash
# Find what's using port 9119
sudo lsof -i :9119

# Kill the process
sudo kill -9 <PID>

# Or stop Hermes and try again
bash ~/hermes-ngrok/scripts/stop.sh
wait 3
bash ~/hermes-ngrok/scripts/start.sh
```

### "Docker daemon is not running"

```bash
# Start Docker
sudo systemctl start docker

# Verify it's running
sudo systemctl status docker
```

### "ngrok tunnel not established"

```bash
# Check ngrok container logs
docker logs hermes-ngrok

# Look for error messages, common ones:
# "Invalid auth token" → Re-run deploy script with correct token
# "Connection refused" → Hermes container may not be ready
```

### "Can't log in to dashboard"

```bash
# Get credentials again
cat ~/hermes-ngrok/credentials.txt

# Or run
bash ~/hermes-ngrok/scripts/get-url.sh

# Default username is always: hermes
```

### "Hermes is slow / API is hanging"

```bash
# Check resource usage
free -h  # RAM
df -h    # Disk
top      # CPU

# Check if LLM API is configured
grep -E '^(OPENROUTER|GOOGLE|OPENAI)' ~/hermes-ngrok/.env

# Check API is responding
curl -s http://localhost:8642/health | jq
```

### "Want to update Hermes image"

```bash
# Pulls latest image and recreates container
bash ~/hermes-ngrok/scripts/update.sh

# All your data in ~/.hermes is preserved
```

### "Want to completely uninstall"

```bash
# Stops containers and removes project files
# Your data in ~/.hermes is PRESERVED
./hermes-ngrok-deploy.sh --uninstall
```

---

## Advanced Usage

### Viewing Real-Time Logs

```bash
# All containers
docker compose -f ~/hermes-ngrok/docker-compose.yml logs -f

# Just Hermes
docker logs -f hermes-agent

# Just ngrok
docker logs -f hermes-ngrok

# URL watcher
sudo journalctl -u hermes-url-watcher.service -f
```

### Checking Ports

```bash
# Hermes dashboard
curl -s http://localhost:9119/health | jq

# Hermes API
curl -s http://localhost:8642/health | jq

# ngrok management API
curl -s http://localhost:4040/api/tunnels | jq
```

### Manual Docker Compose Commands

```bash
cd ~/hermes-ngrok

# Check container status
docker compose ps

# Restart a single container
docker compose restart hermes-agent

# View environment variables
docker compose config

# Stop (doesn't remove containers)
docker compose stop

# Start
docker compose start

# Full clean stop + remove
docker compose down
```

### Backup Hermes Data

```bash
# Create a backup
tar czf ~/hermes-backup-$(date +%Y%m%d-%H%M%S).tar.gz ~/.hermes/

# List backups
ls -lh ~/ | grep hermes-backup

# Restore (if needed)
cd ~ && tar xzf hermes-backup-20260602-120000.tar.gz
bash ~/hermes-ngrok/scripts/restart.sh
```

---

## Security Checklist

- [ ] **Credentials are saved** (`credentials.txt` chmod 600)
- [ ] **`.env` file is not committed** to Git
- [ ] **Password is strong** (24-char auto-generated hex)
- [ ] **API keys are not in Git** (only in `.env`)
- [ ] **ngrok tunnel is HTTPS** (not HTTP)
- [ ] **URL watcher is running** (`sudo systemctl status hermes-url-watcher`)
- [ ] **Firewall is configured** (if using OS-level firewall)
- [ ] **Backups are taken** regularly (monthly)

---

## Frequently Asked Questions

**Q: Can I use a custom domain instead of ngrok's random URL?**
A: Yes, if you upgrade to a paid ngrok plan. See their docs: https://ngrok.com/docs/cloud-edge/domains/

**Q: What if I lose my ngrok token?**
A: Generate a new one at https://dashboard.ngrok.com/get-started/your-authtoken and re-run the deploy script.

**Q: Can I run both n8n and Hermes at the same time?**
A: Yes on the same VM if resources allow (~2 GB RAM), but ngrok free tier only allows 1 tunnel. Upgrade ngrok or use separate VMs.

**Q: Is my data safe if the VM crashes?**
A: Yes. All Hermes data is in `~/.hermes/` on the host. Restore it and restart.

**Q: Can I move to a new VM?**
A: Yes. Backup `~/.hermes/`, copy to new VM, re-run deploy script, and restore data.

**Q: How often does the ngrok URL change?**
A: On container restart. URL watcher detects and logs changes, so you're never blocked.

---

## Support & Resources

- **GitHub Issues:** https://github.com/ahmed-el-mahdy/hermes-ngrok-automation/issues
- **Hermes Docs:** https://github.com/NousResearch/Hermes
- **ngrok Docs:** https://ngrok.com/docs/
- **Docker Docs:** https://docs.docker.com/
- **OpenRouter API:** https://openrouter.ai/docs

---

**Deployment Guide Version:** 1.0  
**Last Updated:** 2026-06-02  
**Status:** Production Ready
