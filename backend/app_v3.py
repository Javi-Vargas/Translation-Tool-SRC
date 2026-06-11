"""
app_v3.py — CTI Translation Service backend, V3 (llama-cpp-python + GGUF Q5_K_M).

Replaces the transformers + PyTorch stack (V1/V2) entirely with llama-cpp-python,
loading a pre-quantised Q5_K_M GGUF file.

Why this is faster:
  - GGUF Q5_K_M is ~5.5 bits/weight vs 32 (V1) or 16 (V2) bits/weight.
    The model fits in ~5 GB RAM instead of ~14–28 GB.
  - llama-cpp's highly optimised GGML kernels outperform PyTorch on CPU for
    autoregressive generation.
  - No torch.compile warm-up penalty on the first request.

Observed: ~3 minutes per document (down from ~5 min V1 and ~3–4 min V2).

Model file required (single GGUF, ~5.5 GB):
    qwen2.5-7b-instruct-q5_k_m.gguf
    Download with:  staging/download_model_gguf.sh
    Transfer to VM: ~/models/qwen2.5-7b-instruct-q5_k_m.gguf
    Override path:  export GGUF_MODEL_PATH=/path/to/file.gguf

Run:
    uvicorn app_v3:app --host 0.0.0.0 --port 8000
"""

import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from llama_cpp import Llama
from pydantic import BaseModel

from placeholder_utils import substitute_after, substitute_before

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODEL_PATH = os.environ.get(
    "GGUF_MODEL_PATH",
    os.path.expanduser("~/models/qwen2.5-7b-instruct-q5_k_m-00001-of-00002.gguf"),
)

# Use all physical cores by default; override with MODEL_THREADS env var.
N_THREADS = int(os.environ.get("MODEL_THREADS", os.cpu_count() or 8))

SUPPORTED_LANGUAGES = [
    "English",
    "Traditional Chinese",
    "Simplified Chinese",
]

MAX_NEW_TOKENS = 512

# ---------------------------------------------------------------------------
# Global model state
# ---------------------------------------------------------------------------
llm: Llama | None = None
model_ready = False
_load_error: str | None = None

# ---------------------------------------------------------------------------
# System prompts per direction
# ---------------------------------------------------------------------------
SYS_EN_TO_TC_DIRECT = (
    "You are a professional translator specialising in cybersecurity and threat "
    "intelligence.\n"
    "Translate text accurately, preserving all technical terminology exactly as "
    "written.\n"
    "When translating into Traditional Chinese, always use Traditional Chinese "
    "characters\n"
    "as used in Taiwan — never Simplified Chinese characters."
)

SYS_TC_TO_EN_TWOHOP = (
    "You are a professional translator specialising in cybersecurity and threat "
    "intelligence.\n"
    "When translating from Traditional Chinese to English, first convert the text "
    "into\n"
    "Simplified Chinese as an internal intermediate step, then translate the "
    "Simplified Chinese\n"
    "into English.\n"
    "Output only the final English result.\n"
    "Preserve all technical terminology exactly."
)

SYS_GENERIC = (
    "You are a professional translator specialising in cybersecurity and threat "
    "intelligence.\n"
    "Translate text accurately, preserving all technical terminology exactly as "
    "written."
)

PROMPT_TEMPLATE = (
    "Translate the following text from {src_lang} to {tgt_lang}.\n"
    "Output only the translation, nothing else.\n"
    "\n"
    "Text:\n"
    "{text}\n"
    "\n"
    "Translation:"
)


def select_system_prompt(src_lang: str, tgt_lang: str) -> str:
    if src_lang == "English" and tgt_lang == "Traditional Chinese":
        return SYS_EN_TO_TC_DIRECT
    if src_lang == "Traditional Chinese" and tgt_lang == "English":
        return SYS_TC_TO_EN_TWOHOP
    return SYS_GENERIC


# ---------------------------------------------------------------------------
# CTI scoring glossaries
# ---------------------------------------------------------------------------
CTI_GLOSSARY_EN = {
    "threat actor":     ["threat actor"],
    "credentials":      ["credentials", "credential"],
    "phishing":         ["phishing"],
    "initial access":   ["initial access"],
    "reconnaissance":   ["reconnaissance"],
    "logging coverage": ["logging coverage"],
    "MFA":              ["MFA", "multi-factor authentication"],
    "ICS":              ["ICS", "industrial control system"],
    "OT":               ["OT", "operational technology"],
    "compromise":       ["compromise", "compromised"],
    "intrusion":        ["intrusion"],
}

CTI_GLOSSARY_ZH = {
    "threat actor":     ["威脅行為者", "威脅者", "攻擊者", "惡意行為者"],
    "credentials":      ["憑證", "帳號憑證", "認證資訊", "登入憑證"],
    "phishing":         ["網路釣魚", "釣魚", "網釣"],
    "initial access":   ["初始存取", "初始訪問", "初始接入"],
    "reconnaissance":   ["偵察", "勘察", "情報蒐集", "偵測"],
    "logging coverage": ["日誌覆蓋", "日誌覆蓋範圍", "記錄覆蓋", "日誌記錄範圍"],
    "MFA":              ["MFA", "多因素驗證", "多重要素驗證", "多因素認證", "多重驗證"],
    "ICS":              ["ICS", "工業控制系統"],
    "OT":               ["OT", "營運技術", "操作技術", "運營技術"],
    "compromise":       ["入侵成功", "遭入侵", "遭受入侵", "被入侵", "入侵", "系統入侵"],
    "intrusion":        ["入侵", "非法入侵", "網路入侵"],
}


