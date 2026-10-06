"""Score the app's own pipeline (parser -> rules -> ML) on REAL labelled SMS that you supply.

   python experiments/evaluate_real.py [path]      default: data/real_labelled.csv

CSV columns: sms,category      (category must be one of `python -m app.maintenance categories`).
Use messages the model has NOT been trained on (do not add them to data/training_examples.csv before scoring).
Delete or mask account numbers and names first; the file is never uploaded anywhere. Prints accuracy, macro
precision/recall/F1 with a Wilson interval, and per-class numbers. Real results replace the synthetic ones in any report.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.classifier import tier1_classify  # noqa: E402
from app.ml_classifier import ml_classify  # noqa: E402
from app.parser import parse_sms  # noqa: E402
from experiments.common import prf, wilson  # noqa: E402


def main(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    if not rows:
        sys.exit("File has no rows")
    y, p, skipped = [], [], 0
    for r in rows:
        pr = parse_sms(r["sms"])
        if not pr["txn_type"] or pr["amount"] is None:
            skipped += 1
            continue
        c = tier1_classify(pr["merchant"], pr["txn_type"]) or ml_classify(pr["merchant"] or r["sms"], pr["txn_type"])
        y.append(r["category"].strip())
        p.append(c["category"])
    n = len(y)
    if not n:
        sys.exit("No parsable transactions in the file")
    k = sum(a == b for a, b in zip(y, p))
    lo, hi = wilson(k, n)
    labels = sorted(set(y) | set(p))
    pa, ra, fa, _ = prf(y, p, labels, "macro")
    print(f"n={n} (skipped {skipped} unparsable)  accuracy {k / n:.3f}  95% CI [{lo:.3f}, {hi:.3f}]")
    print(f"macro precision {pa:.3f}  recall {ra:.3f}  F1 {fa:.3f}")
    pc, rc, fc, sup = prf(y, p, labels)
    for i, l in enumerate(labels):
        if sup[i]:
            print(f"  {l:<22} P {pc[i]:.2f}  R {rc[i]:.2f}  F1 {fc[i]:.2f}  n={int(sup[i])}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent.parent / "data" / "real_labelled.csv"))
