#!/usr/bin/env bash
#
# Frontend setup — run on VM 1 (frontend) after copying this folder over and
# editing nginx.conf to replace BACKEND1_IP / BACKEND2_IP / FRONTEND_IP with the
# real VM IPs.
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_ROOT="/var/www/cti-translate"
SITE_AVAIL="/etc/nginx/sites-available/cti-translate"
SITE_ENABLED="/etc/nginx/sites-enabled/cti-translate"

echo "==> Installing nginx"
if ls "${SCRIPT_DIR}"/deb/*.deb >/dev/null 2>&1; then
    # Air-gapped path: install from bundled .deb packages if provided.
    echo "    Installing nginx from bundled .deb packages in deb/"
    sudo dpkg -i "${SCRIPT_DIR}"/deb/*.deb || sudo apt-get -f install -y
else
    # NOTE: apt REQUIRES INTERNET. In a true air-gapped environment, pre-bundle
    # nginx and its dependencies as .deb files in a deb/ subfolder instead.
    echo "    No deb/ bundle found — falling back to apt (REQUIRES INTERNET)."
    sudo apt-get update
    sudo apt-get install -y nginx
fi

echo "==> Creating web root ${WEB_ROOT}"
sudo mkdir -p "${WEB_ROOT}"

echo "==> Deploying UI"
sudo cp "${SCRIPT_DIR}/ui/index.html" "${WEB_ROOT}/index.html"

echo "==> Installing site config"
sudo cp "${SCRIPT_DIR}/nginx.conf" "${SITE_AVAIL}"
sudo ln -sf "${SITE_AVAIL}" "${SITE_ENABLED}"

echo "==> Removing default nginx site if present"
sudo rm -f /etc/nginx/sites-enabled/default

echo "==> Testing nginx config"
sudo nginx -t

echo "==> Restarting nginx"
sudo systemctl restart nginx
sudo systemctl enable nginx

FRONTEND_HINT="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
echo "============================================================"
echo " Frontend deployed."
echo " Open the UI in a browser at:  http://${FRONTEND_HINT:-FRONTEND_IP}"
echo ""
echo " If you see 502 Bad Gateway on translate, the backends are"
echo " not yet ready — check their /health endpoints first."
echo "============================================================"
