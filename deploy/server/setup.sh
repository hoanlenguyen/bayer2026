#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 24.04 server (Azure VM, or any VPS). Run as root:  bash setup.sh
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

echo "Docker $(docker --version) ready. Next: clone the repository and follow docs/DEPLOY_AZURE.md step 4."
