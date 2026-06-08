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
| RAM | **32 GB** | Qwen2.5-7B in `float32` is **~28 GB of weights alone**, plus tokenizer/activations/OS overhead. Below ~32 GB the service will be OOM-killed or thrash swap into uselessness. **This is the #1 thing that bites people.** |
| CPU | 4+ cores | No GPU required (and the code path is CPU-only). More cores = faster inference. |
| Disk | 40 GB free | ~15 GB model + venv + wheels + headroom. |
| OS | Ubuntu 24 LTS | Ships Python 3.12 (what the wheels target). |

> If your backend VMs have **less than ~32 GB RAM**, the faithful 7B/float32 setup
> will not run. Options then: give the VMs more RAM, or switch to a lighter model
> / quantized runtime (a separate change — ask and we'll add a variant).

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
| Disk | 25 GB free | ~15 GB model + ~0.3 GB wheels + temp venvs. |
| RAM | 4 GB | Downloading does **not** load the model — `snapshot_download` only writes files. |
| Bandwidth | — | ~15 GB model pull; allow time. An `HF_TOKEN` env var raises rate limits and speeds it up. |

---

## 2. Bill of materials — what you need

| # | Artifact | Approx size | Status in this repo | How to get it (§) |
|---|---|---|---|---|
| 1 | Application code (`app.py`, `placeholder_utils.py`, UI, configs) | tiny | ✅ present | already here |
| 2 | Pinned `requirements.txt` | tiny | ✅ present (`backend/requirements.txt`) | §3.1 to regenerate |
| 3 | Python dependency **wheels** | ~250 MB | ✅ present (`backend/wheels/`, 56 wheels, verified) | §3.1 to rebuild |
| 4 | **Qwen2.5-7B-Instruct** model weights | ~15 GB | ⬜ **must download** | §3.2 |
| 5 | **nginx** + dependencies as `.deb` (for air-gapped install) | ~5 MB | ⬜ optional, download if VM 1 is truly offline | §3.3 |

Items 4 and 5 are the binary payloads to acquire on the staging machine.

---

## 3. Acquisition commands (run on the staging machine)

### 3.1 Python wheels + pinned requirements  *(already done — here for rebuild)*

Automated:
```bash
cd cti-translate/staging
./build_offline_bundle.sh
```
This creates a clean venv, installs CPU-only torch + all deps, writes the exact
pins to `backend/requirements.txt`, downloads every wheel into `backend/wheels/`,
and verifies a fully offline install. Manual equivalent: `backend/wheels/DOWNLOAD_INSTRUCTIONS.md`.

Result: `backend/wheels/*.whl` (~250 MB) and a pinned `backend/requirements.txt`.

### 3.2 Qwen2.5-7B-Instruct model weights  *(must download)*

Automated:
```bash
cd cti-translate/staging
# Optional but recommended for speed / rate limits:
# export HF_TOKEN=hf_xxx
./download_model.sh
```

What it does (and the manual equivalent):
```bash
pip install huggingface_hub
python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="Qwen/Qwen2.5-7B-Instruct",
    cache_dir="model-cache/hub",
    ignore_patterns=["*.pth", "*.bin", "original/*"],  # keep safetensors only
)
PY
```
> Use `snapshot_download`, **not** `AutoModelForCausalLM.from_pretrained` — the
> latter *loads* the model into RAM (~28 GB) just to cache it. `snapshot_download`
> only writes files, so it works on a modest staging machine.

Result: `staging/model-cache/hub/models--Qwen--Qwen2.5-7B-Instruct/` (~15 GB).

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
Each VM folder is self-contained.

### → VM 2 and VM 3 (backend) — copy the whole `backend/` folder
| Artifact | Staging path | Final path on backend VM |
|---|---|---|
| App code | `backend/app.py`, `backend/placeholder_utils.py` | `~/cti-translate-backend/` |
| Pinned reqs | `backend/requirements.txt` | `~/cti-translate-backend/requirements.txt` |
| Wheels | `backend/wheels/*.whl` | `~/cti-translate-backend/wheels/` |
| Setup script | `backend/setup.sh` | `~/cti-translate-backend/setup.sh` |
| **Model weights** | `staging/model-cache/hub/models--Qwen--Qwen2.5-7B-Instruct/` | `~/.cache/huggingface/hub/models--Qwen--Qwen2.5-7B-Instruct/` |

> The model weights go in the HuggingFace **cache** path, NOT in the app folder.
> The exact directory name `models--Qwen--Qwen2.5-7B-Instruct` must be preserved.

### → VM 1 (frontend) — copy the whole `frontend/` folder
| Artifact | Staging path | Final path on frontend VM |
|---|---|---|
| UI | `frontend/ui/index.html` | `~/cti-translate-frontend/ui/index.html` (setup.sh copies it to `/var/www/cti-translate/`) |
| nginx site config | `frontend/nginx.conf` | `~/cti-translate-frontend/nginx.conf` (edit IPs first) |
| Setup script | `frontend/setup.sh` | `~/cti-translate-frontend/setup.sh` |
| nginx `.deb`s (optional) | `frontend/deb/*.deb` | `~/cti-translate-frontend/deb/` |

---

## 5. Verify before deploying

On each backend VM, confirm the weights are placed correctly and load offline
(this does need the ~28 GB RAM, so run it on the VM, not the staging box):
```bash
export HUGGINGFACE_HUB_OFFLINE=1
python3 -c "from transformers import AutoTokenizer; AutoTokenizer.from_pretrained('Qwen/Qwen2.5-7B-Instruct'); print('OK')"
```
`OK` = weights are in the right place and offline loading works.

Confirm the wheels install offline:
```bash
python3.12 -m venv /tmp/checkvenv && source /tmp/checkvenv/bin/activate
pip install --no-index --find-links=~/cti-translate-backend/wheels/ -r ~/cti-translate-backend/requirements.txt
```

Then proceed to **`DEPLOYMENT_RUNBOOK.md`** for the full deploy + verification.

---

## 6. Quick checklist

- [ ] Staging machine matches VMs (Ubuntu 24 / Python 3.12 / x86_64)
- [ ] Wheels present in `backend/wheels/` (✅ already done)
- [ ] Pinned `backend/requirements.txt` present (✅ already done)
- [ ] Model weights downloaded (§3.2) — **~15 GB**
- [ ] nginx `.deb`s downloaded if VM 1 is air-gapped (§3.3)
- [ ] **Backend VMs have ≥32 GB RAM** (else 7B/float32 won't run)
- [ ] All artifacts placed per §4
- [ ] Offline load + install verified per §5
- [ ] Deploy per `DEPLOYMENT_RUNBOOK.md`
