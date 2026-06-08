# CTI Translation Service — Requirements & Acquisition Guide

This is the **bill of materials**: everything the service needs, how to acquire
each piece on an internet-connected machine, and exactly where each piece must
end up. Once everything is staged and placed, follow `DEPLOYMENT_RUNBOOK.md` to
deploy.

> Why a separate acquisition machine? The air-gapped VMs have no internet, and a
> modest workstation may not have the disk/bandwidth/RAM to stage everything. Do
> all downloading on a capable, internet-connected **staging machine** whose OS
> and Python match the VMs, then physically transfer the artifacts.

---

## 1. Hardware & OS requirements

### Backend VMs (VM 2, VM 3) — the important one
| Resource | Minimum | Notes |
|---|---|---|
| RAM | **8 GB** | Qwen2.5-7B Q5_K_M GGUF is ~5.5 GB in RAM. 8 GB gives comfortable headroom for the OS and app. |
| CPU | 4+ cores | No GPU required. llama-cpp-python uses all available cores automatically. |
| Disk | 15 GB free | ~5.5 GB GGUF + venv + wheels + headroom. |
| OS | Ubuntu 24 LTS | Ships Python 3.12 (what the wheels target). |

### Frontend VM (VM 1)
| Resource | Minimum | Notes |
|---|---|---|
| RAM | 1 GB | nginx + static file serving only. |
| Disk | 2 GB | nginx + UI. |
| OS | Ubuntu 24 LTS | |

### Staging machine (internet-connected)
| Resource | Minimum | Notes |
|---|---|---|
| OS / Python | Ubuntu 24 LTS / Python 3.12, x86_64 | **Must match the VMs** so wheels are compatible. |
| Disk | 10 GB free | ~5.5 GB GGUF + ~100 MB wheels + temp venvs. |
| RAM | 2 GB | Downloading does not load the model — only writes files to disk. |
| Bandwidth | — | ~5.5 GB GGUF pull. An `HF_TOKEN` env var raises rate limits and speeds it up. |

---

## 2. Bill of materials — what you need

| # | Artifact | Approx size | Status in this repo | How to get it (§) |
|---|---|---|---|---|
| 1 | Application code (`app_v3.py`, `placeholder_utils.py`, UI, configs) | tiny | ✅ present | already here |
| 2 | Pinned `requirements_v3.txt` | tiny | ✅ present (`backend/requirements_v3.txt`) | §3.1 to regenerate |
| 3 | Python dependency **wheels** | ~100 MB | ⬜ **must download** | §3.1 |
| 4 | **Qwen2.5-7B-Instruct Q5_K_M GGUF** model file | ~5.5 GB | ⬜ **must download** | §3.2 |
| 5 | **nginx** + dependencies as `.deb` (for air-gapped install) | ~5 MB | ⬜ optional, download if VM 1 is truly offline | §3.3 |

Items 3, 4, and 5 are the binary payloads to acquire on the staging machine.

---

## 3. Acquisition commands (run on the staging machine)

### 3.1 Python wheels + pinned requirements

Automated:
```bash
cd cti-translate/staging
./build_offline_bundle.sh
```
This creates a clean venv, installs `llama-cpp-python` + all deps from
`backend/requirements_v3.txt`, writes exact pins back to that file, downloads
every wheel into `backend/wheels/`, and verifies a fully offline install.

> **llama-cpp-python wheels:** If `pip download` cannot find a pre-built binary
> wheel for your platform, build it on the staging host (same OS/arch as VMs):
> ```bash
> pip wheel llama-cpp-python -w backend/wheels/
> ```
> See `backend/wheels/DOWNLOAD_INSTRUCTIONS.md` step 3 for the full procedure.

Result: `backend/wheels/*.whl` (~100 MB) and a pinned `backend/requirements_v3.txt`.

### 3.2 Qwen2.5-7B-Instruct GGUF model file  *(must download)*

Automated:
```bash
cd cti-translate/staging
# Optional but recommended for speed / rate limits:
# export HF_TOKEN=hf_xxx
./download_model_gguf.sh
```

What it does (manual equivalent):
```bash
pip install huggingface_hub
python - <<'PY'
from huggingface_hub import hf_hub_download
hf_hub_download(
    repo_id="Qwen/Qwen2.5-7B-Instruct-GGUF",
    filename="qwen2.5-7b-instruct-q5_k_m.gguf",
    local_dir="staging/model-cache-gguf",
)
PY
```

