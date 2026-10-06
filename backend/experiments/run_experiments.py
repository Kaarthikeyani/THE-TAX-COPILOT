"""Model comparison, ablations, calibration, learning curve and split-robustness, on the SYNTHETIC corpus.

   python experiments/run_experiments.py              (run from backend/; ~20-30 min on 2 CPU cores)
   python experiments/run_experiments.py --quick      (seed 0 only, fewer models; for a smoke test)

PROTOCOL (nothing here is tuned on the test split)
  1. Corpus split by merchant entity into train / validation / test (generate_dataset.py).
  2. For every model: pick hyper-parameters by fitting on TRAIN and scoring macro-F1 on VALIDATION.
  3. Pick the shipped model by validation macro-F1 only.
  4. Refit each chosen configuration on TRAIN+VALIDATION and score ONCE on TEST.
  5. Report accuracy and macro-F1 with entity-cluster bootstrap CIs, exact McNemar tests, calibration, ablations,
     a learning curve, and the mean/sd over 5 independent re-splits (each re-tuned from scratch).
Everything is labelled SYNTHETIC: it measures behaviour on unseen merchants written by the authors, not real accuracy.
"""
import argparse
import csv
import json
import pickle
import statistics
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from experiments import generate_dataset as G  # noqa: E402
from experiments.common import (CREDIT, DEBIT, DEFAULT, IS_DED, SECTION, DictionaryRules, cluster_bootstrap, ece,  # noqa: E402
                                hybrid_predict, kappa, log_loss_brier, macro_f1, mcc, mcnemar_exact, predict, prepare,
                                prf, topk, wilson)
from app.classifier import CATEGORY_META, tier1_classify  # noqa: E402
from app.model_registry import REGISTRY, build  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
RES = Path(__file__).resolve().parent / "results"
LABELS = list(CATEGORY_META)
ALL_MODELS = ["majority", "naive_bayes", "complement_nb", "logreg", "linear_svm", "sgd_huber", "ridge", "knn",
              "random_forest", "hist_gb", "mlp", "soft_vote"]
QUICK_MODELS = ["majority", "naive_bayes", "logreg", "linear_svm", "knn", "random_forest"]
NICE = {"majority": "Majority (prior)", "naive_bayes": "Multinomial Naive Bayes", "complement_nb": "Complement Naive Bayes",
        "logreg": "Logistic regression", "linear_svm": "Linear SVM (calibrated)", "sgd_huber": "SGD (modified Huber)",
        "ridge": "Ridge classifier", "knn": "k-nearest neighbours (cosine)", "random_forest": "Random forest",
        "hist_gb": "Gradient boosting (SVD features)", "mlp": "MLP (SVD features)", "soft_vote": "Soft-voting ensemble (LR+SVM+MLP)"}


def split_rows(rows):
    d = {"train": [], "val": [], "test": []}
    for r in rows:
        d[r["split"]].append(r)
    return d


def load_seed0():
    out = {}
    for sp in ("train", "val", "test"):
        with (BACKEND / "data" / "synthetic" / f"{sp}.csv").open(encoding="utf-8") as f:
            out[sp] = [{**r, "split": sp} for r in csv.DictReader(f)]
    return out


def entities_by_cat(rows):
    d = {}
    for r in rows:
        d.setdefault(r["category"], set()).add(r["entity"])
    return d


def tune(name, Xtr, ytr, dtr, Xva, yva, dva):
    """Grid search on the validation split. Returns (best_params, best_val_f1, all_scores, fit_seconds)."""
    best, best_s, scores = None, -1, []
    t0 = time.time()
    for params in REGISTRY[name][2]:
        m = build(name, params).fit(Xtr, ytr)
        p, *_ = predict(m, Xva, dva)
        s = macro_f1(yva, p, LABELS)
        scores.append({"params": params, "val_macro_f1": round(s, 4)})
        if s > best_s:
            best, best_s = params, s
    return best, best_s, scores, time.time() - t0


