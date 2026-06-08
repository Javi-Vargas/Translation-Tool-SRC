#!/usr/bin/env bash
#
# download_model.sh — run on an INTERNET-CONNECTED staging machine.
#
# Downloads Qwen2.5-7B-Instruct (~15 GB) into a local HuggingFace cache so it can
# be transferred to the air-gapped backend VMs.
#
# Uses snapshot_download (downloads files only) NOT from_pretrained (which would
# also LOAD the ~28 GB float32 model into RAM). This lets you stage the weights
# on a modest machine.
#
# Usage:
#   cd cti-translate/staging
#   ./download_model.sh
#
# Result:
#   staging/model-cache/hub/models--Qwen--Qwen2.5-7B-Instruct/
#
# Transfer that models--Qwen--Qwen2.5-7B-Instruct directory to each backend VM at:
#   ~/.cache/huggingface/hub/models--Qwen--Qwen2.5-7B-Instruct/

set -euo pipefail

STAGING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACHE_DIR="${STAGING_DIR}/model-cache"
MODEL="Qwen/Qwen2.5-7B-Instruct"
VENV_DIR="${STAGING_DIR}/.staging-venv"

# Prefer the staging venv (created by build_offline_bundle.sh); else system python.
if [ -x "${VENV_DIR}/bin/python" ]; then
    PY="${VENV_DIR}/bin/python"
else
    PY="${PYTHON:-python3}"
fi

echo "==> Ensuring huggingface_hub is available"
"${PY}" -m pip install --quiet --upgrade huggingface_hub

echo "==> Downloading ${MODEL} into ${CACHE_DIR}"
echo "    This is ~15 GB and may take a while. Files only — not loaded into RAM."
mkdir -p "${CACHE_DIR}/hub"

HUGGINGFACE_HUB_CACHE="${CACHE_DIR}/hub" \
"${PY}" - "${MODEL}" "${CACHE_DIR}/hub" <<'PYEOF'
import sys
from huggingface_hub import snapshot_download

model_name, cache_dir = sys.argv[1], sys.argv[2]
print(f"Fetching all files for {model_name} ...")
path = snapshot_download(
    repo_id=model_name,
    cache_dir=cache_dir,
    # Skip duplicate/unneeded formats; keep safetensors weights + configs/tokenizer.
    ignore_patterns=["*.pth", "*.bin", "original/*"],
)
print("Download complete:", path)
PYEOF

echo ""
echo "============================================================"
echo " Model cached at:"
echo "   ${CACHE_DIR}/hub/models--Qwen--Qwen2.5-7B-Instruct/"
echo ""
echo " Transfer that directory to EACH backend VM at:"
echo "   ~/.cache/huggingface/hub/models--Qwen--Qwen2.5-7B-Instruct/"
echo ""
echo " Then verify offline on the VM:"
echo "   export HUGGINGFACE_HUB_OFFLINE=1"
echo "   python3 -c \"from transformers import AutoTokenizer; \\"
echo "     AutoTokenizer.from_pretrained('Qwen/Qwen2.5-7B-Instruct'); print('OK')\""
echo "============================================================"
