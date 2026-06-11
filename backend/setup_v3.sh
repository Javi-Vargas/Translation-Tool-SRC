#!/usr/bin/env bash
#
# setup_v3.sh — V3 backend setup (llama-cpp-python + GGUF Q5_K_M).
#
# Run on each backend VM (VM 2 and VM 3) after:
#   1. Copying this backend/ folder over (wheels/ populated — see below).
#   2. Transferring the GGUF model file to ~/models/ (see staging/download_model_gguf.sh).
#
# Differences from setup.sh (V1/V2):
#   - Uses requirements_v3.txt (no torch/transformers stack).
#   - Service points to app_v3:app.
#   - Sets GGUF_MODEL_PATH in the systemd unit.
#   - Model loads in seconds, not minutes (GGUF is memory-mapped).
#
# Populating wheels/ for V3:
#   On the internet-connected staging host, run:
#       pip download -r backend/requirements_v3.txt -d backend/wheels/ --only-binary=:all:
#   If llama-cpp-python has no pre-built wheel:
#       pip wheel llama-cpp-python -w backend/wheels/
#   (See wheels/DOWNLOAD_INSTRUCTIONS.md step 3 for the general procedure.)
#
# Usage:
#   chmod +x setup_v3.sh
#   ./setup_v3.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$HOME/translation-venv-v3"
SERVICE_NAME="cti-translate-backend-v3"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
RUN_USER="$(whoami)"
# Q5_K_M is split into two shards; llama-cpp loads both when pointed at shard 1.
GGUF_MODEL_PATH="${HOME}/models/qwen2.5-7b-instruct-q5_k_m-00001-of-00002.gguf"
GGUF_SHARD2="${HOME}/models/qwen2.5-7b-instruct-q5_k_m-00002-of-00002.gguf"

# Verify both shards are present before installing anything.
if [ ! -f "${GGUF_MODEL_PATH}" ] || [ ! -f "${GGUF_SHARD2}" ]; then
    echo "ERROR: GGUF model shards not found at ~/models/"
    echo "  Transfer both shards first:"
    echo "    mkdir -p ~/models"
    echo "    scp <staging>:staging/model-cache-gguf/qwen2.5-7b-instruct-q5_k_m-00001-of-00002.gguf ~/models/"
    echo "    scp <staging>:staging/model-cache-gguf/qwen2.5-7b-instruct-q5_k_m-00002-of-00002.gguf ~/models/"
    exit 1
fi
echo "==> Model file found: ${GGUF_MODEL_PATH}"

echo "==> Creating virtualenv at ${VENV_DIR}"
python3 -m venv "${VENV_DIR}"
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

echo "==> Upgrading pip from local wheels (if available)"
pip install --no-index --find-links="${SCRIPT_DIR}/wheels/" --upgrade pip || \
    echo "    (skipping pip upgrade — no pip wheel bundled, continuing)"

echo "==> Installing V3 dependencies offline from wheels/"
pip install --no-index --find-links="${SCRIPT_DIR}/wheels/" -r "${SCRIPT_DIR}/requirements_v3.txt"

echo "==> Writing systemd service to ${SERVICE_FILE}"
sudo tee "${SERVICE_FILE}" > /dev/null <<EOF
[Unit]
Description=CTI Translation Backend V3 (FastAPI + llama-cpp-python GGUF Q5_K_M)
After=network.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${SCRIPT_DIR}
Environment=GGUF_MODEL_PATH=${GGUF_MODEL_PATH}
ExecStart=${VENV_DIR}/bin/uvicorn app_v3:app --host 0.0.0.0 --port 8000
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
echo " Backend V3 service installed and started."
echo ""
echo " Model loads in a few seconds (GGUF is memory-mapped)."
echo " Verify readiness with:"
echo "     curl http://localhost:8000/health"
echo ""
echo " Expected once loaded:  {\"status\":\"ready\"}"
echo " While loading:         {\"status\":\"loading\"}  (HTTP 503)"
echo ""
echo " Follow logs with:"
echo "     sudo journalctl -u ${SERVICE_NAME} -f"
echo "============================================================"
