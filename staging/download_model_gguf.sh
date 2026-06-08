#!/usr/bin/env bash
#
# download_model_gguf.sh — run on an INTERNET-CONNECTED staging machine.
#
# Downloads the Qwen2.5-7B-Instruct Q5_K_M GGUF (~5.5 GB) for use with V3
# (app_v3.py / llama-cpp-python).  Much smaller than the full safetensors
# weights used by V1/V2 (~15 GB).
#
# Result:
#   staging/model-cache-gguf/qwen2.5-7b-instruct-q5_k_m.gguf
#
# Transfer that single file to each backend VM at:
#   ~/models/qwen2.5-7b-instruct-q5_k_m.gguf
#
# Or set GGUF_MODEL_PATH in the systemd service (setup_v3.sh does this
# automatically using the default ~/models/ path).
#
# Usage:
#   cd cti-translate/staging
#   ./download_model_gguf.sh

set -euo pipefail

STAGING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACHE_DIR="${STAGING_DIR}/model-cache-gguf"
REPO_ID="Qwen/Qwen2.5-7B-Instruct-GGUF"
FILENAME="qwen2.5-7b-instruct-q5_k_m.gguf"
VENV_DIR="${STAGING_DIR}/.staging-venv"

# Prefer the staging venv (created by build_offline_bundle.sh); else system python.
if [ -x "${VENV_DIR}/bin/python" ]; then
    PY="${VENV_DIR}/bin/python"
else
    PY="${PYTHON:-python3}"
fi

echo "==> Ensuring huggingface_hub is available"
"${PY}" -m pip install --quiet --upgrade huggingface_hub

echo "==> Downloading ${FILENAME} from ${REPO_ID}"
echo "    ~5.5 GB — Q5_K_M quantisation (5.5 bits/weight)."
echo "    Destination: ${CACHE_DIR}/${FILENAME}"
mkdir -p "${CACHE_DIR}"

"${PY}" - "${REPO_ID}" "${FILENAME}" "${CACHE_DIR}" <<'PYEOF'
import sys
from huggingface_hub import hf_hub_download

repo_id, filename, local_dir = sys.argv[1], sys.argv[2], sys.argv[3]
print(f"Fetching {filename} from {repo_id} ...")
path = hf_hub_download(
    repo_id=repo_id,
    filename=filename,
    local_dir=local_dir,
)
print("Download complete:", path)
PYEOF

echo ""
echo "============================================================"
echo " GGUF model saved at:"
echo "   ${CACHE_DIR}/${FILENAME}"
echo ""
echo " Transfer that file to EACH backend VM at:"
echo "   ~/models/${FILENAME}"
echo ""
echo "   mkdir -p ~/models"
echo "   scp ${CACHE_DIR}/${FILENAME} user@VM_IP:~/models/${FILENAME}"
echo ""
echo " Then run backend/setup_v3.sh on each VM."
echo "============================================================"
