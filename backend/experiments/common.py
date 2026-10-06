"""Shared evaluation utilities: parsing SMS into model inputs, direction-aware prediction, metrics, statistics."""
from __future__ import annotations

import math
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.classifier import CATEGORY_META, KEYWORD_FALLBACK, normalize_merchant, tier1_classify  # noqa: E402
from app.parser import parse_sms  # noqa: E402

CREDIT = [c for c, v in CATEGORY_META.items() if v[2] == "income"]
DEBIT = [c for c, v in CATEGORY_META.items() if v[2] != "income"]
DEFAULT = {"credit": "other_income", "debit": "uncategorized"}
SECTION = {c: v[1] for c, v in CATEGORY_META.items()}
IS_DED = {c: v[1] != "none" for c, v in CATEGORY_META.items()}


def prepare(rows):
    """SMS rows -> (text for the classifier, direction, parsed dict). Exactly what the app does at ingestion."""
    X, dirs, parsed = [], [], []
    for r in rows:
        p = parse_sms(r["sms"])
        X.append(p["merchant"] or r["sms"])
        dirs.append(p["txn_type"] or "unknown")
        parsed.append(p)
    return X, dirs, parsed


def allowed_mask(classes, direction):
    if direction == "credit":
        return np.array([c in CREDIT for c in classes])
    if direction == "debit":
        return np.array([c in DEBIT for c in classes])
    return np.ones(len(classes), dtype=bool)


def restricted_proba(model, X, dirs):
    """Probabilities renormalised over the classes allowed for each message's direction (as the app does)."""
    P = model.predict_proba(X)
    classes = list(model.classes_)
    out = np.zeros_like(P)
    for i, d in enumerate(dirs):
        m = allowed_mask(classes, d)
        row = P[i] * m
        s = row.sum()
        out[i] = row / s if s > 0 else m / max(1, m.sum())
    return out, classes


def predict(model, X, dirs):
    P, classes = restricted_proba(model, X, dirs)
    idx = P.argmax(axis=1)
    return [classes[i] for i in idx], P.max(axis=1), P, classes


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - r) / d, (c + r) / d)


def prf(y, p, labels, average=None):
    """Precision / recall / F1 computed from first principles (no sklearn), so the paper's formulas are the code."""
    idx = {l: i for i, l in enumerate(labels)}
    k = len(labels)
    tp = np.zeros(k)
    fp = np.zeros(k)
    fn = np.zeros(k)
    for a, b in zip(y, p):
        if a == b:
            tp[idx[a]] += 1
        else:
            fn[idx[a]] += 1
            if b in idx:
                fp[idx[b]] += 1
    prec = np.divide(tp, tp + fp, out=np.zeros(k), where=(tp + fp) > 0)
    rec = np.divide(tp, tp + fn, out=np.zeros(k), where=(tp + fn) > 0)
    f1 = np.divide(2 * prec * rec, prec + rec, out=np.zeros(k), where=(prec + rec) > 0)
    sup = tp + fn
    if average is None:
        return prec, rec, f1, sup
    present = sup > 0  # macro average over classes that occur in the reference labels
    if average == "macro":
        return prec[present].mean(), rec[present].mean(), f1[present].mean(), sup.sum()
    w = sup / sup.sum()
    return (prec * w).sum(), (rec * w).sum(), (f1 * w).sum(), sup.sum()


def macro_f1(y, p, labels):
    return float(prf(y, p, labels, "macro")[2])


def mcc(y, p, labels):
    """Multiclass Matthews correlation coefficient (Gorodkin)."""
    idx = {l: i for i, l in enumerate(labels)}
    k = len(labels)
    C = np.zeros((k, k))
    for a, b in zip(y, p):
        C[idx[a], idx[b]] += 1
    t = C.sum(axis=1)
    pr = C.sum(axis=0)
    n = C.sum()
    c = np.trace(C)
    num = c * n - (t * pr).sum()
    den = math.sqrt(max(n * n - (pr * pr).sum(), 0)) * math.sqrt(max(n * n - (t * t).sum(), 0))
    return float(num / den) if den else 0.0


def kappa(y, p):
    n = len(y)
    po = sum(a == b for a, b in zip(y, p)) / n
    cy, cp = Counter(y), Counter(p)
    pe = sum(cy[l] * cp.get(l, 0) for l in cy) / (n * n)
    return float((po - pe) / (1 - pe)) if pe < 1 else 1.0


