#!/usr/bin/env bash
#
# build_offline_bundle.sh — run on an INTERNET-CONNECTED staging machine whose
# OS/Python match the target VMs (Ubuntu 24 LTS => Python 3.12, linux x86_64).
#
# Produces the offline payload the air-gapped backend VMs need:
#   1. Pins backend/requirements_v3.txt to exact versions (clean install + freeze)
#   2. Downloads all wheels into backend/wheels/
#   3. Verifies a fully offline install succeeds
#
# Uses the llama-cpp-python stack (V3). No torch/CUDA wheels are downloaded.
#
# llama-cpp-python ships pre-built CPU wheels for common platforms. If pip
# download falls back to an sdist (no pre-built wheel for your platform), build
# it on the staging host first:
#     pip wheel llama-cpp-python -w backend/wheels/
# See backend/wheels/DOWNLOAD_INSTRUCTIONS.md step 3 for the general procedure.
#
# Run download_model_gguf.sh separately for the GGUF model file.
#
# Usage:
#   cd cti-translate/staging
#   ./build_offline_bundle.sh

set -euo pipefail

STAGING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${STAGING_DIR}/../backend" && pwd)"
WHEELS_DIR="${BACKEND_DIR}/wheels"
REQ="${BACKEND_DIR}/requirements_v3.txt"
STAGING_VENV="${STAGING_DIR}/.staging-venv"

PY="${PYTHON:-python3}"

if ! command -v "${PY}" >/dev/null 2>&1; then
    echo "ERROR: ${PY} not found. Set PYTHON=... to a Python that matches the VMs (3.12)."
    exit 1
fi
echo "==> Using $("${PY}" --version) at $(command -v "${PY}")"

echo "==> [1/4] Clean install to resolve exact versions"
rm -rf "${STAGING_VENV}"
"${PY}" -m venv "${STAGING_VENV}"
# shellcheck disable=SC1091
source "${STAGING_VENV}/bin/activate"
pip install --upgrade pip
pip install -r "${REQ}"

echo "==> [2/4] Pinning ${REQ} via pip freeze"
pip freeze > "${REQ}"
deactivate
echo "    requirements_v3.txt now pinned."

echo "==> [3/4] Downloading wheels into ${WHEELS_DIR} (native platform)"
mkdir -p "${WHEELS_DIR}"
# shellcheck disable=SC1091
source "${STAGING_VENV}/bin/activate"
pip download -r "${REQ}" -d "${WHEELS_DIR}" --only-binary=:all: \
  || {
        echo ""
        echo "WARNING: wheel download failed for one or more packages."
        echo "  If llama-cpp-python is missing a pre-built wheel, build it:"
        echo "    pip wheel llama-cpp-python -w ${WHEELS_DIR}"
        echo "  Then re-run this script."
        echo "  See backend/wheels/DOWNLOAD_INSTRUCTIONS.md step 3."
        deactivate
        exit 1
     }
# Bundle pip itself so backend setup_v3.sh can upgrade pip offline.
pip download pip -d "${WHEELS_DIR}" --only-binary=:all: || true
deactivate

echo "==> [4/4] Verifying a fully offline install"
VERIFYVENV="$(mktemp -d)/verifyvenv"
"${PY}" -m venv "${VERIFYVENV}"
# shellcheck disable=SC1091
source "${VERIFYVENV}/bin/activate"
if pip install --no-index --find-links="${WHEELS_DIR}" -r "${REQ}"; then
    echo "    OFFLINE INSTALL OK — bundle is complete."
else
    echo "    OFFLINE INSTALL FAILED — a wheel is missing."
    echo "    See backend/wheels/DOWNLOAD_INSTRUCTIONS.md step 3."
    deactivate
    exit 1
fi
deactivate

echo ""
echo "============================================================"
echo " Offline bundle ready."
echo "   - Pinned:   ${REQ}"
echo "   - Wheels:   ${WHEELS_DIR} ($(ls -1 "${WHEELS_DIR}"/*.whl 2>/dev/null | wc -l) files)"
echo ""
echo " Next: ./download_model_gguf.sh   (to fetch the GGUF model file)"
echo "============================================================"
