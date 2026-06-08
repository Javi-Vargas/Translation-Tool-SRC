# CTI Translation Service — Deployment Runbook

A step-by-step guide to deploying the 3-VM, air-gapped CTI translation service.
Written for an operator, not a developer. Follow the sections in order.

```
VM 1 — Frontend   nginx reverse proxy + static UI            (port 80)
VM 2 — Backend 1  FastAPI + Qwen2.5-7B-Instruct              (port 8000)
VM 3 — Backend 2  FastAPI + Qwen2.5-7B-Instruct              (port 8000)
```

All three VMs run **Ubuntu 24 LTS** and have **no internet access**. Everything
is staged on an internet-connected machine first, then physically transferred.

---

## 0. Build the package (on the machine running Claude Code)

You already have the `cti-translate/` folder. It contains:

```
cti-translate/
├── DEPLOYMENT_RUNBOOK.md        ← this file
├── backend/                     ← copy to VM 2 and VM 3
│   ├── app.py
│   ├── placeholder_utils.py
│   ├── requirements.txt
│   ├── setup.sh
│   └── wheels/                  ← populated by the staging step below
│       └── DOWNLOAD_INSTRUCTIONS.md
├── frontend/                    ← copy to VM 1
│   ├── setup.sh
│   ├── nginx.conf
│   └── ui/index.html
└── staging/                     ← run on an INTERNET-connected machine only
    ├── build_offline_bundle.sh
    └── download_model.sh
```

---

## 1. Stage the offline payload (internet-connected machine)

The code is ready, but the **wheels** and **model weights** are binary payloads
that must be downloaded. Do this on a machine WITH internet, ideally matching the
VMs (Ubuntu, Python 3.11, x86_64).

```bash
cd cti-translate/staging
./build_offline_bundle.sh      # pins requirements.txt + fills backend/wheels/
./download_model.sh            # downloads Qwen2.5-7B-Instruct into ./model-cache/
```

After this:
- `backend/requirements.txt` has exact pinned versions
- `backend/wheels/` is full of `.whl` files
- `staging/model-cache/` holds the HuggingFace model cache

---

## 2. Prerequisites checklist

- [ ] Three VMs provisioned, running Ubuntu 24 LTS
- [ ] Static IPs assigned to all three VMs
- [ ] All three VMs can reach each other on the network (test with `ping`)
- [ ] Python 3.12 + `python3.12-venv` present on VM 2 and VM 3 (default on Ubuntu 24 LTS)
- [ ] Qwen model weights transferred to VM 2 and VM 3 (Section 3)
- [ ] Deployment package transferred to the right VMs (Section 4 / 5)
- [ ] You know the real IPs — write them here:
  - FRONTEND_IP = ________________
  - BACKEND1_IP = ________________
  - BACKEND2_IP = ________________

---

## 3. Model weights transfer (to VM 2 and VM 3)

### 3a. Download on the internet-connected machine

`staging/download_model.sh` already did this. If doing it manually:

```bash
pip install transformers
python -c "
from transformers import AutoTokenizer, AutoModelForCausalLM
AutoTokenizer.from_pretrained('Qwen/Qwen2.5-7B-Instruct')
AutoModelForCausalLM.from_pretrained('Qwen/Qwen2.5-7B-Instruct')
"
```

### 3b. Locate the cache

```
~/.cache/huggingface/hub/models--Qwen--Qwen2.5-7B-Instruct/
```

(Or `staging/model-cache/hub/models--Qwen--Qwen2.5-7B-Instruct/` if you used the
script.)

### 3c. Transfer to VM 2 and VM 3 at the SAME path

On each backend VM the weights must live at:

```
~/.cache/huggingface/hub/models--Qwen--Qwen2.5-7B-Instruct/
```

Copy the entire `models--Qwen--Qwen2.5-7B-Instruct` directory there (USB, scp
within the offline network, etc.). Preserve the directory structure exactly.

### 3d. Verify offline (on each backend VM)

```bash
export HUGGINGFACE_HUB_OFFLINE=1
python3 -c "from transformers import AutoTokenizer; AutoTokenizer.from_pretrained('Qwen/Qwen2.5-7B-Instruct'); print('OK')"
```

`OK` means the weights are in the right place and offline loading works.

---

## 4. Backend deployment (VM 2 and VM 3 — identical steps)

Do this on **each** backend VM.

1. SSH into the VM.
2. Copy the `backend/` folder over (e.g. to `~/cti-translate-backend`). It must
   include the populated `wheels/` directory.
3. Confirm weights are in place (Section 3d).
4. Run setup:
   ```bash
   cd ~/cti-translate-backend
   chmod +x setup.sh
   ./setup.sh
   ```
5. The script creates `~/translation-venv`, installs from `wheels/` with no
   internet, installs the systemd service `cti-translate-backend`, and starts it.
