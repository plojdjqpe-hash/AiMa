#!/bin/bash
set -e

# ============================================
# Proxy Subscription Service — One-Click Install
# API + Telegram Bot + WebApp
# For Ubuntu/Debian Linux VPS
# ============================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  Proxy Subscription Service Installer    ║${NC}"
echo -e "${CYAN}║  API + Telegram Bot + WebApp             ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""

# --- Config ---
INSTALL_DIR="/opt/proxy-sub"
SERVICE_USER="proxy-sub"
REPO_URL="https://github.com/plojdjqpe-hash/AiMa.git"
BRANCH="devin/1777773350-add-claude-code-skill"

# --- Gather settings ---
echo -e "${YELLOW}Configuration:${NC}"

if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    read -p "Telegram Bot Token (from @BotFather): " TELEGRAM_BOT_TOKEN
fi

if [ -z "$ADMIN_IDS" ]; then
    read -p "Admin Telegram User ID (comma-separated): " ADMIN_IDS
fi

# Domain/IP for subscription URLs
if [ -z "$SERVER_DOMAIN" ]; then
    SERVER_IP=$(curl -4 -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
    read -p "Server domain or IP [$SERVER_IP]: " SERVER_DOMAIN
    SERVER_DOMAIN=${SERVER_DOMAIN:-$SERVER_IP}
fi

API_PORT=${API_PORT:-8000}
WEBAPP_URL="http://${SERVER_DOMAIN}:${API_PORT}/app"

echo ""
echo -e "${GREEN}Settings:${NC}"
echo "  Install dir:  $INSTALL_DIR"
echo "  API:          http://${SERVER_DOMAIN}:${API_PORT}"
echo "  WebApp:       ${WEBAPP_URL}"
echo "  Admin IDs:    ${ADMIN_IDS}"
echo ""
read -p "Continue? [Y/n] " confirm
if [[ "$confirm" =~ ^[Nn] ]]; then
    echo "Aborted."
    exit 0
fi

# --- Install system dependencies ---
echo -e "\n${CYAN}[1/6] Installing system dependencies...${NC}"
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git curl > /dev/null

# --- Create service user ---
echo -e "${CYAN}[2/6] Setting up service user...${NC}"
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd -r -s /bin/false -m -d "$INSTALL_DIR" "$SERVICE_USER"
fi

# --- Clone/update repo ---
echo -e "${CYAN}[3/6] Downloading proxy-sub...${NC}"
if [ -d "$INSTALL_DIR/repo" ]; then
    cd "$INSTALL_DIR/repo"
    git fetch origin "$BRANCH" --quiet
    git checkout "$BRANCH" --quiet
    git pull origin "$BRANCH" --quiet
else
    mkdir -p "$INSTALL_DIR"
    git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR/repo" --quiet
fi

# --- Setup Python venv ---
echo -e "${CYAN}[4/6] Installing Python dependencies...${NC}"
cd "$INSTALL_DIR/repo/proxy-sub"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -e .

# --- Write env file ---
echo -e "${CYAN}[5/6] Configuring services...${NC}"
cat > "$INSTALL_DIR/.env" << EOF
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
PROXY_SUB_API=http://127.0.0.1:${API_PORT}
WEBAPP_URL=${WEBAPP_URL}
ADMIN_IDS=${ADMIN_IDS}
EOF
chmod 600 "$INSTALL_DIR/.env"
chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.env"

# --- Create systemd services ---
echo -e "${CYAN}[6/6] Creating systemd services...${NC}"

# API service
cat > /etc/systemd/system/proxy-sub-api.service << EOF
[Unit]
Description=Proxy Subscription API
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR/repo/proxy-sub
EnvironmentFile=$INSTALL_DIR/.env
ExecStart=$INSTALL_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port ${API_PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Bot service
cat > /etc/systemd/system/proxy-sub-bot.service << EOF
[Unit]
Description=Proxy Subscription Telegram Bot
After=network.target proxy-sub-api.service
Requires=proxy-sub-api.service

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR/repo/proxy-sub
EnvironmentFile=$INSTALL_DIR/.env
ExecStart=$INSTALL_DIR/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# --- Fix permissions ---
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# --- Start services ---
systemctl daemon-reload
systemctl enable proxy-sub-api proxy-sub-bot
systemctl restart proxy-sub-api
sleep 2
systemctl restart proxy-sub-bot

# --- Verify ---
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Installation Complete!                  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""

api_status=$(systemctl is-active proxy-sub-api 2>/dev/null || echo "failed")
bot_status=$(systemctl is-active proxy-sub-bot 2>/dev/null || echo "failed")

if [ "$api_status" = "active" ]; then
    echo -e "  API:     ${GREEN}running${NC} on port ${API_PORT}"
else
    echo -e "  API:     ${RED}failed${NC} — check: journalctl -u proxy-sub-api"
fi

if [ "$bot_status" = "active" ]; then
    echo -e "  Bot:     ${GREEN}running${NC}"
else
    echo -e "  Bot:     ${RED}failed${NC} — check: journalctl -u proxy-sub-bot"
fi

echo ""
echo -e "  ${CYAN}API:${NC}     http://${SERVER_DOMAIN}:${API_PORT}"
echo -e "  ${CYAN}WebApp:${NC}  ${WEBAPP_URL}"
echo -e "  ${CYAN}LTE:${NC}     http://${SERVER_DOMAIN}:${API_PORT}/sub/lte"
echo -e "  ${CYAN}WiFi:${NC}    http://${SERVER_DOMAIN}:${API_PORT}/sub/wifi"
echo -e "  ${CYAN}3G:${NC}      http://${SERVER_DOMAIN}:${API_PORT}/sub/3g"
echo ""
echo -e "  ${YELLOW}Telegram:${NC} find your bot and send /start"
echo ""
echo -e "  ${YELLOW}Management:${NC}"
echo "    systemctl status proxy-sub-api"
echo "    systemctl status proxy-sub-bot"
echo "    journalctl -u proxy-sub-api -f"
echo "    journalctl -u proxy-sub-bot -f"
echo ""
echo -e "  ${YELLOW}Update:${NC}"
echo "    cd $INSTALL_DIR/repo && git pull && systemctl restart proxy-sub-api proxy-sub-bot"
echo ""

# Open firewall if ufw is active
if command -v ufw &>/dev/null && ufw status | grep -q "active"; then
    ufw allow "${API_PORT}/tcp" > /dev/null 2>&1
    echo -e "  ${GREEN}Firewall:${NC} port ${API_PORT} opened"
fi
