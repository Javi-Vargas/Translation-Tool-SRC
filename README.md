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

## Repository layout

```
.
├── README.md                  ← you are here
├── REQUIREMENTS.md            bill of materials, acquisition + placement guide
├── DEPLOYMENT_RUNBOOK.md      step-by-step deploy + verification + troubleshooting
├── backend/                   → deploy to VM 2 and VM 3
│   ├── app.py                 FastAPI app, model loading, /health + /translate, CTI scoring
│   ├── placeholder_utils.py   CTI term protect/restore substitution
│   ├── requirements.txt       pinned deps (Python 3.12, CPU-only torch)
│   ├── setup.sh               venv + offline install + systemd service
│   └── wheels/                offline dependency wheels (not in git — see below)
│       └── DOWNLOAD_INSTRUCTIONS.md
├── frontend/                  → deploy to VM 1
│   ├── setup.sh               nginx install + UI deploy
│   ├── nginx.conf             reverse proxy + load balancer
│   └── ui/index.html          self-contained Google-Translate-style UI
└── staging/                   → run on an internet-connected machine
    ├── build_offline_bundle.sh   pin requirements + download wheels
    └── download_model.sh         download Qwen2.5-7B weights
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
3. **`backend/app.py`** — the heart of the implementation: endpoints, prompts,
   the `generate()` pattern, paragraph splitting, and CTI scoring.
4. **`backend/placeholder_utils.py`** — the CTI term substitution module.
5. **`frontend/ui/index.html`** — the entire UI in one file (see the inline
   `<script>` for the `/api/translate` call shape).
6. **`frontend/nginx.conf`** — reverse proxy, load balancing, and the long
   timeouts that keep slow CPU inference alive.

**Fast path (90% understanding):** `REQUIREMENTS.md` → `DEPLOYMENT_RUNBOOK.md` →
`backend/app.py`.

---

## Quick start (high level)

> Full, exact steps are in `REQUIREMENTS.md` and `DEPLOYMENT_RUNBOOK.md`.

1. **Stage** (internet machine, Ubuntu 24 / Python 3.12 / x86_64):
   ```bash
   cd staging
   ./build_offline_bundle.sh   # pins requirements + downloads wheels
   ./download_model.sh         # downloads Qwen2.5-7B weights (~15 GB)
   ```
2. **Transfer** `backend/` (+ wheels + model cache) to VM 2 & VM 3, and
   `frontend/` to VM 1, per the placement matrix in `REQUIREMENTS.md`.
3. **Deploy** following `DEPLOYMENT_RUNBOOK.md`:
   - Backends: edit nothing, run `backend/setup.sh`, wait for `/health` → ready.
   - Frontend: set the real IPs in `nginx.conf`, run `frontend/setup.sh`.
4. **Use** it: open `http://FRONTEND_IP` in a browser.

---

## Requirements at a glance

| Node | RAM | Notes |
|------|-----|-------|
| Backend VM (×2) | **≥32 GB** | Qwen2.5-7B in `float32` is ~28 GB of weights. Below this it will OOM. |
| Frontend VM | ~1 GB | nginx + static UI only. |
| Staging machine | ~4 GB | Downloads only; the model is not loaded into RAM during staging. |

- **OS:** Ubuntu 24 LTS (Python 3.12) on all nodes.
- **CPU-only:** no GPU required; inference runs on CPU (expect minutes per
  document — see Notes).

---

## Notes

- **Latency:** ~3–5 minutes for ~2 paragraphs on CPU with `float32` — this is
  expected for the faithful configuration. Faster options (bf16, or a quantized
  GGUF runtime) are possible but intentionally not applied here.
- **Scaling:** add a backend VM by deploying `backend/` on it and adding one
  line to the `upstream` block in `nginx.conf` (see the runbook).