def full_metrics(y, pred, conf, P, classes, groups, dirs, boot=True):
    n = len(y)
    k = sum(a == b for a, b in zip(y, pred))
    lo, hi = wilson(k, n)
    mp, mr, mf, _ = prf(y, pred, LABELS, "macro")
    wp, wr, wf, _ = prf(y, pred, LABELS, "weighted")
    e, rel = ece(conf, [a == b for a, b in zip(y, pred)])
    ll, br = log_loss_brier(P, classes, y)
    tp = sum(IS_DED[a] and IS_DED[b] for a, b in zip(y, pred))
    fp = sum((not IS_DED[a]) and IS_DED[b] for a, b in zip(y, pred))
    fn = sum(IS_DED[a] and not IS_DED[b] for a, b in zip(y, pred))
    dp = tp / (tp + fp) if tp + fp else 0.0
    dr = tp / (tp + fn) if tp + fn else 0.0
    pr, rc, f1, sup = prf(y, pred, LABELS)
    m = {"n": n, "accuracy": round(k / n, 4), "acc_wilson95": [round(lo, 4), round(hi, 4)],
         "macro": {"precision": round(mp, 4), "recall": round(mr, 4), "f1": round(mf, 4)},
         "weighted": {"precision": round(wp, 4), "recall": round(wr, 4), "f1": round(wf, 4)},
         "mcc": round(mcc(y, pred, LABELS), 4), "kappa": round(kappa(y, pred), 4),
         "top3_accuracy": round(topk(P, classes, y, 3), 4), "log_loss": round(ll, 4), "brier": round(br, 4), "ece": round(e, 4),
         "reliability": rel,
         "tax_section_accuracy": round(float(np.mean([SECTION[a] == SECTION[b] for a, b in zip(y, pred)])), 4),
         "deduction": {"precision": round(dp, 4), "recall": round(dr, 4), "f1": round(2 * dp * dr / (dp + dr), 4) if dp + dr else 0.0,
                       "false_deductions": fp, "missed_deductions": fn},
         "by_direction": {d: round(float(np.mean([a == b for a, b, dd in zip(y, pred, dirs) if dd == d])), 4)
                          for d in ("debit", "credit") if any(dd == d for dd in dirs)},
         "per_class": {l: {"precision": round(float(pr[i]), 4), "recall": round(float(rc[i]), 4), "f1": round(float(f1[i]), 4),
                           "support": int(sup[i])} for i, l in enumerate(LABELS) if sup[i] > 0}}
    if boot:
        m.update(cluster_bootstrap(y, pred, groups, LABELS, B=600))
    return m


def run_split(data, models, seed_tag, boot=True, verbose=True):
    """Tune on val, refit on train+val, evaluate once on test."""
    Xtr, dtr, _ = prepare(data["train"])
    Xva, dva, _ = prepare(data["val"])
    Xte, dte, pte = prepare(data["test"])
    ytr, yva, yte = [r["category"] for r in data["train"]], [r["category"] for r in data["val"]], [r["category"] for r in data["test"]]
    groups = [r["entity"] + "|" + r["category"] for r in data["test"]]
    out, fitted = {}, {}
    for name in models:
        best, bs, scores, t_tune = tune(name, Xtr, ytr, dtr, Xva, yva, dva)
        t0 = time.time()
        final = build(name, best).fit(Xtr + Xva, ytr + yva)
        t_fit = time.time() - t0
        pred, conf, P, classes = predict(final, Xte, dte)
        met = full_metrics(yte, pred, conf, P, classes, groups, dte, boot=boot)
        t1 = time.time()
        for x, d in list(zip(Xte, dte))[:150]:
            predict(final, [x], [d])
        lat = (time.time() - t1) / 150 * 1000
        size = len(pickle.dumps(final)) / 1024
        out[name] = {"name": NICE[name], "params": best, "val_macro_f1": round(bs, 4), "tuning": scores, "test": met,
                     "train_seconds": round(t_fit, 2), "latency_ms_per_message": round(lat, 2), "model_kb": round(size, 1)}
        fitted[name] = (final, pred, conf)
        if verbose:
            print(f"[{seed_tag}] {name:14s} val F1 {bs:.3f} | test acc {met['accuracy']:.3f} macroF1 {met['macro']['f1']:.3f} "
                  f"| fit {t_fit:.1f}s lat {lat:.1f}ms", flush=True)
    return out, fitted, (Xtr, dtr, ytr, Xva, dva, yva, Xte, dte, yte, groups, pte)


