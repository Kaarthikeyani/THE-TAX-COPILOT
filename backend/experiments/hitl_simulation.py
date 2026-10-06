"""Human-in-the-loop simulation: how does accuracy and user effort evolve as the app learns from corrections?

   python experiments/hitl_simulation.py            (run from backend/, after run_experiments.py)

Stream: the TEST messages in random order (5 shuffles). For every message the app answers from its merchant memory (if the
user has taught it this merchant or a close spelling) or else from the shipped model. A message whose confidence is below
the threshold chosen on VALIDATION is flagged "please review". The simulated user reviews each flagged message with
probability r (default 0.7: people skip some), fixing the category, which is stored in memory (same code as the app).
Unflagged mistakes stay silently wrong. SYNTHETIC data, simulated user: it shows the mechanism and its size, not a promise.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.classifier import normalize_merchant  # noqa: E402
from app.merchant_memory import MerchantMemory  # noqa: E402
from app.model_registry import build  # noqa: E402
from experiments.common import predict, prepare  # noqa: E402
from experiments.run_experiments import RES, load_seed0  # noqa: E402


def simulate(model, X, d, y, tau, review_p, seed, use_memory=True):
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(X))
    mem = MerchantMemory()
    pred_all, conf_all, _, classes = None, None, None, None
    pred_all, conf_all, P, classes = predict(model, X, d)
    final, flagged, silent_err, corrections = [], [], [], 0
    log = []
    for n, i in enumerate(order, 1):
        key = normalize_merchant(X[i])
        hit = mem.lookup(key, d[i]) if use_memory else None
        if hit:
            pred, conf = hit[0], 0.99
        else:
            pred, conf = pred_all[i], conf_all[i]
        flag = conf < tau
        if flag and rng.random() < review_p:
            if pred != y[i]:
                corrections += 1
            mem.learn(key, d[i], y[i])
            final.append(y[i])
        else:
            final.append(pred)
        flagged.append(flag)
        silent_err.append((not flag) and pred != y[i])
        log.append((pred == y[i], flag))
    return final, np.array(flagged), np.array(silent_err), corrections, order


def main():
    summ = json.loads((RES / "summary.json").read_text())
    name, params = summ["selected"]["name"], summ["selected"]["params"]
    tau = summ["operating_point"]["threshold"]
    data = load_seed0()
    Xtr, dtr, _ = prepare(data["train"] + data["val"])
    Xte, dte, _ = prepare(data["test"])
    ytr = [r["category"] for r in data["train"] + data["val"]]
    yte = [r["category"] for r in data["test"]]
    model = build(name, params).fit(Xtr, ytr)
    out = {"model": name, "threshold_from_validation": tau, "reviewer_probability": 0.7, "messages": len(yte), "variants": {}}
    for label, use_mem in (("with merchant memory", True), ("without memory (user fixes, app never learns)", False)):
        curves = {"silent_error": [], "flagged": [], "final_acc": []}
        for seed in range(5):
            final, flagged, silent, corr, order = simulate(model, Xte, dte, yte, tau, 0.7, seed, use_memory=use_mem)
            ys = np.array(yte)[order]
            fa = (np.array(final) == ys)
            n = len(ys)
            cuts = [int(n * f) for f in (0.2, 0.4, 0.6, 0.8, 1.0)]
            prev = 0
            row_s, row_f, row_a = [], [], []
            for c in cuts:
                row_s.append(float(silent[prev:c].mean())), row_f.append(float(flagged[prev:c].mean())), row_a.append(float(fa[prev:c].mean()))
                prev = c
            curves["silent_error"].append(row_s), curves["flagged"].append(row_f), curves["final_acc"].append(row_a)
        out["variants"][label] = {k: [round(float(np.mean([r[i] for r in v])), 4) for i in range(5)] for k, v in curves.items()}
    out["stages"] = ["messages 0-20%", "20-40%", "40-60%", "60-80%", "80-100%"]
    (RES / "hitl.json").write_text(json.dumps(out, indent=1))
    for k, v in out["variants"].items():
        print(k)
        for m, vals in v.items():
            print("  ", m, vals)


if __name__ == "__main__":
    main()
