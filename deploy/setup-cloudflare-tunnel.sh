#!/usr/bin/env bash
# ============================================================
# Cloudflare Tunnel Setup — gives you a free HTTPS URL
# without needing a domain name.
#
# Run on the Oracle VM after setup-oracle.sh:
#   sudo bash /opt/slcpipeline/deploy/setup-cloudflare-tunnel.sh
#
# This creates a permanent HTTPS URL like:
#   https://random-words.trycloudflare.com
# ============================================================

set -euo pipefail

echo "=========================================="
echo "  Cloudflare Tunnel — Quick HTTPS Setup"
echo "=========================================="

# ── 1. Install cloudflared ──────────────────────────────────
echo "[1/3] Installing cloudflared..."
ARCH=$(dpkg --print-architecture)

if [ "$ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ]; then
    CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb"
elif [ "$ARCH" = "amd64" ]; then
    CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb"
else
    echo "Unsupported architecture: $ARCH"
    exit 1
fi

curl -fsSL -o /tmp/cloudflared.deb "$CF_URL"
dpkg -i /tmp/cloudflared.deb
rm /tmp/cloudflared.deb

# ── 2. Create systemd service for the tunnel ────────────────
echo "[2/3] Creating tunnel service..."

cat > /etc/systemd/system/cloudflare-tunnel.service <<'SVCEOF'
[Unit]
Description=Cloudflare Quick Tunnel (HTTPS proxy to Nginx)
After=network.target nginx.service

[Service]
Type=simple
ExecStart=/usr/bin/cloudflared tunnel --url http://localhost:80 --no-autoupdate
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable cloudflare-tunnel
systemctl start cloudflare-tunnel

# ── 3. Get the tunnel URL ──────────────────────────────────
echo "[3/3] Waiting for tunnel URL..."
sleep 5

# Extract the URL from logs
TUNNEL_URL=$(journalctl -u cloudflare-tunnel --no-pager -n 20 | grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1)

echo ""
echo "=========================================="
echo "  CLOUDFLARE TUNNEL READY!"
echo "=========================================="
if [ -n "$TUNNEL_URL" ]; then
    echo ""
    echo "  Your HTTPS URL: ${TUNNEL_URL}"
    echo ""
    echo "  Dashboard:   ${TUNNEL_URL}/"
    echo "  Health:      ${TUNNEL_URL}/health"
    echo "  Upload API:  ${TUNNEL_URL}/api/upload-video"
    echo ""
    echo "  Update Chrome extension with this URL!"
else
    echo ""
    echo "  Tunnel started but URL not captured yet."
    echo "  Run: journalctl -u cloudflare-tunnel --no-pager | grep trycloudflare"
    echo "  to find your HTTPS URL."
fi
echo "=========================================="