Result: `staging/model-cache-gguf/qwen2.5-7b-instruct-q5_k_m.gguf` (~5.5 GB).

### 3.3 nginx as offline `.deb` packages  *(only if VM 1 is air-gapped)*

`frontend/setup.sh` installs nginx from a `frontend/deb/` folder if present,
otherwise falls back to `apt` (which needs internet). For a truly offline VM 1,
pre-download nginx and all its dependencies on a matching Ubuntu 24 machine:

```bash
mkdir -p cti-translate/frontend/deb && cd cti-translate/frontend/deb
sudo apt-get update
apt-get download $(apt-cache depends --recurse --no-recommends --no-suggests \
  --no-conflicts --no-breaks --no-replaces --no-enhances nginx \
  | grep '^\w' | sort -u)
```
Result: a set of `.deb` files in `frontend/deb/`. `setup.sh` installs them with
`dpkg -i deb/*.deb`.

---

## 4. Placement matrix — where each artifact must end up

After acquiring everything on the staging machine, transfer to the VMs as below.

### → VM 2 and VM 3 (backend) — copy the whole `backend/` folder
| Artifact | Staging path | Final path on backend VM |
|---|---|---|
| App code | `backend/app_v3.py`, `backend/placeholder_utils.py` | `~/cti-translate-backend/` |
| Pinned reqs | `backend/requirements_v3.txt` | `~/cti-translate-backend/requirements_v3.txt` |
| Wheels | `backend/wheels/*.whl` | `~/cti-translate-backend/wheels/` |
| Setup script | `backend/setup_v3.sh` | `~/cti-translate-backend/setup_v3.sh` |
| **Model file** | `staging/model-cache-gguf/qwen2.5-7b-instruct-q5_k_m.gguf` | `~/models/qwen2.5-7b-instruct-q5_k_m.gguf` |

> The GGUF model file goes in `~/models/` on each backend VM — **not** inside
> the app folder. `setup_v3.sh` checks this path exists before proceeding.

### → VM 1 (frontend) — copy the whole `frontend/` folder
| Artifact | Staging path | Final path on frontend VM |
|---|---|---|
| UI | `frontend/ui/index.html` | `~/cti-translate-frontend/ui/index.html` (setup.sh copies it to `/var/www/cti-translate/`) |
| nginx site config | `frontend/nginx.conf` | `~/cti-translate-frontend/nginx.conf` (edit IPs first) |
| Setup script | `frontend/setup.sh` | `~/cti-translate-frontend/setup.sh` |
| nginx `.deb`s (optional) | `frontend/deb/*.deb` | `~/cti-translate-frontend/deb/` |

---

## 5. Verify before deploying

On each backend VM, confirm the GGUF file is present and the library imports work:

```bash
# Check the file exists and is the right size (~5.5 GB)
ls -lh ~/models/qwen2.5-7b-instruct-q5_k_m.gguf

# Confirm llama-cpp-python installed correctly
source ~/translation-venv-v3/bin/activate      # if venv already created by setup_v3.sh
python3 -c "from llama_cpp import Llama; print('OK')"
```

Confirm the wheels install offline (before running setup_v3.sh):
```bash
python3.12 -m venv /tmp/checkvenv && source /tmp/checkvenv/bin/activate
pip install --no-index --find-links=~/cti-translate-backend/wheels/ \
  -r ~/cti-translate-backend/requirements_v3.txt
```

Then proceed to **`DEPLOYMENT_RUNBOOK.md`** for the full deploy + verification.

---

## 6. Quick checklist

- [ ] Staging machine matches VMs (Ubuntu 24 / Python 3.12 / x86_64)
- [ ] `build_offline_bundle.sh` run → wheels in `backend/wheels/`, `requirements_v3.txt` pinned
- [ ] GGUF model downloaded via `download_model_gguf.sh` — **~5.5 GB**
- [ ] nginx `.deb`s downloaded if VM 1 is air-gapped (§3.3)
- [ ] **Backend VMs have ≥ 8 GB RAM**
- [ ] All artifacts placed per §4
- [ ] `~/models/qwen2.5-7b-instruct-q5_k_m.gguf` present on each backend VM
- [ ] Offline install verified per §5
- [ ] Deploy per `DEPLOYMENT_RUNBOOK.md`
