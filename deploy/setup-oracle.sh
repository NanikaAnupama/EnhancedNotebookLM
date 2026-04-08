#!/usr/bin/env bash
# ============================================================
# Oracle Cloud VM Setup Script for SLC Video Pipeline
# Run this on a fresh Ubuntu 22.04/24.04 ARM or AMD instance
# Usage: sudo bash setup-oracle.sh
# ============================================================

set -euo pipefail

APP_USER="slcapp"
APP_DIR="/opt/slcpipeline"
REPO_URL="https://github.com/NanikaAnupama/EnhancedNotebookLM.git"

echo "=========================================="
echo "  SLC Video Pipeline — Oracle Cloud Setup"
echo "=========================================="

# ── 1. System packages ──────────────────────────────────────
echo "[1/8] Installing system packages..."
apt-get update
apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    ffmpeg \
    mysql-server \
    nginx \
    certbot python3-certbot-nginx \
    git curl ufw

# ── 2. Firewall ─────────────────────────────────────────────
echo "[2/8] Configuring firewall..."
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS
ufw --force enable

# ── 3. MySQL setup ──────────────────────────────────────────
echo "[3/8] Setting up MySQL..."
systemctl enable mysql
systemctl start mysql

# Generate a random password for the app
DB_PASS=$(openssl rand -base64 16 | tr -dc 'a-zA-Z0-9' | head -c 16)

mysql -u root <<EOSQL
CREATE DATABASE IF NOT EXISTS slcpipeline CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${APP_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';
GRANT ALL PRIVILEGES ON slcpipeline.* TO '${APP_USER}'@'localhost';
FLUSH PRIVILEGES;
EOSQL

echo "  MySQL database 'slcpipeline' created"
echo "  MySQL user '${APP_USER}' with password '${DB_PASS}'"

# ── 4. App user & directory ─────────────────────────────────
echo "[4/8] Setting up application..."
id -u ${APP_USER} &>/dev/null || useradd -r -m -s /bin/bash ${APP_USER}

if [ -d "${APP_DIR}" ]; then
    cd ${APP_DIR} && git pull
else
    git clone ${REPO_URL} ${APP_DIR}
fi

chown -R ${APP_USER}:${APP_USER} ${APP_DIR}

# ── 5. Python venv & dependencies ───────────────────────────
echo "[5/8] Installing Python dependencies..."
cd ${APP_DIR}
sudo -u ${APP_USER} python3 -m venv venv
sudo -u ${APP_USER} ./venv/bin/pip install --upgrade pip
sudo -u ${APP_USER} ./venv/bin/pip install -r requirements.txt

# Create required directories
sudo -u ${APP_USER} mkdir -p /tmp/slc_uploads assets fonts

# ── 6. Environment file ─────────────────────────────────────
echo "[6/8] Creating environment file..."
cat > ${APP_DIR}/.env <<ENVEOF
DATABASE_URL=mysql+pymysql://${APP_USER}:${DB_PASS}@localhost:3306/slcpipeline
SERVICE_MODE=both
# MS_CLIENT_ID=772dd850-50bd-4c97-9152-d1b3e78fb737
# MS_AUTHORITY=https://login.microsoftonline.com/globaledulinkuk.onmicrosoft.com
# ONEDRIVE_FOLDER_URL=<your-onedrive-url>
ENVEOF

chmod 600 ${APP_DIR}/.env
chown ${APP_USER}:${APP_USER} ${APP_DIR}/.env

# ── 7. Systemd services ─────────────────────────────────────
echo "[7/8] Creating systemd services..."

# FastAPI service
cat > /etc/systemd/system/slc-fastapi.service <<SVCEOF
[Unit]
Description=SLC Video Pipeline — FastAPI
After=network.target mysql.service
Wants=mysql.service

[Service]
Type=exec
User=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
Environment=SERVICE_MODE=fastapi
Environment=PORT=8000
ExecStart=${APP_DIR}/venv/bin/uvicorn api:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

# Streamlit service
cat > /etc/systemd/system/slc-streamlit.service <<SVCEOF
[Unit]
Description=SLC Video Pipeline — Streamlit Dashboard
After=network.target mysql.service
Wants=mysql.service

[Service]
Type=exec
User=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
Environment=SERVICE_MODE=streamlit
Environment=PORT=8501
ExecStart=${APP_DIR}/venv/bin/streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable slc-fastapi slc-streamlit
systemctl start slc-fastapi slc-streamlit

# ── 8. Nginx reverse proxy ──────────────────────────────────
echo "[8/8] Configuring Nginx..."

cat > /etc/nginx/sites-available/slcpipeline <<'NGXEOF'
server {
    listen 80;
    server_name _;

    # FastAPI — handles /api/* and /health
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 200M;
        proxy_read_timeout 300s;
    }

    location /health {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Streamlit — everything else
    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
NGXEOF

ln -sf /etc/nginx/sites-available/slcpipeline /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

echo ""
echo "=========================================="
echo "  SETUP COMPLETE!"
echo "=========================================="
echo ""
echo "  MySQL password: ${DB_PASS}"
echo "  (saved in ${APP_DIR}/.env)"
echo ""
echo "  Services:"
echo "    FastAPI:   http://<YOUR-IP>/health"
echo "    Streamlit: http://<YOUR-IP>/"
echo ""
echo "  Commands:"
echo "    sudo systemctl status slc-fastapi"
echo "    sudo systemctl status slc-streamlit"
echo "    sudo journalctl -u slc-fastapi -f"
echo "    sudo journalctl -u slc-streamlit -f"
echo ""
echo "  Next steps:"
echo "    1. Open port 80 and 443 in Oracle Cloud Security List"
echo "    2. Point your domain to this VM's public IP"
echo "    3. Run: sudo certbot --nginx -d yourdomain.com"
echo "    4. Update Chrome extension URLs to your new domain"
echo "=========================================="
