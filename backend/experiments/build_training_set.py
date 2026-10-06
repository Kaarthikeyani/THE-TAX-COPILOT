"""Build data/training_examples.csv = curated examples (data/training_examples_curated.csv) + merchant strings parsed from the
SYNTHETIC train and validation splits. The test split is never read here.   python experiments/build_training_set.py"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.parser import parse_sms  # noqa: E402

D = Path(__file__).resolve().parent.parent / "data"
rows, seen = [], set()
for r in csv.DictReader(open(D / "training_examples_curated.csv", encoding="utf-8")):
    k = (r["text"].strip().upper(), r["category"])
    if k not in seen:
        seen.add(k); rows.append(k)
n0 = len(rows)
for sp in ("train", "val"):  # never "test"
    for r in csv.DictReader(open(D / "synthetic" / f"{sp}.csv", encoding="utf-8")):
        m = parse_sms(r["sms"])["merchant"]
        k = (m.strip().upper(), r["category"])
        if m and k not in seen:
            seen.add(k); rows.append(k)
with open(D / "training_examples.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f); w.writerow(["text", "category"]); w.writerows(rows)
print(f"curated {n0} + synthetic train/val {len(rows) - n0} = {len(rows)} examples")