def check_cti_terms(text: str, tgt_lang: str) -> tuple[str, dict]:
    """Return (pass_rate "n/m", {term: PASS|FAIL}) for the target language."""
    glossary = CTI_GLOSSARY_EN if tgt_lang == "English" else CTI_GLOSSARY_ZH
    lower = text.lower()
    results: dict[str, str] = {}
    passes = 0
    for term, variants in glossary.items():
        found = False
        for variant in variants:
            if tgt_lang == "English":
                if variant.lower() in lower:
                    found = True
                    break
            else:
                if variant in text:
                    found = True
                    break
        results[term] = "PASS" if found else "FAIL"
        if found:
            passes += 1
    return f"{passes}/{len(glossary)}", results


def script_check(text: str) -> str:
    """Detect whether Chinese text is Traditional or Simplified."""
    simplified_markers = set("国来时这说为样动产实统气电")
    traditional_markers = set("國來時這說為樣動產實統氣電")
    simp = sum(1 for c in text if c in simplified_markers)
    trad = sum(1 for c in text if c in traditional_markers)
    if simp > trad:
        return "WRONG - Simplified Chinese detected"
    elif trad > simp:
        return "CORRECT - Traditional Chinese"
    else:
        return "UNCERTAIN - Mixed or insufficient markers"


# ---------------------------------------------------------------------------
# Model loading / inference  (V3: llama-cpp-python replaces torch+transformers)
# ---------------------------------------------------------------------------
def _load_model() -> None:
    global llm, model_ready, _load_error
    try:
        llm = Llama(
            model_path=MODEL_PATH,
            n_ctx=4096,        # sufficient for paragraph-by-paragraph translation
            n_threads=N_THREADS,
            chat_format="chatml",  # Qwen2.5 uses the ChatML template
            verbose=False,
        )
        model_ready = True
    except Exception as exc:  # noqa: BLE001 — surface any load failure via /health
        _load_error = str(exc)


def run_model(system_prompt: str, prompt: str) -> str:
    response = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        max_tokens=MAX_NEW_TOKENS,
        temperature=0.0,
    )
    return response["choices"][0]["message"]["content"].strip()


def translate_document(
    source_text: str, src_lang: str, tgt_lang: str, use_placeholder: bool
) -> str:
    """Split into paragraphs, translate each, rejoin. Prevents truncation."""
    system_prompt = select_system_prompt(src_lang, tgt_lang)
    paragraphs = source_text.split("\n\n")
    translated: list[str] = []

    for para in paragraphs:
        if not para.strip():
            translated.append("")
            continue

        work = para
        sub_map: dict = {}
        if use_placeholder:
            work, sub_map = substitute_before(work, src_lang, tgt_lang)

        prompt = PROMPT_TEMPLATE.format(
            src_lang=src_lang, tgt_lang=tgt_lang, text=work
        )
        result = run_model(system_prompt, prompt)

        if use_placeholder:
            result = substitute_after(result, sub_map, tgt_lang)

        translated.append(result)

    return "\n\n".join(translated)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # llama-cpp loads the GGUF by memory-mapping it — typically a few seconds,
    # not minutes, so /health turns ready quickly.
    thread = threading.Thread(target=_load_model, daemon=True)
    thread.start()
    yield


app = FastAPI(title="CTI Translation Service (V3)", lifespan=lifespan)


class TranslateRequest(BaseModel):
    source_text: str
    source_lang: str
    target_lang: str
    use_placeholder: bool = True


@app.get("/health")
def health():
    if model_ready:
        return JSONResponse({"status": "ready"}, status_code=200)
    if _load_error is not None:
        return JSONResponse(
            {"status": "error", "detail": _load_error}, status_code=503
        )
    return JSONResponse({"status": "loading"}, status_code=503)


@app.post("/translate")
def translate(req: TranslateRequest):
    if not model_ready:
        return JSONResponse(
            {"detail": "Model is not ready yet. Try again shortly."},
            status_code=503,
        )

    if req.source_lang not in SUPPORTED_LANGUAGES:
        return JSONResponse(
            {"detail": f"Unsupported source_lang: {req.source_lang}"},
            status_code=400,
        )
    if req.target_lang not in SUPPORTED_LANGUAGES:
        return JSONResponse(
            {"detail": f"Unsupported target_lang: {req.target_lang}"},
            status_code=400,
        )

    try:
        translation = translate_document(
            req.source_text,
            req.source_lang,
            req.target_lang,
            req.use_placeholder,
        )
    except Exception as exc:  # noqa: BLE001 — report inference failure to client
        return JSONResponse(
            {"detail": f"Inference error: {exc}"}, status_code=500
        )

    pass_rate, cti_terms = check_cti_terms(translation, req.target_lang)

    if req.target_lang in ("Traditional Chinese", "Simplified Chinese"):
        script_result = script_check(translation)
    else:
        script_result = "N/A - non-Chinese output"

    return {
        "translation": translation,
        "source_lang": req.source_lang,
        "target_lang": req.target_lang,
        "cti_pass_rate": pass_rate,
        "script_check": script_result,
        "cti_terms": cti_terms,
    }
