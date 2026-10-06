"""Tier-1 privacy-preserving classifier: local taxonomy lookup + strong-keyword fallback.
Nothing here leaves the device; only coarse amount buckets are used for events."""
import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
TAXONOMY_PATH = DATA / "merchant_taxonomy.json"   # built-in merchant keywords: {category: [keywords]}
USER_RULES_PATH = DATA / "user_rules.csv"          # your own rules: keyword,category (edit in any spreadsheet)

# category -> (label, tax_section, kind)
CATEGORY_META = {
    "elss_investment": ("ELSS mutual fund", "80C", "investment"),
    "life_insurance": ("Life insurance premium", "80C", "investment"),
    "ppf_epf": ("PPF / EPF / VPF", "80C", "investment"),
    "tuition_fees": ("Tuition fees", "80C", "investment"),
    "nps": ("NPS contribution", "80CCD1B", "investment"),
    "health_insurance": ("Health insurance premium", "80D", "investment"),
    "preventive_healthcare": ("Preventive health check-up", "80D", "investment"),
    "home_loan_interest": ("Home loan EMI", "24b", "investment"),
    "donation": ("Charitable donation", "80G", "investment"),
    "food_dining": ("Food & dining", "none", "expense"),
    "groceries": ("Groceries", "none", "expense"),
    "shopping": ("Shopping", "none", "expense"),
    "transport": ("Local transport", "none", "expense"),
    "fuel": ("Fuel", "none", "expense"),
    "utilities": ("Bills & utilities", "none", "expense"),
    "entertainment": ("Entertainment", "none", "expense"),
    "travel": ("Travel", "none", "expense"),
    "rent": ("Rent", "none", "expense"),
    "salary_income": ("Salary", "none", "income"),
    "freelance_income": ("Freelance / business income", "none", "income"),
    "other_income": ("Other credit", "none", "income"),
    "uncategorized": ("Uncategorised", "none", "expense"),
}

# Strong keywords used only when the exact taxonomy misses
KEYWORD_FALLBACK = [
    (r"\bTAX SAVER\b|\bELSS\b", "elss_investment"),
    (r"\bHEALTH INS", "health_insurance"),
    (r"\bLIFE INS", "life_insurance"),
    (r"\bPENSION\b", "nps"),
    (r"\bHOME LOAN\b|\bHOUSING LOAN\b", "home_loan_interest"),
    (r"\bSALARY\b|\bPAYROLL\b", "salary_income"),
    (r"\bDONAT", "donation"),
    (r"\bRESTAURANT\b|\bCAFE\b|\bBAKERY\b", "food_dining"),
    (r"\bPETROL\b|\bDIESEL\b", "fuel"),
    (r"\bSUPERMARKET\b|\bKIRANA\b|\bGROCER", "groceries"),
]


def normalize_merchant(m: str) -> str:
    """Canonical key for a merchant string (used for user rules and corrections)."""
    return re.sub(r"[^A-Z0-9]+", " ", (m or "").upper()).strip()[:60]


def user_csv_rules() -> dict:
    """Read data/user_rules.csv -> {category: [keywords]}. Unknown categories are skipped (and reported by /rules)."""
    out: dict = {}
    if not USER_RULES_PATH.exists():
        return out
    import csv
    with USER_RULES_PATH.open(encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            if len(row) < 2 or row[0].strip().startswith("#") or row[0].strip().lower() == "keyword":
                continue
            kw, cat = row[0].strip().upper(), row[1].strip()
            if kw and cat in CATEGORY_META:
                out.setdefault(cat, []).append(kw)
    return out


def reload_rules():
    _taxonomy.cache_clear()


@lru_cache(maxsize=1)
def _taxonomy():
    raw = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    rules = []
    # your own rules first, so on a tie in keyword length they beat the built-in ones
    for source in (user_csv_rules(), raw):
        for cat, kws in source.items():
            for kw in kws:
                rules.append((re.compile(rf"(?<![A-Z0-9]){re.escape(kw)}(?![A-Z0-9])"), kw, cat))
    # longest keyword first so "HDFC LIFE" beats "LIFE"
    rules.sort(key=lambda r: -len(r[1]))  # stable: user rules stay ahead on ties
    return rules


def amount_bucket(amount: float) -> str:
    for limit, label in [(500, "<500"), (2000, "500-2k"), (10000, "2k-10k"),
                         (50000, "10k-50k"), (100000, "50k-1L"), (500000, "1L-5L")]:
        if amount < limit:
            return label
    return ">5L"


def _result(cat, source, conf):
    label, section, _ = CATEGORY_META[cat]
    return {"category": cat, "label": label, "tax_section": section,
            "source": source, "confidence": conf}


def tier1_classify(merchant: str, txn_type: str):
    """Return a classification dict or None when Tier-1 cannot decide."""
    m = (merchant or "").upper()
    if not m:
        return None
    for rx, kw, cat in _taxonomy():
        if rx.search(m):
            # the expense taxonomy is for debits and income taxonomy for credits
            kind = CATEGORY_META[cat][2]
            if txn_type == "credit" and kind != "income":
                continue
            if txn_type == "debit" and kind == "income":
                continue
            return _result(cat, "tier1_taxonomy", 0.95)
    for pattern, cat in KEYWORD_FALLBACK:
        if re.search(pattern, m):
            kind = CATEGORY_META[cat][2]
            if (txn_type == "credit") != (kind == "income"):
                continue
            return _result(cat, "tier1_keyword", 0.80)
    return None