def ece(conf, correct, bins=10):
    conf, correct = np.asarray(conf), np.asarray(correct, dtype=float)
    edges = np.linspace(0, 1, bins + 1)
    tot, rel = 0.0, []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi) if lo > 0 else (conf >= lo) & (conf <= hi)
        if m.sum():
            tot += m.sum() / len(conf) * abs(correct[m].mean() - conf[m].mean())
            rel.append({"lo": float(lo), "hi": float(hi), "n": int(m.sum()), "conf": float(conf[m].mean()), "acc": float(correct[m].mean())})
    return float(tot), rel


def log_loss_brier(P, classes, y):
    ci = {c: i for i, c in enumerate(classes)}
    n = len(y)
    ll, br = 0.0, 0.0
    for i, t in enumerate(y):
        pt = max(P[i, ci[t]], 1e-6) if t in ci else 1e-6
        ll += -math.log(pt)
        e = np.zeros(P.shape[1])
        if t in ci:
            e[ci[t]] = 1
        br += float(((P[i] - e) ** 2).sum())
    return ll / n, br / n


def topk(P, classes, y, k=3):
    ci = {c: i for i, c in enumerate(classes)}
    hit = 0
    for i, t in enumerate(y):
        if t in ci and ci[t] in np.argsort(-P[i])[:k]:
            hit += 1
    return hit / len(y)


def mcnemar_exact(a_correct, b_correct):
    """Exact two-sided McNemar test on paired correctness vectors. Returns (b01, b10, p)."""
    from scipy.stats import binomtest
    a, b = np.asarray(a_correct, bool), np.asarray(b_correct, bool)
    n10 = int((a & ~b).sum())   # first right, second wrong
    n01 = int((~a & b).sum())
    n = n10 + n01
    if n == 0:
        return n10, n01, 1.0
    return n10, n01, float(binomtest(min(n10, n01), n, 0.5).pvalue)


def cluster_bootstrap(y, p, groups, labels, B=1000, seed=0):
    """95% percentile CI for accuracy and macro-F1, resampling whole entities (merchants), not rows."""
    rng = np.random.default_rng(seed)
    y, p = np.asarray(y), np.asarray(p)
    gid = {}
    for i, g in enumerate(groups):
        gid.setdefault(g, []).append(i)
    keys = list(gid)
    accs, f1s = [], []
    for _ in range(B):
        pick = rng.integers(0, len(keys), len(keys))
        idx = np.concatenate([gid[keys[j]] for j in pick])
        accs.append(float((y[idx] == p[idx]).mean()))
        f1s.append(macro_f1(y[idx].tolist(), p[idx].tolist(), labels))
    q = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
    return {"acc_ci95": q(accs), "macro_f1_ci95": q(f1s)}


# ---------------------------------------------------------------- rules baselines
_RULE_RX = lambda kw: re.compile(rf"(?<![A-Z0-9]){re.escape(kw)}(?![A-Z0-9])")


class DictionaryRules:
    """Rules learned from the training entities: each training entity's full normalised name becomes a keyword.
    This is what a hand-built merchant dictionary looks like at the moment it is first deployed: perfect on
    merchants it has seen, silent on everything else (falls back to generic keywords, then to 'other')."""

    def __init__(self, entities_by_category):
        self.rules = []
        for cat, names in entities_by_category.items():
            for n in names:
                k = normalize_merchant(n)
                if k:
                    self.rules.append((_RULE_RX(k), k, cat))
        self.rules.sort(key=lambda r: -len(r[1]))

    def classify(self, merchant, direction):
        m = normalize_merchant(merchant)
        for rx, k, cat in self.rules:
            if (direction == "credit") != (cat in CREDIT) and direction != "unknown":
                continue
            if rx.search(m):
                return cat
        for pat, cat in KEYWORD_FALLBACK:
            if re.search(pat, m) and ((direction == "credit") == (cat in CREDIT) or direction == "unknown"):
                return cat
        return None


def hybrid_predict(rule_fn, model, X, dirs, texts_for_rules=None):
    """Rules first; ML for whatever the rules cannot decide. Returns (pred, conf, source)."""
    P, classes = restricted_proba(model, X, dirs)
    out, conf, src = [], [], []
    for i, (x, d) in enumerate(zip(X, dirs)):
        r = rule_fn(x, d)
        if r is not None:
            out.append(r), conf.append(0.95), src.append("rule")
        else:
            j = int(P[i].argmax())
            out.append(classes[j]), conf.append(float(P[i, j])), src.append("ml")
    return out, np.array(conf), src
