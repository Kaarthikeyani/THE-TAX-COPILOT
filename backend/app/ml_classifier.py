"""Tier-2 ML fallback. Which model runs, and with what settings, is chosen by the experiments and stored in
data/model_config.json (default: TF-IDF + logistic regression). Training text comes from
data/training_examples.csv plus every category you corrected in the app - nothing is hard-coded in Python.
"""
import csv
import json
import threading
from pathlib import Path

from .classifier import CATEGORY_META
from .model_registry import build

DATA = Path(__file__).resolve().parent.parent / "data"
TRAINING_CSV = DATA / "training_examples.csv"   # columns: text,category
CONFIG_PATH = DATA / "model_config.json"        # written by experiments/run_experiments.py
DEFAULT_CONFIG = {"name": "logreg", "params": {"C": 30.0}}

_lock = threading.Lock()
_model = None
_extra: list = []          # (text, category) from user corrections, set by set_extra_examples()
CONFIDENCE_FLOOR = 0.22


def load_examples() -> list:
    rows = []
    if TRAINING_CSV.exists():
        with TRAINING_CSV.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                t, c = (r.get("text") or "").strip(), (r.get("category") or "").strip()
                if t and c in CATEGORY_META:
                    rows.append((t, c))
    return rows + list(_extra)


def get_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["selected"]
        except Exception:
            pass
    return DEFAULT_CONFIG


def set_extra_examples(pairs: list):
    """Called with (merchant, category) pairs the user has corrected; takes effect on the next retrain."""
    global _extra
    _extra = [(t, c) for t, c in pairs if t and c in CATEGORY_META]


def _build():
    rows = load_examples()
    X, y = [r[0] for r in rows], [r[1] for r in rows]
    cfg = get_config()
    pipe = build(cfg["name"], cfg.get("params"))
    pipe.fit(X, y)
    return pipe


def get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = _build()
    return _model


def retrain():
    """Rebuild the model from the CSV plus corrections (call after adding examples or fixing categories)."""
    global _model
    with _lock:
        _model = _build()
    return {"examples": len(load_examples()), "model": get_config()["name"]}


def ml_classify(text: str, txn_type: str):
    """Classify a novel merchant string. Restricts to income classes for credits and
    expense/investment classes for debits."""
    model = get_model()
    classes = list(model.classes_)
    probs = model.predict_proba([text or ""])[0]
    allowed = [(c, p) for c, p in zip(classes, probs)
               if (CATEGORY_META[c][2] == "income") == (txn_type == "credit")]
    if not allowed:
        cat = "other_income" if txn_type == "credit" else "uncategorized"
        label, section, _ = CATEGORY_META[cat]
        return {"category": cat, "label": label, "tax_section": section,
                "source": "tier2_ml_low_confidence", "confidence": 0.0}
    total = sum(p for _, p in allowed) or 1.0
    best_cat, best_p = max(allowed, key=lambda cp: cp[1])
    conf = round(best_p / total, 2)
    if conf < CONFIDENCE_FLOOR:
        cat = "other_income" if txn_type == "credit" else "uncategorized"
        label, section, _ = CATEGORY_META[cat]
        return {"category": cat, "label": label, "tax_section": section,
                "source": "tier2_ml_low_confidence", "confidence": conf}
    label, section, _ = CATEGORY_META[best_cat]
    return {"category": best_cat, "label": label, "tax_section": section,
            "source": "tier2_ml_fallback", "confidence": conf}
