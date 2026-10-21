"""Optional third classification tier: ask a language model about a merchant the ML model is unsure of, then fuse its
answer with the ML probabilities.   Turn on with COPILOT_LLM_CLASSIFY=1.

Measured on the synthetic unseen-merchant test split (experiments/hybrid_fusion.py; weights chosen on validation only,
local gemma4 as the LLM): accuracy 69.8% -> 82.4%, macro precision 72.8% -> 84.8%, macro recall 70.8% -> 82.5%.

    p_final(class) = p_ml(class) + W * [class == llm_answer]      W = 0.8, or 0.1 if the LLM answers "uncategorized"

Only the merchant text and the direction (money in or out) are sent, never the amount, balance, account or full SMS.
Providers, in order: Gemini (GEMINI_API_KEY), Claude (ANTHROPIC_API_KEY), local Ollama. Answers are cached per
(direction, merchant) so a repeat merchant costs nothing. A daily cap (COPILOT_LLM_CLASSIFY_CAP, default 500) protects free quotas.
With a cloud provider the merchant text leaves this server, so use it only with demo or consented data.
"""
import os
from datetime import date

import httpx

from .classifier import CATEGORY_META

W_LLM = 0.8
W_ABSTAIN = 0.1
SKIP_ABOVE = 0.9  # a class the ML model is already 90% sure of cannot be overturned by W=0.8, so don't spend a call
PROMPT = ("Classify this Indian bank transaction by what the money was FOR.\n"
          "Merchant text: {m!r}\nDirection: money {d}\nCategories (id: meaning):\n{cats}\nAnswer with ONLY the category id.")

_cache: dict = {}
_calls = {"day": None, "n": 0}


def enabled() -> bool:
    return os.environ.get("COPILOT_LLM_CLASSIFY") == "1"


def _under_cap() -> bool:
    today = date.today()
    if _calls["day"] != today:
        _calls.update(day=today, n=0)
    if _calls["n"] >= int(os.environ.get("COPILOT_LLM_CLASSIFY_CAP", "500")):
        return False
    _calls["n"] += 1
    return True


def allowed_ids(txn_type: str) -> list:
    return [k for k, v in CATEGORY_META.items() if (v[2] == "income") == (txn_type == "credit")]


def _complete(prompt: str) -> str:
    gkey, ckey = os.environ.get("GEMINI_API_KEY", "").strip(), os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if gkey:
        model = os.environ.get("COPILOT_GEMINI_MODEL", "gemini-flash-latest")
        r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", timeout=15.0,
                       headers={"x-goog-api-key": gkey, "content-type": "application/json"},
                       json={"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                             "generationConfig": {"temperature": 0, "maxOutputTokens": 40}})
        r.raise_for_status()
        parts = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if ckey:
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=15.0,
                       headers={"x-api-key": ckey, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                       json={"model": os.environ.get("COPILOT_AI_MODEL", "claude-sonnet-5-5"), "max_tokens": 20, "temperature": 0,
                             "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    from . import assistant  # local Ollama, if one is installed
    model = assistant._pick_model()
    if not model:
        return ""
    r = httpx.post(assistant.HOST() + "/api/chat", timeout=60.0,
                   json={"model": model, "stream": False, "think": False, "options": {"temperature": 0, "num_predict": 20},
                         "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    return r.json().get("message", {}).get("content", "")


def llm_answer(text: str, txn_type: str):
    """The model's category id for this merchant, or None (disabled, no provider, over the cap, or an unusable reply)."""
    if not enabled() or not text:
        return None
    key = (txn_type, text.strip().upper())
    if key in _cache:
        return _cache[key]
    if not _under_cap():
        return None
    ids = allowed_ids(txn_type)
    cats = "\n".join(f"{k}: {CATEGORY_META[k][0]}" for k in ids)
    try:
        reply = _complete(PROMPT.format(m=text, d="IN" if txn_type == "credit" else "OUT", cats=cats)).strip().lower()
    except Exception:
        return None  # never block ingestion because a provider is down; the ML answer stands
    ans = next((k for k in ids if k in reply), None)
    _cache[key] = ans
    return ans


def fuse(probs: dict, answer):
    """probs: class -> ML probability renormalised over the allowed classes. Returns (best class, confidence 0-1)."""
    p = dict(probs)
    if answer in p:
        p[answer] += W_ABSTAIN if answer == "uncategorized" else W_LLM
    best = max(p, key=p.get)
    scale = 1.0 + (W_ABSTAIN if answer == "uncategorized" else W_LLM if answer in p else 0.0)
    return best, round(min(1.0, p[best] / scale), 2)
