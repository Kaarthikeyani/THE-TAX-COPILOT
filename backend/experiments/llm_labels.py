"""Ask a language model to classify each unique (merchant text, direction) in the validation and test splits.

Run once, resumable (results are cached in experiments/results/llm_labels_<model>.json):
    python experiments/llm_labels.py                 # uses the local Ollama model
The prompt below is FIXED before the test split is scored. It lists only the categories allowed for the message's
direction (money in -> income categories, money out -> the rest), exactly as the app restricts its ML model.
experiments/hybrid_llm.py then combines these answers with the ML model and scores the test split once.
"""
import csv
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from app.classifier import CATEGORY_META  # noqa: E402
from experiments.common import prepare  # noqa: E402

HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL = os.environ.get("COPILOT_LLM_MODEL") or httpx.get(HOST + "/api/tags", timeout=5).json()["models"][0]["name"]
OUT = ROOT / "experiments" / "results" / f"llm_labels_{MODEL.replace(':', '_')}.json"

PROMPT = ("Classify this Indian bank transaction by what the money was FOR.\n"
          "Merchant text: {m!r}\nDirection: money {d}\nCategories (id: meaning):\n{cats}\nAnswer with ONLY the category id.")


def allowed(direction):
    return [k for k, v in CATEGORY_META.items() if (v[2] == "income") == (direction == "credit")]


def ask(merchant, direction):
    ids = allowed(direction)
    cats = "\n".join(f"{k}: {CATEGORY_META[k][0]}" for k in ids)
    body = {"model": MODEL, "stream": False, "think": False, "options": {"temperature": 0, "num_predict": 20},
            "messages": [{"role": "user", "content": PROMPT.format(m=merchant, d="IN" if direction == "credit" else "OUT", cats=cats)}]}
    txt = httpx.post(HOST + "/api/chat", json=body, timeout=300).json()["message"]["content"].strip().lower()
    for k in ids:  # accept the id even if wrapped in quotes or a sentence
        if k in txt:
            return k
    return None


def main():
    cache = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    keys = []
    for split in ("val", "test"):
        rows = list(csv.DictReader(open(f"data/synthetic/{split}.csv", encoding="utf-8")))
        X, dirs, _ = prepare(rows)
        keys += [f"{d}|{x}" for x, d in zip(X, dirs)]
    keys = sorted(set(keys))
    todo = [k for k in keys if k not in cache]
    print(f"model {MODEL}: {len(keys)} unique merchant texts, {len(todo)} still to ask", flush=True)
    t0 = time.time()
    for i, k in enumerate(todo, 1):
        d, m = k.split("|", 1)
        try:
            cache[k] = ask(m, d)
        except Exception as e:
            print("error", k, e, flush=True)
            time.sleep(5)
            continue
        if i % 25 == 0:
            OUT.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            print(f"{i}/{len(todo)}  {time.time() - t0:.0f}s", flush=True)
    OUT.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    print("done", OUT, flush=True)


if __name__ == "__main__":
    main()
