"""
placeholder_utils.py — CTI term placeholder substitution.

Replaces known CTI terms with unique tokens BEFORE sending text to the model,
then restores the correct target-language equivalents AFTER translation. This
guarantees correct handling of terms the model translates inconsistently,
regardless of model behavior.

Priority targets (known failures observed during evaluation):
  - "reconnaissance"    fails EN->ZH, restore as 偵察
  - "logging coverage"  fails ZH->EN, restore as "logging coverage"
  - "compromise"        fails ZH->EN, restore as "compromise"

The full 11-term glossary is mapped in both directions to future-proof the
module — not just the three failing terms.

Token format: CTITERM001, CTITERM002, ...
Tokens are uppercase alphanumeric only — no underscores, dashes, or special
characters that could be altered by translation.
"""

import re

# ---------------------------------------------------------------------------
# Canonical bidirectional glossary.
#
# Each entry defines:
#   en        canonical English form to RESTORE to (target = English)
#   zh        canonical Traditional Chinese form to RESTORE to (target = Chinese)
#   en_match  English surface forms to DETECT in English source text
#   zh_match  Chinese surface forms to DETECT in Chinese source text
#
# Detection variants mirror the CTI glossaries in app.py.
# ---------------------------------------------------------------------------
CTI_TERMS = [
    {
        "en": "threat actor",
        "zh": "威脅行為者",
        "en_match": ["threat actors", "threat actor"],
        "zh_match": ["威脅行為者", "惡意行為者", "威脅者", "攻擊者"],
    },
    {
        "en": "credentials",
        "zh": "憑證",
        "en_match": ["credentials", "credential"],
        "zh_match": ["登入憑證", "帳號憑證", "認證資訊", "憑證"],
    },
    {
        "en": "phishing",
        "zh": "網路釣魚",
        "en_match": ["phishing"],
        "zh_match": ["網路釣魚", "網釣", "釣魚"],
    },
    {
        "en": "initial access",
        "zh": "初始存取",
        "en_match": ["initial access"],
        "zh_match": ["初始存取", "初始訪問", "初始接入"],
    },
    {
        "en": "reconnaissance",
        "zh": "偵察",
        "en_match": ["reconnaissance"],
        "zh_match": ["情報蒐集", "偵察", "勘察", "偵測"],
    },
    {
        "en": "logging coverage",
        "zh": "日誌覆蓋",
        "en_match": ["logging coverage"],
        "zh_match": ["日誌覆蓋範圍", "日誌記錄範圍", "記錄覆蓋", "日誌覆蓋"],
    },
    {
        "en": "MFA",
        "zh": "多因素驗證",
        "en_match": ["multi-factor authentication", "MFA"],
        "zh_match": ["多重要素驗證", "多因素驗證", "多因素認證", "多重驗證", "MFA"],
    },
    {
        "en": "ICS",
        "zh": "工業控制系統",
        "en_match": ["industrial control system", "ICS"],
        "zh_match": ["工業控制系統", "ICS"],
    },
    {
        "en": "OT",
        "zh": "營運技術",
        "en_match": ["operational technology", "OT"],
        "zh_match": ["營運技術", "操作技術", "運營技術", "OT"],
    },
    {
        "en": "compromise",
        "zh": "入侵成功",
        "en_match": ["compromised", "compromise"],
        "zh_match": ["遭受入侵", "入侵成功", "系統入侵", "遭入侵", "被入侵", "入侵"],
    },
    {
        "en": "intrusion",
        "zh": "入侵",
        "en_match": ["intrusion"],
        "zh_match": ["非法入侵", "網路入侵", "入侵"],
    },
]


def _is_english(lang: str) -> bool:
    return lang == "English"


def _is_chinese(lang: str) -> bool:
    return lang in ("Traditional Chinese", "Simplified Chinese")


def _make_token(index: int) -> str:
    return f"CTITERM{index:03d}"


def substitute_before(text: str, src_lang: str, tgt_lang: str) -> tuple[str, dict]:
    """
    Replace CTI terms in source text with unique tokens.

    Detection is driven by the SOURCE language surface forms; the substitution
    map records the TARGET language term to restore to.

    Returns (modified_text, sub_map) where sub_map maps token -> target term.
    """
    sub_map: dict[str, str] = {}

    # Choose detection forms (source side) and restore forms (target side).
    if _is_english(src_lang):
        match_key = "en_match"
    elif _is_chinese(src_lang):
        match_key = "zh_match"
    else:
        return text, sub_map  # unsupported source — no substitution

    if _is_english(tgt_lang):
        restore_key = "en"
    elif _is_chinese(tgt_lang):
        restore_key = "zh"
    else:
        return text, sub_map  # unsupported target — no substitution

    token_index = 1
    for entry in CTI_TERMS:
        # Longest surface forms first so "threat actors" wins over "threat actor".
        variants = sorted(entry[match_key], key=len, reverse=True)
        replaced_this_term = False
        token = _make_token(token_index)

        for variant in variants:
            if _is_english(src_lang):
                pattern = re.compile(re.escape(variant), re.IGNORECASE)
                if pattern.search(text):
                    text = pattern.sub(token, text)
                    replaced_this_term = True
            else:
                if variant in text:
                    text = text.replace(variant, token)
                    replaced_this_term = True

        if replaced_this_term:
            sub_map[token] = entry[restore_key]
            token_index += 1

    return text, sub_map


def substitute_after(text: str, sub_map: dict, tgt_lang: str) -> str:
    """
    Replace tokens in translated text with correct target-language terms.

    The model occasionally lowercases or spaces tokens; we match the canonical
    uppercase token first, then fall back to a case-insensitive match.
    """
    for token, replacement in sub_map.items():
        if token in text:
            text = text.replace(token, replacement)
        else:
            text = re.sub(re.escape(token), replacement, text, flags=re.IGNORECASE)
    return text
