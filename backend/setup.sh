#!/usr/bin/env bash
#
# Backend setup — run on each backend VM (VM 2 and VM 3) after copying this
# folder over. Installs dependencies offline from wheels/, installs a systemd
# service, and starts it.
#
# Prerequisites on the VM:
#   - Python 3.11 with the venv module
#   - This folder copied to the VM (e.g. ~/cti-translate-backend)
#   - wheels/ populated (see wheels/DOWNLOAD_INSTRUCTIONS.md)
#   - Qwen weights present in ~/.cache/huggingface/hub/ (see DEPLOYMENT_RUNBOOK.md)
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh

set -euo pipefail

# Resolve the directory this script lives in (the app code lives here too).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$HOME/translation-venv"
SERVICE_NAME="cti-translate-backend"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
RUN_USER="$(whoami)"

echo "==> Creating virtualenv at ${VENV_DIR}"
python3 -m venv "${VENV_DIR}"
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

echo "==> Upgrading pip from local wheels (if available)"
pip install --no-index --find-links="${SCRIPT_DIR}/wheels/" --upgrade pip || \
    echo "    (skipping pip upgrade — no pip wheel bundled, continuing)"

echo "==> Installing dependencies offline from wheels/"
pip install --no-index --find-links="${SCRIPT_DIR}/wheels/" -r "${SCRIPT_DIR}/requirements.txt"

echo "==> Writing systemd service to ${SERVICE_FILE}"
sudo tee "${SERVICE_FILE}" > /dev/null <<EOF
[Unit]
Description=CTI Translation Backend (FastAPI + Qwen2.5-7B)
After=network.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${SCRIPT_DIR}
Environment=HUGGINGFACE_HUB_OFFLINE=1
Environment=TRANSFORMERS_OFFLINE=1
ExecStart=${VENV_DIR}/bin/uvicorn app:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "==> Enabling and starting ${SERVICE_NAME}"
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"

echo ""
echo "============================================================"
echo " Backend service installed and started."
echo ""
echo " Model loading takes 2-4 minutes. Verify readiness with:"
echo "     curl http://localhost:8000/health"
echo ""
echo " Expected once loaded:  {\"status\":\"ready\"}"
echo " While loading:         {\"status\":\"loading\"}  (HTTP 503)"
echo ""
echo " Follow logs with:"
echo "     sudo journalctl -u ${SERVICE_NAME} -f"
echo "============================================================"