6. Wait 2–4 minutes for the model to load, then verify:
   ```bash
   curl http://localhost:8000/health
   ```
   `{"status":"loading"}` (HTTP 503) → still loading; wait.
   `{"status":"ready"}`  (HTTP 200) → ready.
7. Tail logs if needed:
   ```bash
   sudo journalctl -u cti-translate-backend -f
   ```

Repeat for the second backend VM.

---

## 5. Frontend deployment (VM 1)

1. SSH into VM 1.
2. Copy the `frontend/` folder over (e.g. `~/cti-translate-frontend`).
3. **Edit `nginx.conf`** and replace the placeholders with real IPs:
   - `BACKEND1_IP` → VM 2 IP
   - `BACKEND2_IP` → VM 3 IP
   - `FRONTEND_IP` → VM 1 IP
4. For a true air-gapped install, place nginx `.deb` packages in a `deb/`
   subfolder (otherwise `setup.sh` falls back to apt, which needs internet).
5. Run setup:
   ```bash
   cd ~/cti-translate-frontend
   chmod +x setup.sh
   ./setup.sh
   ```
6. The script installs nginx, deploys the UI to `/var/www/cti-translate/`,
   installs the site config, tests it (`nginx -t`), and restarts nginx.
7. Open `http://FRONTEND_IP` in a browser — the UI should load and the status
   indicator should turn green ("Backend ready") once both backends are up.

---

## 6. Verification steps

1. **Backend health** (from VM 1 or any VM that can reach the backends):
   ```bash
   curl http://BACKEND1_IP:8000/health
   curl http://BACKEND2_IP:8000/health
   ```
   Both should return `{"status":"ready"}`. Model loading takes 2–4 minutes
   after service start.

2. **Direct translation against a backend** (bypassing nginx):
   ```bash
   curl -X POST http://BACKEND1_IP:8000/translate \
     -H "Content-Type: application/json" \
     -d '{"source_text":"Test translation","source_lang":"English","target_lang":"Traditional Chinese","use_placeholder":true}'
   ```
   Expect JSON with `translation`, `cti_pass_rate`, `script_check`, `cti_terms`.

3. **UI loads:** open `http://FRONTEND_IP` and confirm the page renders.

4. **Translate through the UI:** enter text, pick languages, click Translate,
   confirm a result returns with a CTI score.

5. **Load balancing:** submit two translations in quick succession and confirm
   nginx routes them to different backends — check each backend's logs:
   ```bash
   sudo journalctl -u cti-translate-backend -f
   ```
   You should see request activity split across VM 2 and VM 3.

---

## 7. Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| Backend `/health` returns 503 | Model still loading — wait 2–4 minutes. |
| nginx returns **502 Bad Gateway** | Backend not running or not yet ready. Check `systemctl status cti-translate-backend` and `/health`. |
| Translation **times out** in browser | Increase `proxy_read_timeout` in `nginx.conf` (already 600s) and reload nginx. |
| **Wrong script** in Chinese output | Confirm the EN→TC system prompt is applied; check `source_lang`/`target_lang` are exactly the supported strings. |
| **Model weights not found** | Ensure `HUGGINGFACE_HUB_OFFLINE=1` is set (the systemd unit sets it) and the cache path matches Section 3c exactly. |
| Offline `pip install` fails | A wheel is missing — see `backend/wheels/DOWNLOAD_INSTRUCTIONS.md` step 3. |

---

## 8. Adding a third backend VM later

Scaling out is two steps:

1. **Deploy backend** on the new VM following Section 4 (copy `backend/`,
   transfer weights, run `setup.sh`, confirm `/health` is ready).
2. **Register it with nginx** on VM 1 — add one line to the upstream block in
   `nginx.conf`:
   ```nginx
   upstream translation_backends {
       least_conn;
       server BACKEND1_IP:8000 max_fails=3 fail_timeout=30s;
       server BACKEND2_IP:8000 max_fails=3 fail_timeout=30s;
       server BACKEND3_IP:8000 max_fails=3 fail_timeout=30s;   # new
   }
   ```
   Then reload:
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```
   No downtime; new requests start flowing to the third backend immediately.

---

## Validation criteria (done when all true)

1. `curl http://BACKEND1_IP:8000/health` → `{"status":"ready"}`
2. `curl http://BACKEND2_IP:8000/health` → `{"status":"ready"}`
3. Direct POST to `/translate` on either backend returns a valid translation
   with CTI scores
4. UI loads at `http://FRONTEND_IP`
5. A translation submitted through the UI returns a correct result
6. Two rapid submissions are distributed across both backends (in the logs)
7. English → Traditional Chinese produces a CORRECT script check
8. CTI term pass rate on the test text is 10/11 or better