def rules_and_hybrids(data, fitted, best_name, ctx):
    Xtr, dtr, ytr, Xva, dva, yva, Xte, dte, yte, groups, pte = ctx
    out = {}
    ents = entities_by_cat(data["train"] + data["val"])
    dr = DictionaryRules(ents)
    rule_fn = dr.classify
    pred_rules = [rule_fn(x, d) or DEFAULT.get(d, "uncategorized") for x, d in zip(Xte, dte)]
    shipped = [(tier1_classify(x, d) or {"category": DEFAULT.get(d, "uncategorized")})["category"] for x, d in zip(Xte, dte)]
    model = fitted[best_name][0]
    hyb, conf, src = hybrid_predict(rule_fn, model, Xte, dte)
    Pm, classes = None, None

    def row(label, pred, note):
        k = sum(a == b for a, b in zip(yte, pred))
        mp, mr, mf, _ = prf(yte, pred, LABELS, "macro")
        return {"name": label, "accuracy": round(k / len(yte), 4), "macro_f1": round(mf, 4), "macro_precision": round(mp, 4),
                "macro_recall": round(mr, 4), "note": note}
    out["rules_from_training_entities"] = row("Rules: dictionary of training merchants", pred_rules,
                                              "Exact-name dictionary built from train+val entities (no test merchant is in it).")
    out["rules_shipped_taxonomy"] = row("Rules: shipped taxonomy (merchant_taxonomy.json)", shipped,
                                        "OPTIMISTIC: the shipped keyword list was written with common brands in mind and overlaps test brands.")
    out["hybrid_rules_then_ml"] = row(f"Hybrid: training dictionary, then {NICE[best_name]}", hyb,
                                      "Rules decide when they match; the model decides the rest.")
    out["hybrid_rule_share"] = round(Counter(src)["rule"] / len(src), 4)
    return out, hyb, conf


def selective(y, pred, conf):
    """Risk-coverage: sort by confidence, report accuracy among the top-c fraction (the rest are sent to the user)."""
    order = np.argsort(-np.asarray(conf))
    ok = np.array([a == b for a, b in zip(y, pred)])[order]
    pts = []
    for c in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        m = max(1, int(round(c * len(ok))))
        pts.append({"coverage": c, "accuracy": round(float(ok[:m].mean()), 4)})
    return pts


def operating_point(Xva, dva, yva, model, target=0.95):
    """On VALIDATION only: smallest confidence threshold with accepted-accuracy >= target."""
    pred, conf, *_ = predict(model, Xva, dva)
    best = {"threshold": 1.01, "coverage": 0.0, "accuracy": None}
    for t in np.linspace(0.05, 0.99, 95):
        m = conf >= t
        if m.sum() < 20:
            break
        acc = np.mean([a == b for a, b, k in zip(yva, pred, m) if k])
        if acc >= target:
            return {"threshold": round(float(t), 2), "coverage": round(float(m.mean()), 4), "accuracy": round(float(acc), 4)}
    return best


def ablations(data, best_name, best_params, ctx):
    Xtr, dtr, ytr, Xva, dva, yva, Xte, dte, yte, groups, pte = ctx
    res = {}

    def evalm(label, m, X=Xte, d=dte):
        pred, conf, P, classes = predict(m, X, d)
        res[label] = {"accuracy": round(float(np.mean([a == b for a, b in zip(yte, pred)])), 4),
                      "macro_f1": round(macro_f1(yte, pred, LABELS), 4)}
    Xall, yall = Xtr + Xva, ytr + yva
    for feat in ("char", "word", "char_word"):
        evalm(f"features={feat}", build(best_name, {**best_params, "feat": feat}).fit(Xall, yall))
    base = build(best_name, best_params).fit(Xall, yall)
    pred, *_ = predict(base, Xte, ["unknown"] * len(Xte))
    res["no direction restriction (credit/debit ignored)"] = {"accuracy": round(float(np.mean([a == b for a, b in zip(yte, pred)])), 4),
                                                             "macro_f1": round(macro_f1(yte, pred, LABELS), 4)}
    raw_tr = [r["sms"] for r in data["train"] + data["val"]]
    raw_te = [r["sms"] for r in data["test"]]
    m = build(best_name, best_params).fit(raw_tr, yall)
    evalm("input = whole SMS text (no parser)", m, raw_te, dte)
    res["input = parsed merchant (shipped)"] = {"accuracy": round(float(np.mean([a == b for a, b in zip(yte, predict(base, Xte, dte)[0])])), 4),
                                               "macro_f1": round(macro_f1(yte, predict(base, Xte, dte)[0], LABELS), 4)}
    return res


