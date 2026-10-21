"""ML model + LLM fallback, scored with the same honest protocol as the other experiments.

  1. Train the shipped model (logistic regression, C=3) on train+val of the synthetic corpus, exactly as the app does.
  2. On the VALIDATION split only, choose the confidence threshold where the ML model hands a message to the LLM.
     (The LLM answers come from experiments/llm_labels.py, which uses one fixed prompt.)
  3. Score the TEST split once with that threshold. No test label is used to choose anything.
Also reports: ML alone, LLM alone, and the share of messages sent to the LLM. Writes results/hybrid_llm.json.

    python experiments/hybrid_llm.py
"""
import csv
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from app.model_registry import build  # noqa: E402
from experiments.common import prepare, predict, prf, wilson, mcc  # noqa: E402

RES = ROOT / "experiments" / "results"
LLM_FILE = RES / os.environ.get("LLM_LABELS", "llm_labels_gemma4_latest.json")  # set LLM_LABELS=llm_labels_gemini.json to score another model


def load(n):
    return list(csv.DictReader(open(f"data/synthetic/{n}.csv", encoding="utf-8")))


def scores(y, p, labels):
    acc = float(np.mean([a == b for a, b in zip(y, p)]))
    P, R, F, _ = prf(y, p, labels, average="macro")
    return {"accuracy": round(acc, 4), "macro_precision": round(P, 4), "macro_recall": round(R, 4), "macro_f1": round(F, 4),
            "mcc": round(mcc(y, p, labels), 4), "wilson95": [round(x, 4) for x in wilson(int(round(acc * len(y))), len(y))]}


def main():
    tr, va, te = load("train"), load("val"), load("test")
    llm = json.loads(LLM_FILE.read_text(encoding="utf-8"))
    Xtr, dtr, _ = prepare(tr + va)
    model = build("logreg", {"C": 3.0}).fit(Xtr, [r["category"] for r in tr + va])
    # for the threshold we need a model that did NOT train on val: train on train only
    m_val = build("logreg", {"C": 3.0}).fit(prepare(tr)[0], [r["category"] for r in tr])

    def run(rows, mdl):
        X, d, _ = prepare(rows)
        pred, conf, _, classes = predict(mdl, X, d)
        lp = [llm.get(f"{dd}|{x}") for x, dd in zip(X, d)]
        return [r["category"] for r in rows], pred, conf, lp, classes

    yv, pv, cv, lv, classes = run(va, m_val)
    labels = sorted(set(yv) | set(classes))
    grid = [round(t, 2) for t in np.arange(0.0, 1.01, 0.05)]
    table = []
    for t in grid:
        hyb = [(l if (c < t and l) else p) for p, c, l in zip(pv, cv, lv)]
        table.append({"threshold": t, "val_accuracy": round(float(np.mean([a == b for a, b in zip(yv, hyb)])), 4),
                      "share_to_llm": round(float(np.mean([c < t and bool(l) for c, l in zip(cv, lv)])), 3)})
    best = max(table, key=lambda r: (r["val_accuracy"], -r["share_to_llm"]))
    t = best["threshold"]

    yt, pt, ct, lt, _ = run(te, model)
    hyb = [(l if (c < t and l) else p) for p, c, l in zip(pt, ct, lt)]
    llm_only = [l or p for p, l in zip(pt, lt)]
    out = {"llm_file": LLM_FILE.name, "threshold_chosen_on_validation": t, "validation_curve": table,
           "test": {"ml_only": scores(yt, pt, labels), "llm_only": scores(yt, llm_only, labels), "hybrid": scores(yt, hyb, labels),
                    "share_sent_to_llm": round(float(np.mean([c < t and bool(l) for c, l in zip(ct, lt)])), 3),
                    "llm_unanswered": int(sum(1 for l in lt if not l))}}
    (RES / "hybrid_llm.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out["test"], indent=1))
    print("threshold", t, "(val acc", best["val_accuracy"], ")")


if __name__ == "__main__":
    main()
