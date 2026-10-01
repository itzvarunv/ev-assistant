#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu server. Run from the project folder:  bash deploy/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
APP_DIR=$(pwd)
IP=$(curl -fsS https://api.ipify.org)
DOMAIN=${1:-$(echo "$IP" | tr . -).sslip.io}   # free HTTPS name that points at this server's IP

[ -f .env ] || { echo "Create .env first (cp .env.example .env and fill it in)"; exit 1; }

sudo apt-get update
sudo apt-get install -y python3-venv sqlite3 curl debian-keyring debian-archive-keyring apt-transport-https gpg

# Caddy: reverse proxy with automatic HTTPS (Meta only calls https webhooks)
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
  sudo apt-get update && sudo apt-get install -y caddy
fi
printf '%s {\n    reverse_proxy 127.0.0.1:8000\n}\n' "$DOMAIN" | sudo tee /etc/caddy/Caddyfile

# Small servers (e.g. Oracle's 1 GB Micro) need swap so installs don't run out of memory
if [ "$(free -m | awk '/Mem:/{print $2}')" -lt 2000 ] && ! swapon --show | grep -q swapfile; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

# Local AI models - skipped when .env says LLM_PROVIDER=gemini
if ! grep -qE '^LLM_PROVIDER=gemini' .env; then
  command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
  ollama pull "$(grep -E '^CHAT_MODEL=' .env | cut -d= -f2 || echo llama3.2:3b)"
  ollama pull qwen2.5vl:3b
fi

python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

sed "s|APP_DIR|$APP_DIR|g; s|APP_USER|$USER|g" deploy/ev-assistant.service | sudo tee /etc/systemd/system/ev-assistant.service
sudo systemctl daemon-reload
sudo systemctl enable --now ev-assistant
sudo systemctl restart caddy

# Oracle Cloud's Ubuntu image blocks 80/443 in iptables by default
if sudo iptables -L INPUT -n | grep -q REJECT; then
  sudo iptables -I INPUT -p tcp -m multiport --dports 80,443 -j ACCEPT
  command -v netfilter-persistent >/dev/null && sudo netfilter-persistent save
fi

echo
echo "Done. Webhook URL for Meta:  https://$DOMAIN/webhook"
echo "Logs:  journalctl -u ev-assistant -f"
