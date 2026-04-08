#!/usr/bin/env bash
# Quick update script — pull latest code and restart services
# Usage: sudo bash /opt/slcpipeline/deploy/update.sh

set -euo pipefail

APP_DIR="/opt/slcpipeline"
APP_USER="slcapp"

echo "Pulling latest code..."
cd ${APP_DIR}
sudo -u ${APP_USER} git pull

echo "Updating dependencies..."
sudo -u ${APP_USER} ./venv/bin/pip install -r requirements.txt

echo "Restarting services..."
systemctl restart slc-fastapi slc-streamlit

echo "Done! Checking status..."
systemctl status slc-fastapi --no-pager -l | head -5
systemctl status slc-streamlit --no-pager -l | head -5
