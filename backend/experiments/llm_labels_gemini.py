"""Same job as llm_labels.py, with Gemini and BATCHING so the free quota is enough (about 45 requests, not 1,656).
UNTESTED against the live API (needs your key). The parser is unit-tested offline.

    set GEMINI_API_KEY=your-key            (Command Prompt)      optional: set COPILOT_GEMINI_MODEL=gemini-flash-latest
    python experiments/llm_labels_gemini.py
    set LLM_LABELS=llm_labels_gemini.json
    python experiments/hybrid_llm.py ; python experiments/hybrid_fusion.py

Same prompt wording and the same category lists as llm_labels.py; only the format changes (many merchants per request).
"""
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from app.classifier import CATEGORY_META  # noqa: E402
from experiments.common import prepare  # noqa: E402

KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("COPILOT_GEMINI_MODEL", "gemini-flash-latest")
OUT = ROOT / "experiments" / "results" / "llm_labels_gemini.json"
BATCH = 40


def allowed(direction):
    return [k for k, v in CATEGORY_META.items() if (v[2] == "income") == (direction == "credit")]


def prompt_for(direction, merchants):
    ids = allowed(direction)
    cats = "\n".join(f"{k}: {CATEGORY_META[k][0]}" for k in ids)
    items = "\n".join(f"{i + 1}. {m!r}" for i, m in enumerate(merchants))
    return ("Classify each Indian bank transaction by what the money was FOR.\n"
            f"Direction for all of them: money {'IN' if direction == 'credit' else 'OUT'}\n"
            f"Categories (id: meaning):\n{cats}\n\nMerchant texts:\n{items}\n\n"
            'Answer with ONLY a JSON array of exactly %d category ids, in the same order, for example ["groceries","fuel"].' % len(merchants))


def parse_reply(text, direction, n):
    """-> list of n category ids or None each. Tolerates code fences and extra words."""
    ids = set(allowed(direction))
    m = re.search(r"\[.*\]", text, re.S)
    try:
        arr = json.loads(m.group(0)) if m else []
    except Exception:
        arr = []
    out = [(a.strip().lower() if isinstance(a, str) and a.strip().lower() in ids else None) for a in arr[:n]]
    return out + [None] * (n - len(out))


def call(prompt):
    r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent", timeout=120,
                   headers={"x-goog-api-key": KEY, "content-type": "application/json"},
                   json={"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                         "generationConfig": {"temperature": 0, "maxOutputTokens": 2048}})
    r.raise_for_status()
    parts = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def main():
    if not KEY:
        sys.exit("Set GEMINI_API_KEY first.")
    cache = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    keys = set()
    for split in ("val", "test"):
        rows = list(csv.DictReader(open(f"data/synthetic/{split}.csv", encoding="utf-8")))
        X, dirs, _ = prepare(rows)
        keys |= {f"{d}|{x}" for x, d in zip(X, dirs)}
    for direction in ("debit", "credit"):
        todo = sorted(k for k in keys if k.startswith(direction + "|") and cache.get(k) is None)
        for i in range(0, len(todo), BATCH):
            chunk = todo[i:i + BATCH]
            merchants = [k.split("|", 1)[1] for k in chunk]
            try:
                answers = parse_reply(call(prompt_for(direction, merchants)), direction, len(chunk))
            except Exception as e:
                print("batch failed, will retry on next run:", e, flush=True)
                time.sleep(15)
                continue
            for k, a in zip(chunk, answers):
                cache[k] = a
            OUT.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            print(direction, i + len(chunk), "/", len(todo), flush=True)
            time.sleep(8)  # stay under the free-tier requests-per-minute limit
    print("done", OUT, flush=True)


if __name__ == "__main__":
    main()
