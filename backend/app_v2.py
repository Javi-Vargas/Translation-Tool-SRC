"""
app_v2.py — CTI Translation Service backend, V2 (bfloat16 + torch.compile).

Changes from V1 (app.py):
  - torch_dtype changed from float32 → bfloat16 (halves model RAM, enables
    half-precision arithmetic on CPU).
  - torch.compile() wraps the model after loading (triggers TorchInductor JIT
    on the first inference call; subsequent calls use the compiled graph).

Combined effect: ~1.5–2× speedup over V1 with no accuracy regression observed
on the CTI translation eval set.

See app_v3.py for the further step to llama-cpp-python + GGUF Q5_K_M (~3 min).

Run:
    uvicorn app_v2:app --host 0.0.0.0 --port 8000
"""

import os

os.environ.setdefault("HUGGINGFACE_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import threading
from contextlib import asynccontextmanager

import torch
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer

from placeholder_utils import substitute_after, substitute_before

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"

SUPPORTED_LANGUAGES = [
    "English",
    "Traditional Chinese",
    "Simplified Chinese",
]

MAX_NEW_TOKENS = 512

# ---------------------------------------------------------------------------
# Global model state
# ---------------------------------------------------------------------------
model = None
tokenizer = None
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
# Model loading / inference  (V2 changes are here)
# ---------------------------------------------------------------------------
def _load_model() -> None:
    global model, tokenizer, model_ready, _load_error
    try:
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_NAME,
            torch_dtype=torch.bfloat16,  # V2: was float32
        )
        model.eval()
        model = torch.compile(model)  # V2: JIT-compile the graph; first call triggers compile
        model_ready = True
    except Exception as exc:  # noqa: BLE001 — surface any load failure via /health
        _load_error = str(exc)


def run_model(system_prompt: str, prompt: str) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    formatted = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = tokenizer(formatted, return_tensors="pt")
    prompt_len = inputs["input_ids"].shape[1]

    with torch.no_grad():
        output_tokens = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )

    new_tokens = output_tokens[0][prompt_len:]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


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
    thread = threading.Thread(target=_load_model, daemon=True)
    thread.start()
    yield


app = FastAPI(title="CTI Translation Service (V2)", lifespan=lifespan)


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
