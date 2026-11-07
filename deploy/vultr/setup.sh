#!/usr/bin/env bash
# One-time server setup on a fresh Vultr Ubuntu 24.04 instance. Run as root:  bash setup.sh
set -euo pipefail

# Docker Engine and the Compose plugin (official convenience script).
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi

# 2 GB swap: the frontend build (npm) can run out of memory on small plans.
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Firewall: SSH and web only. The backend port 8000 is never published.
if command -v ufw >/dev/null; then
  ufw allow OpenSSH
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw allow 443/udp
  ufw --force enable
fi

echo "Docker $(docker --version) ready. Next: clone the repository and follow docs/DEPLOY_VULTR.md step 4."
