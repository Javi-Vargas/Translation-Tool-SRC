# Translation Tool SRC

An **air-gapped CTI (Cyber Threat Intelligence) translation service**. A small,
scalable 3-VM deployment that translates security/threat-intelligence text
between **English, Traditional Chinese, and Simplified Chinese** using a locally
hosted LLM — with no internet access on any node.

The UI looks and feels like Google Translate (left/right panels), while the
backend specializes the translation for CTI: it preserves technical terminology,
enforces Traditional (Taiwan) characters, and scores each translation against a
threat-intelligence glossary.

---

## Architecture

```
                 ┌─────────────────────────────┐
   Browser ────▶ │  VM 1 — Frontend            │
                 │  nginx reverse proxy + UI    │
                 │  (least_conn load balancer)  │
                 └───────────┬─────────────────┘
                     /api/    │
              ┌───────────────┴───────────────┐
              ▼                               ▼
   ┌────────────────────┐         ┌────────────────────┐
   │ VM 2 — Backend 1   │         │ VM 3 — Backend 2   │
   │ FastAPI + Qwen2.5  │         │ FastAPI + Qwen2.5  │
   │ -7B-Instruct :8000 │         │ -7B-Instruct :8000 │
   └────────────────────┘         └────────────────────┘
```

- **Frontend (VM 1):** nginx serves a single self-contained `index.html` and
  proxies `/api/` to the backend pool, balancing with `least_conn` and long
  (600s) timeouts for slow CPU inference.
- **Backends (VM 2 & VM 3):** identical FastAPI apps, each loading
  `Qwen/Qwen2.5-7B-Instruct` once and keeping it resident. A `/health` endpoint
  gates traffic until the model is loaded.
- **Air-gapped:** everything (model weights, Python wheels, nginx packages) is
  downloaded on an internet-connected staging machine and physically transferred
  into the offline network.

### Key features
- CTI-specialized system prompts per translation direction (incl. a two-hop
  Traditional → Simplified → English path for accuracy).
- **Placeholder substitution** that protects terms the model mistranslates
  (e.g. *reconnaissance*, *logging coverage*, *compromise*).
- **CTI scoring** on every result: glossary pass-rate + a Traditional vs.
  Simplified script check.

---

## Backend engine

The service runs `app_v3.py` — **llama-cpp-python with a GGUF Q5_K_M
quantised model** (~3 min/doc on CPU, ≥ 8 GB RAM).

Earlier transformer-based implementations (`app.py` float32, `app_v2.py`
bfloat16 + torch.compile) are kept in the repo for reference but are not
used in deployment.

---

## Repository layout

```
.
├── README.md                  ← you are here
├── REQUIREMENTS.md            bill of materials, acquisition + placement guide
├── DEPLOYMENT_RUNBOOK.md      step-by-step deploy + verification + troubleshooting
├── backend/                   → deploy to VM 2 and VM 3
│   ├── app_v3.py              FastAPI + llama-cpp-python, GGUF Q5_K_M (~3 min/doc)  ← active
│   ├── placeholder_utils.py   CTI term protect/restore substitution
│   ├── requirements_v3.txt    pinned deps (llama-cpp-python)                         ← active
│   ├── setup_v3.sh            venv + offline install + systemd service               ← active
│   ├── app.py                 [archive] V1: transformers, float32
│   ├── app_v2.py              [archive] V2: bfloat16 + torch.compile
│   ├── requirements.txt       [archive] V1/V2 deps (CPU-only torch)
│   ├── setup.sh               [archive] V1/V2 setup
│   └── wheels/                offline dependency wheels (not in git — see below)
│       └── DOWNLOAD_INSTRUCTIONS.md
├── frontend/                  → deploy to VM 1
│   ├── setup.sh               nginx install + UI deploy
│   ├── nginx.conf             reverse proxy + load balancer
│   └── ui/index.html          self-contained Google-Translate-style UI
└── staging/                   → run on an internet-connected machine
    ├── build_offline_bundle.sh      pin requirements_v3.txt + download wheels
    ├── download_model_gguf.sh       download Qwen2.5-7B GGUF Q5_K_M (~5.5 GB)      ← active
    └── download_model.sh            [archive] download safetensors weights (V1/V2)
```

> **Not included in this repo (by design):** the ~246 MB of dependency wheels and
> the ~15 GB model weights. They are binary payloads acquired on a staging
> machine — see `REQUIREMENTS.md`. Rebuild the wheels with
> `staging/build_offline_bundle.sh`.

---

## Where to start reading

A guided order from concept → requirements → implementation → deployment:

1. **`REQUIREMENTS.md`** — what you need, how to acquire it, and exactly where it
   goes. Includes the hardware reality (backend VMs need **≥32 GB RAM** for the
   7B float32 model) and the artifact placement matrix.
2. **`DEPLOYMENT_RUNBOOK.md`** — the operator's how-to: staging → model transfer
   → backend deploy → frontend deploy → verify → scale.
3. **`backend/app_v3.py`** — the heart of the implementation: endpoints, prompts,
   the llama-cpp-python inference pattern, paragraph splitting, and CTI scoring.
4. **`backend/placeholder_utils.py`** — the CTI term substitution module.
5. **`frontend/ui/index.html`** — the entire UI in one file (see the inline
   `<script>` for the `/api/translate` call shape).
6. **`frontend/nginx.conf`** — reverse proxy, load balancing, and the long
   timeouts that keep slow CPU inference alive.

**Fast path (90% understanding):** `REQUIREMENTS.md` → `DEPLOYMENT_RUNBOOK.md` →
`backend/app_v3.py`.

---

## Quick start (high level)

> Full, exact steps are in `REQUIREMENTS.md` and `DEPLOYMENT_RUNBOOK.md`.

1. **Stage** (internet machine, Ubuntu 24 / Python 3.12 / x86_64):
   ```bash
   cd staging
   ./build_offline_bundle.sh      # pins requirements_v3.txt + downloads wheels
   ./download_model_gguf.sh       # downloads Qwen2.5-7B GGUF Q5_K_M (~5.5 GB)
   ```
2. **Transfer** `backend/` (+ wheels + GGUF file) to VM 2 & VM 3, and
   `frontend/` to VM 1, per the placement matrix in `REQUIREMENTS.md`.
3. **Deploy** following `DEPLOYMENT_RUNBOOK.md`:
   - Backends: transfer GGUF to `~/models/`, run `backend/setup_v3.sh`, wait for `/health` → ready.
   - Frontend: set the real IPs in `nginx.conf`, run `frontend/setup.sh`.
4. **Use** it: open `http://FRONTEND_IP` in a browser.

---

## Requirements at a glance

| Node | RAM | Notes |
|------|-----|-------|
| Backend VM (×2) | **≥ 8 GB** | GGUF Q5_K_M is ~5.5 GB in RAM; 8 GB gives comfortable headroom. |
| Frontend VM | ~1 GB | nginx + static UI only. |
| Staging machine | ~2 GB | Downloads only; model is not loaded into RAM during staging. |

- **OS:** Ubuntu 24 LTS (Python 3.12) on all nodes.
- **CPU-only:** no GPU required; inference runs on CPU via llama-cpp-python.

---

## Notes

- **Latency:** ~3 minutes per document on CPU (GGUF Q5_K_M quantisation).
- **Scaling:** add a backend VM by deploying `backend/` on it and adding one
  line to the `upstream` block in `nginx.conf` (see the runbook).
