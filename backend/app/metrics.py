"""Accuracy measured on YOUR real messages, from the answers you give in the app.

A message becomes a verified label when you fix its category or press "Looks right". The model's original answer
(`auto_category`) is compared with your answer (`category`), so every number here is computed on real SMS, not synthetic text.
Limits are returned with the numbers: the sample size, a 95% interval, and a note about selection bias.
"""
from collections import Counter
from math import sqrt

from sqlalchemy.orm import Session

from .classifier import CATEGORY_META
from .models import Transaction

LOW_CONF = 0.6
MIN_FOR_STABLE = 30


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return round(p, 4), round(r, 4), round(f, 4)


def _family(source: str) -> str:
    if source.startswith("user_"):
        return "your own rules"
    if source.startswith("tier1"):
        return "built-in rules"
    if source.startswith("tier2"):
        return "machine learning"
    return "other"


def live_metrics(db: Session) -> dict:
    rows = db.query(Transaction).all()
    total = len(rows)
    lab = [t for t in rows if t.user_corrected or t.confirmed]
    n = len(lab)
    out = {"transactions": total, "verified": n, "corrected": sum(1 for t in lab if t.user_corrected and t.category != (t.auto_category or t.category)),
           "confirmed_right": sum(1 for t in lab if (t.auto_category or t.category) == t.category),
           "review_coverage": round(n / total, 4) if total else 0.0, "stable": n >= MIN_FOR_STABLE,
           "min_for_stable": MIN_FOR_STABLE}
    pending = [t for t in rows if not (t.user_corrected or t.confirmed) and (t.confidence or 0) < LOW_CONF]
    out["pending_review"] = len(pending)
    out["review_queue"] = [
        {"id": t.id, "merchant": t.merchant, "amount": t.amount, "type": t.txn_type, "label": t.label,
         "category": t.category, "confidence": t.confidence, "source": t.classification_source}
        for t in sorted(pending, key=lambda t: (t.confidence or 0))[:15]]
    out["notes"] = [
        "Computed from the messages you reviewed. People tend to fix wrong ones more often than they confirm right ones, "
        "so accuracy here can read low. Press 'Looks right' on messages that are correct too, for a fair number."]
    if n == 0:
        out["accuracy"] = None
        out["message"] = "Nothing reviewed yet. Open a transaction and press 'Looks right' or fix its category."
        return out

    yt = [t.category for t in lab]
    yp = [(t.auto_category or t.category) for t in lab]
    k = sum(1 for a, b in zip(yt, yp) if a == b)
    out["accuracy"] = round(k / n, 4)
    out["accuracy_wilson95"] = wilson(k, n)

    classes = sorted(set(yt) | set(yp))
    per, tps = {}, 0
    for c in classes:
        tp = sum(1 for a, b in zip(yt, yp) if a == c and b == c)
        fp = sum(1 for a, b in zip(yt, yp) if a != c and b == c)
        fn = sum(1 for a, b in zip(yt, yp) if a == c and b != c)
        p, r, f = _prf(tp, fp, fn)
        per[c] = {"label": CATEGORY_META.get(c, (c,))[0], "precision": p, "recall": r, "f1": f, "support": sum(1 for a in yt if a == c)}
    true_classes = [c for c in classes if per[c]["support"] > 0]
    mac = lambda key: round(sum(per[c][key] for c in true_classes) / len(true_classes), 4) if true_classes else 0.0
    wt = lambda key: round(sum(per[c][key] * per[c]["support"] for c in true_classes) / n, 4)
    out["macro"] = {"precision": mac("precision"), "recall": mac("recall"), "f1": mac("f1")}
    out["weighted"] = {"precision": wt("precision"), "recall": wt("recall"), "f1": wt("f1")}
    out["per_class"] = per
    out["confusions"] = [{"true": a, "predicted": b, "count": c} for (a, b), c in Counter((a, b) for a, b in zip(yt, yp) if a != b).most_common(8)]

    sec = lambda c: CATEGORY_META.get(c, ("", "none"))[1] != "none"
    tp = sum(1 for a, b in zip(yt, yp) if sec(a) and sec(b))
    fp = sum(1 for a, b in zip(yt, yp) if not sec(a) and sec(b))
    fn = sum(1 for a, b in zip(yt, yp) if sec(a) and not sec(b))
    p, r, f = _prf(tp, fp, fn)
    out["tax_saving"] = {"precision": p, "recall": r, "f1": f, "false_deductions": fp, "missed_deductions": fn}

    fam = {}
    for t, a, b in zip(lab, yt, yp):
        key = _family(t.auto_source or t.classification_source)  # the tier that made the ORIGINAL guess
        e = fam.setdefault(key, [0, 0])
        e[0] += 1
        e[1] += int(a == b)
    out["by_source"] = {k_: {"n": v[0], "accuracy": round(v[1] / v[0], 4), "wilson95": wilson(v[1], v[0])} for k_, v in fam.items()}

    ml = [(t.confidence or 0, int(a == b)) for t, a, b in zip(lab, yt, yp) if t.classification_source.startswith("tier2")]
    if len(ml) >= 20:  # calibration needs enough ML-decided messages to mean anything
        bins = []
        for lo in (0.0, 0.4, 0.6, 0.8):
            hi = lo + (0.2 if lo else 0.4) if lo < 0.8 else 1.01
            sel = [x for x in ml if lo <= x[0] < hi]
            if sel:
                bins.append({"lo": lo, "hi": min(hi, 1.0), "n": len(sel), "confidence": round(sum(x[0] for x in sel) / len(sel), 3),
                             "accuracy": round(sum(x[1] for x in sel) / len(sel), 3)})
        out["ml_calibration"] = {"n": len(ml), "ece": round(sum(b["n"] * abs(b["confidence"] - b["accuracy"]) for b in bins) / len(ml), 4), "bins": bins}
    if not out["stable"]:
        out["notes"].append(f"Only {n} reviewed so far. Treat these numbers as a rough guide until you have about {MIN_FOR_STABLE}.")
    return out
