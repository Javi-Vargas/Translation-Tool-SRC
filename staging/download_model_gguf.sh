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
# Q5_K_M is split into two shards in the upstream repo.
# llama-cpp-python loads split GGUFs by pointing at the first shard.
SHARD1="qwen2.5-7b-instruct-q5_k_m-00001-of-00002.gguf"
SHARD2="qwen2.5-7b-instruct-q5_k_m-00002-of-00002.gguf"
VENV_DIR="${STAGING_DIR}/.staging-venv"

# Prefer the staging venv (created by build_offline_bundle.sh); else system python.
if [ -x "${VENV_DIR}/bin/python" ]; then
    PY="${VENV_DIR}/bin/python"
else
    PY="${PYTHON:-python3}"
fi

echo "==> Ensuring huggingface_hub is available"
"${PY}" -m pip install --quiet --upgrade huggingface_hub

echo "==> Downloading Q5_K_M shards from ${REPO_ID}"
echo "    ~5.5 GB total (2 shards) — Q5_K_M quantisation (5.5 bits/weight)."
echo "    Destination: ${CACHE_DIR}/"
mkdir -p "${CACHE_DIR}"

"${PY}" - "${REPO_ID}" "${SHARD1}" "${SHARD2}" "${CACHE_DIR}" <<'PYEOF'
import sys
from huggingface_hub import hf_hub_download

repo_id, shard1, shard2, local_dir = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
for filename in (shard1, shard2):
    print(f"Fetching {filename} from {repo_id} ...")
    path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        local_dir=local_dir,
    )
    print("Done:", path)
PYEOF

echo ""
echo "============================================================"
echo " GGUF model shards saved at:"
echo "   ${CACHE_DIR}/${SHARD1}"
echo "   ${CACHE_DIR}/${SHARD2}"
echo ""
echo " Transfer BOTH shards to EACH backend VM at ~/models/:"
echo ""
echo "   mkdir -p ~/models"
echo "   scp ${CACHE_DIR}/${SHARD1} user@VM_IP:~/models/"
echo "   scp ${CACHE_DIR}/${SHARD2} user@VM_IP:~/models/"
echo ""
echo " Then run backend/setup_v3.sh on each VM."
echo "============================================================"