def amount_features(rows):
    import math
    out = []
    for r in rows:
        a = float(r["amount"])
        out.append([math.log10(max(a, 1.0)) / 6.0, float(a % 1000 == 0), float(a % 500 == 0), float(a % 100 == 0), float(abs(a - round(a)) > 1e-9)])
    return np.array(out)


def amount_ablation(data, name, params, ctx):
    """Does the amount help? CAVEAT: synthetic amounts are drawn from category-specific ranges chosen by the authors,
    so any gain is partly an artefact of the generator. Reported as an upper bound, never as a shipped feature."""
    from scipy.sparse import csr_matrix, hstack
    from sklearn.linear_model import LogisticRegression
    from app.model_registry import vectorizer
    Xtr, dtr, ytr, Xva, dva, yva, Xte, dte, yte, groups, pte = ctx
    rows_all = data["train"] + data["val"]
    out = {}
    for label, use_amt in (("text only", False), ("text + amount features (synthetic amounts; optimistic)", True)):
        vec = vectorizer("char_word")
        A = vec.fit_transform(Xtr + Xva)
        T = vec.transform(Xte)
        if use_amt:
            A = hstack([A, csr_matrix(amount_features(rows_all) * 3.0)]).tocsr()
            T = hstack([T, csr_matrix(amount_features(data["test"]) * 3.0)]).tocsr()
        clf = LogisticRegression(C=params.get("C", 30.0), max_iter=3000).fit(A, ytr + yva)
        P = clf.predict_proba(T)
        classes = list(clf.classes_)
        pred = []
        for i, d in enumerate(dte):
            from experiments.common import allowed_mask
            m = allowed_mask(classes, d)
            pred.append(classes[int((P[i] * m).argmax())])
        out[label] = {"accuracy": round(float(np.mean([a == b for a, b in zip(yte, pred)])), 4), "macro_f1": round(macro_f1(yte, pred, LABELS), 4)}
    return out


def learning_curve(data, name, params, ctx, reps=3):
    Xtr, dtr, ytr, Xva, dva, yva, Xte, dte, yte, groups, pte = ctx
    rows = data["train"] + data["val"]
    ents = sorted({(r["category"], r["entity"]) for r in rows})
    out = []
    for frac in (0.1, 0.25, 0.5, 0.75, 1.0):
        accs, f1s = [], []
        for rep in range(reps if frac < 1 else 1):
            rng = np.random.default_rng(rep)
            keep = set(map(tuple, rng.permutation(np.array(ents, dtype=object))[:max(22, int(len(ents) * frac))].tolist())) if frac < 1 else set(ents)
            sub = [r for r in rows if (r["category"], r["entity"]) in keep]
            X, _, _ = prepare(sub)
            m = build(name, params).fit(X, [r["category"] for r in sub])
            pred, *_ = predict(m, Xte, dte)
            accs.append(float(np.mean([a == b for a, b in zip(yte, pred)])))
            f1s.append(macro_f1(yte, pred, LABELS))
        out.append({"fraction": frac, "entities": int(len(ents) * frac), "accuracy": round(float(np.mean(accs)), 4),
                    "macro_f1": round(float(np.mean(f1s)), 4), "macro_f1_sd": round(float(np.std(f1s)), 4)})
        print(f"  learning curve {frac:.2f}: macroF1 {out[-1]['macro_f1']:.3f}", flush=True)
    return out


