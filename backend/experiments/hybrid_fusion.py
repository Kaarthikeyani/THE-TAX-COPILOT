"""Fuse the ML model's probabilities with the LLM's answer. Rule and weight are chosen on the VALIDATION split only
(ML trained on train only for that), then the TEST split is scored once with the model trained on train+val.

    p_final(class) = p_ml(class) + w * [class == llm_answer]        (llm_answer ignored if it is None)
    optional: when the LLM says 'uncategorized' it counts as an abstention (weight w_abstain, usually 0).

    python experiments/hybrid_fusion.py
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
from experiments.common import prepare, restricted_proba  # noqa: E402
from experiments.hybrid_llm import LLM_FILE, load, scores  # noqa: E402

RES = ROOT / "experiments" / "results"


def fuse(P, classes, llm_answers, w, w_abstain):
    idx = {c: i for i, c in enumerate(classes)}
    out = []
    for row, a in zip(P, llm_answers):
        r = row.copy()
        if a in idx:
            r[idx[a]] += (w_abstain if a == "uncategorized" else w)
        out.append(classes[int(r.argmax())])
    return out


def probs(model, rows, llm):
    X, d, _ = prepare(rows)
    P, classes = restricted_proba(model, X, d)
    return P, classes, [llm.get(f"{dd}|{x}") for x, dd in zip(X, d)], [r["category"] for r in rows]


def main():
    tr, va, te = load("train"), load("val"), load("test")
    llm = json.loads(LLM_FILE.read_text(encoding="utf-8"))
    m_val = build("logreg", {"C": 3.0}).fit(prepare(tr)[0], [r["category"] for r in tr])
    Pv, classes, lv, yv = probs(m_val, va, llm)
    grid = [(w, wa) for w in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 5.0) for wa in (0.0, 0.1, 0.2, 0.4, 0.6)]
    curve = []
    for w, wa in grid:
        p = fuse(Pv, classes, lv, w, wa)
        curve.append({"w": w, "w_abstain": wa, "val_accuracy": round(float(np.mean([a == b for a, b in zip(yv, p)])), 4)})
    best = max(curve, key=lambda r: (r["val_accuracy"], -r["w"]))
    m_full = build("logreg", {"C": 3.0}).fit(prepare(tr + va)[0], [r["category"] for r in tr + va])
    Pt, classes_t, lt, yt = probs(m_full, te, llm)
    labels = sorted(set(yt) | set(classes_t))
    pt = fuse(Pt, classes_t, lt, best["w"], best["w_abstain"])
    out = {"chosen_on_validation": best, "validation_curve_top5": sorted(curve, key=lambda r: -r["val_accuracy"])[:5],
           "test_fusion": scores(yt, pt, labels)}
    (RES / "hybrid_fusion.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
