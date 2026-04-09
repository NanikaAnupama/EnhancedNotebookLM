#!/usr/bin/env bash
# ============================================================
# Self-signed SSL for Nginx — permanent HTTPS, no external deps
# Run: sudo bash /opt/slcpipeline/deploy/setup-ssl.sh
# ============================================================

set -euo pipefail

SERVER_IP="140.245.7.248"

echo "[1/3] Generating self-signed certificate..."
mkdir -p /etc/nginx/ssl

openssl req -x509 -nodes -days 3650 \
    -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/server.key \
    -out /etc/nginx/ssl/server.crt \
    -subj "/CN=${SERVER_IP}" \
    -addext "subjectAltName=IP:${SERVER_IP}"

echo "[2/3] Updating Nginx config..."
cat > /etc/nginx/sites-available/slcpipeline <<'NGXEOF'
# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name _;

    ssl_certificate /etc/nginx/ssl/server.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;

    # FastAPI — handles /api/* and /health and /docs
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 500M;
        proxy_read_timeout 600s;
        proxy_connect_timeout 60s;
    }

    location /health {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /docs {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /openapi.json {
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

echo "[3/3] Restarting Nginx..."
nginx -t && systemctl restart nginx

# Stop cloudflare tunnel if running
systemctl stop cloudflare-tunnel 2>/dev/null || true
systemctl disable cloudflare-tunnel 2>/dev/null || true

echo ""
echo "=========================================="
echo "  SSL CONFIGURED!"
echo "=========================================="
echo "  Dashboard:  https://${SERVER_IP}/"
echo "  Health:     https://${SERVER_IP}/health"
echo "  API:        https://${SERVER_IP}/api/upload-video"
echo ""
echo "  Note: Browser will show a certificate warning"
echo "  because it's self-signed. Click 'Advanced' → "
echo "  'Proceed' to accept it."
echo "  Chrome extensions with host_permissions bypass this."
echo "=========================================="