def parser_report(rows_test):
    import re
    from app.parser import parse_sms
    n = len(rows_test)
    f = {"amount": 0, "direction": 0, "merchant": 0, "balance": 0}
    nb = 0
    for r in rows_test:
        p = parse_sms(r["sms"])
        f["amount"] += p["amount"] is not None and abs(p["amount"] - float(r["amount"])) < 0.01
        f["direction"] += p["txn_type"] == r["type"]
        a = re.sub(r"[^A-Z0-9]", "", p["merchant"])
        b = re.sub(r"[^A-Z0-9]", "", r["expected_merchant"].upper())
        f["merchant"] += a == b
    NON = [  # author-written non-transaction messages that must NOT be stored as spending
        "123456 is your OTP for login. Do not share it with anyone.", "OTP 482913 for txn of Rs 2,000 at FLIPKART. Do not share",
        "Txn of INR 799 at NETFLIX on card ending 4455 declined", "Your payment of Rs 1,200 has failed. Please retry.",
        "Insufficient balance for txn of Rs 5,000 on A/c XX1234", "Your EMI of Rs 12,000 is due on 05-11-26. Please maintain balance.",
        "Reminder: your credit card bill of Rs 14,200 is due on 15-10-26", "Pre-approved personal loan up to Rs 5,00,000 for you. Apply now!",
        "e-Mandate request for Rs 649 from NETFLIX. Approve in app.", "Rs 500 will be debited on 01-11-26 towards your SIP",
        "Get 10% cashback offer on shopping. T&C apply", "Dear customer, your a/c XX1234 KYC is expiring. Update now",
        "Available balance in A/c XX1234 is Rs 10,000 as on 05-10-26", "UPI request for Rs 300 from RAMESH. Pending approval",
        "Use code SAVE20 to get Rs 200 off your next order", "Your insurance premium of Rs 15,000 is due on 20-10-26",
    ]
    TXN = [("Rs 250.00 debited from A/c XX1 on 05-10-26 to SWIGGY. Bal Rs 9,000", True), ("INR 5,000.00 credited to A/c XX1 on 05-10-26 by CLIENT. Avl Bal INR 20,000", True),
           ("Rs 15000 withdrawn from ATM on 03-07-26 A/c XX4821. Avl Bal Rs 40,000", True), ("A/c XX4821 credited INR 54.00 Info: REVERSAL OF FAILED TXN. Avl bal INR 5,000", True)]
    fpos = sum(parse_sms(t).get("skipped") is None and parse_sms(t)["amount"] is not None and parse_sms(t)["txn_type"] is not None for t in NON)
    tneg = sum(parse_sms(t).get("skipped") is not None or parse_sms(t)["amount"] is None for t, _ in TXN)
    return {"n": n, "amount_accuracy": round(f["amount"] / n, 4), "direction_accuracy": round(f["direction"] / n, 4),
            "merchant_accuracy": round(f["merchant"] / n, 4),
            "non_transaction_samples": len(NON), "non_transactions_wrongly_stored": fpos,
            "real_transaction_samples": len(TXN), "real_transactions_wrongly_skipped": tneg,
            "note": "Synthetic wording written by the authors; real bank SMS vary far more."}


def plots(summary, fitted, best_name, ctx):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figs = RES / "figs"
    figs.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    ms = summary["models"]
    order = sorted(ms, key=lambda k: ms[k]["test"]["macro"]["f1"])
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    f1 = [ms[k]["test"]["macro"]["f1"] for k in order]
    lo = [ms[k]["test"]["macro_f1_ci95"][0] for k in order]
    hi = [ms[k]["test"]["macro_f1_ci95"][1] for k in order]
    ax.barh([ms[k]["name"] for k in order], f1, xerr=[np.array(f1) - lo, np.array(hi) - f1], color="#0b7a75", capsize=3)
    for i, v in enumerate(f1):
        ax.text(min(v + 0.012, 0.96), i, f"{v:.3f}", va="center", fontsize=8)
    ax.set_xlim(0, 1.02)
    ax.set_xlabel("Macro-F1 on held-out test merchants (synthetic data; bars = 95% entity-bootstrap CI)")
    fig.tight_layout()
    fig.savefig(figs / "model_comparison.png", dpi=170)
    plt.close(fig)
    # confusion matrix, row-normalised, for the shipped model
    final, pred, conf = fitted[best_name]
    yte = ctx[8]
    used = [l for l in LABELS if l in set(yte) | set(pred)]
    idx = {l: i for i, l in enumerate(used)}
    cm = np.zeros((len(used), len(used)))
    for a, b in zip(yte, pred):
        cm[idx[a], idx[b]] += 1
    cmn = cm / cm.sum(axis=1, keepdims=True).clip(1)
    fig, ax = plt.subplots(figsize=(8.2, 7.2))
    ax.imshow(cmn, cmap="GnBu", vmin=0, vmax=1)
    ax.set_xticks(range(len(used)))
    ax.set_yticks(range(len(used)))
    ax.set_xticklabels(used, rotation=70, ha="right", fontsize=7)
    ax.set_yticklabels(used, fontsize=7)
    for i in range(len(used)):
        for j in range(len(used)):
            if cm[i, j]:
                ax.text(j, i, int(cm[i, j]), ha="center", va="center", fontsize=6, color="white" if cmn[i, j] > .5 else "black")
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.set_title(f"{NICE[best_name]}: test confusion matrix (counts; colour = row share)")
    fig.tight_layout()
    fig.savefig(figs / "confusion_matrix.png", dpi=150)
    plt.close(fig)
    # per-class F1
    pc = ms[best_name]["test"]["per_class"]
    ks = sorted(pc, key=lambda k: pc[k]["f1"])
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.barh(ks, [pc[k]["f1"] for k in ks], color=["#d04545" if pc[k]["f1"] < .6 else "#0b7a75" for k in ks])
    ax.set_xlim(0, 1)
    ax.set_xlabel("F1 per category (test)")
    fig.tight_layout()
    fig.savefig(figs / "per_class_f1.png", dpi=170)
    plt.close(fig)
    # reliability
    rel = ms[best_name]["test"]["reliability"]
    fig, ax = plt.subplots(figsize=(4.6, 4.4))
    ax.plot([0, 1], [0, 1], "--", color="#999")
    ax.plot([r["conf"] for r in rel], [r["acc"] for r in rel], "o-", color="#0b7a75")
    ax.set_xlabel("Mean confidence")
    ax.set_ylabel("Observed accuracy")
    ax.set_title(f"Reliability (ECE = {ms[best_name]['test']['ece']:.3f})")
    fig.tight_layout()
    fig.savefig(figs / "reliability.png", dpi=170)
    plt.close(fig)
    # risk-coverage
    fig, ax = plt.subplots(figsize=(5, 4))
    for k in ("logreg", "linear_svm", best_name):
        if k in summary["selective"]:
            pts = summary["selective"][k]
            ax.plot([p["coverage"] for p in pts], [p["accuracy"] for p in pts], "o-", label=NICE[k], ms=3)
    ax.set_xlabel("Coverage (share auto-classified; rest sent to the user)")
    ax.set_ylabel("Accuracy on auto-classified")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(figs / "risk_coverage.png", dpi=170)
    plt.close(fig)
    # learning curve
    lc = summary["learning_curve"]
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.errorbar([p["entities"] for p in lc], [p["macro_f1"] for p in lc], yerr=[p["macro_f1_sd"] for p in lc], fmt="o-", color="#0b7a75", capsize=3)
    ax.set_xlabel("Training merchants (entities)")
    ax.set_ylabel("Test macro-F1")
    ax.set_title(NICE[best_name])
    fig.tight_layout()
    fig.savefig(figs / "learning_curve.png", dpi=170)
    plt.close(fig)
    # robustness across splits
    rb = summary.get("robustness")
    if rb:
        names = sorted(rb["models"], key=lambda k: np.mean(rb["models"][k]["macro_f1"]))
        fig, ax = plt.subplots(figsize=(7.5, 4.6))
        ax.boxplot([rb["models"][k]["macro_f1"] for k in names], vert=False, tick_labels=[NICE[k] for k in names])
        ax.set_xlabel(f"Test macro-F1 over {rb['n_splits']} independent entity splits (each re-tuned)")
        fig.tight_layout()
        fig.savefig(figs / "robustness.png", dpi=170)
        plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--seeds", type=int, default=5)
    a = ap.parse_args()
    RES.mkdir(parents=True, exist_ok=True)
    models = QUICK_MODELS if a.quick else ALL_MODELS
    data = load_seed0()
    ents = {sp: {(r["category"], r["entity"]) for r in data[sp]} for sp in data}
    assert not (ents["train"] & ents["val"]) and not (ents["train"] & ents["test"]) and not (ents["val"] & ents["test"]), "LEAK"
    t0 = time.time()
    ms, fitted, ctx = run_split(data, models, "seed0")
    best_name = max((k for k in ms if k != "majority"), key=lambda k: ms[k]["val_macro_f1"])  # chosen on VALIDATION only
    print("selected by validation macro-F1:", best_name, ms[best_name]["val_macro_f1"], flush=True)
    summary = {
        "label": "SYNTHETIC corpus: unseen merchants written by the authors. Not real-world accuracy.",
        "date": date.today().isoformat(),
        "dataset": {"seed": 0, "rows": {sp: len(data[sp]) for sp in data}, "entities": {sp: len(ents[sp]) for sp in ents},
                    "classes": len({r["category"] for sp in data for r in data[sp]}),
                    "class_counts_test": dict(Counter(r["category"] for r in data["test"])),
                    "sha256_16": {sp: G.checksum(BACKEND / "data" / "synthetic" / f"{sp}.csv") for sp in data}},
        "selected": {"name": best_name, "params": ms[best_name]["params"], "selected_by": "validation macro-F1",
                     "val_macro_f1": ms[best_name]["val_macro_f1"]},
        "models": ms,
    }
    summary["rules_and_hybrids"], hyb_pred, hyb_conf = rules_and_hybrids(data, fitted, best_name, ctx)
    Xtr, dtr, ytr, Xva, dva, yva, Xte, dte, yte, groups, pte = ctx
    summary["selective"] = {k: selective(yte, fitted[k][1], fitted[k][2]) for k in fitted if k != "majority"}
    summary["operating_point"] = operating_point(Xva, dva, yva, build(best_name, ms[best_name]["params"]).fit(Xtr, ytr), 0.95)
    # test-side accuracy at the validation-chosen threshold
    op = summary["operating_point"]
    pred_b, conf_b = fitted[best_name][1], fitted[best_name][2]
    acc_mask = np.asarray(conf_b) >= op["threshold"]
    summary["operating_point"]["test_coverage"] = round(float(acc_mask.mean()), 4)
    summary["operating_point"]["test_accuracy_on_accepted"] = round(float(np.mean([a_ == b_ for a_, b_, k in zip(yte, pred_b, acc_mask) if k])), 4) if acc_mask.any() else None
    # McNemar: shipped vs every other model
    bc = [a_ == b_ for a_, b_ in zip(yte, fitted[best_name][1])]
    summary["mcnemar_vs_selected"] = {}
    for k in fitted:
        if k == best_name:
            continue
        n10, n01, p = mcnemar_exact(bc, [x == y for x, y in zip(yte, fitted[k][1])])
        summary["mcnemar_vs_selected"][k] = {"selected_right_other_wrong": n10, "other_right_selected_wrong": n01, "p_value": round(p, 6)}
    print("ablations...", flush=True)
    summary["ablations"] = ablations(data, best_name, ms[best_name]["params"], ctx)
    summary["amount_ablation"] = amount_ablation(data, best_name, ms[best_name]["params"], ctx)
    print("learning curve...", flush=True)
    summary["learning_curve"] = learning_curve(data, best_name, ms[best_name]["params"], ctx, reps=2 if a.quick else 3)
    summary["parser"] = parser_report(data["test"])
    # robustness across independent re-splits (full nested tuning each time)
    if not a.quick and a.seeds > 1:
        rb = {m_: {"accuracy": [ms[m_]["test"]["accuracy"]], "macro_f1": [ms[m_]["test"]["macro"]["f1"]]} for m_ in models}
        for s in range(1, a.seeds):
            rows = G.build_corpus(s)
            d = split_rows(rows)
            print(f"--- robustness split {s} ---", flush=True)
            m2, _, _ = run_split(d, models, f"seed{s}", boot=False, verbose=True)
            for m_ in models:
                rb[m_]["accuracy"].append(m2[m_]["test"]["accuracy"])
                rb[m_]["macro_f1"].append(m2[m_]["test"]["macro"]["f1"])
        summary["robustness"] = {"n_splits": a.seeds, "models": {m_: {**v, "acc_mean": round(float(np.mean(v["accuracy"])), 4),
                                 "acc_sd": round(float(np.std(v["accuracy"], ddof=1)), 4),
                                 "f1_mean": round(float(np.mean(v["macro_f1"])), 4), "f1_sd": round(float(np.std(v["macro_f1"], ddof=1)), 4)}
                                 for m_, v in rb.items()},
                                 "note": "Each split re-draws which merchants fall in train/val/test and re-tunes every model."}
    summary["runtime_seconds"] = round(time.time() - t0)
    (RES / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")  # save first: plotting must never lose a 40-minute run
    try:
        plots(summary, fitted, best_name, ctx)
    except Exception as e:  # noqa: BLE001
        print("WARNING: plotting failed:", repr(e), "- summary.json is saved; rerun plots separately")
    # write the model choice used by the app; train data for the shipped model excludes the test split
    cfg = {"selected": summary["selected"], "trained_on": "train+val of the synthetic corpus plus curated examples; never test",
           "date": summary["date"]}
    (BACKEND / "data" / "model_config.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    print("done in", summary["runtime_seconds"], "s ->", RES / "summary.json")


if __name__ == "__main__":
    main()
