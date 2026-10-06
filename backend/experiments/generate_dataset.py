"""Build the SYNTHETIC labelled SMS corpus and split it by merchant entity.

   python experiments/generate_dataset.py            (run from backend/)  -> data/synthetic/{train,val,test}.csv

SYNTHETIC means: the merchant names come from experiments/lexicon.py and the SMS wording from the templates below, both
written by the authors. Results on this corpus say how a method behaves on *unseen merchants in familiar bank wording*.
They are NOT real-world accuracy. Real labelled SMS (data/real_labelled.csv) always take priority in the reports.

Leak control: the split is over *entities*. Every SMS of an entity (all its spelling variants, templates, amounts) goes to
exactly one of train / validation / test, so a merchant never appears on both sides of a boundary.
"""
import csv
import hashlib
import random
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from experiments.lexicon import CATEGORIES, CREDIT_CATEGORIES, E  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "synthetic"
SPLIT = (0.60, 0.20, 0.20)

DEBIT_T = [
    "Rs.{a2} debited from A/c XX{ac} on {d} to {m} (UPI Ref {r}). Bal Rs {b2}",
    "Your a/c no. XX{ac} is debited for Rs {a0} on {d} and a/c credited to {m}. Avl bal Rs {b2}",
    "Rs {a0} spent on HDFC Bank Card x{ac} at {m} on {d}. Avl Lmt Rs 90,000",
    "Sent Rs.{a2} From HDFC Bank A/C *{ac} To {m} On {d} Ref {r}",
    "A/c XX{ac} debited INR {a2} on {d}. Info: UPI/{r}/{m}. Avl Bal INR {b2}",
    "Dear Customer, Rs.{a2} has been debited from your account for payment to {m} on {d}.",
    "A/c XX{ac} debited INR {a2} on {d}. Info: {m}. Avl bal INR {b2}",
    "Rs {a0} paid to {m} on {d} using ICICI Bank Card XX{ac}. Avl Bal Rs {b2}",
    "INR {a2} spent at {m} on {d} via Axis Bank Card ending {ac}.",
    "Rs.{a2} debited A/c XX{ac} on {d} Info: NEFT-{m}. Bal Rs {b2}",
]
HANDLE_T = "UPI txn of Rs {a2} paid to VPA {h} on {d}. Bal: Rs {b2}"
CREDIT_T = [
    "INR {a2} credited to A/c XX{ac} on {d} by {m}. Avl Bal INR {b2}",
    "Rs.{a2} credited to your a/c XX{ac} on {d}. Info: {m}. Avl Bal Rs {b2}",
    "Your A/c XX{ac} is credited with Rs {a0} on {d} by UPI from {m}. Avl Bal Rs {b2}",
    "A/c XX{ac} credited INR {a2} on {d} Info: {m}. Avl bal INR {b2}",
    "Dear Customer, Rs {a2} received in your a/c XX{ac} from {m} on {d}. Bal Rs {b2}",
    "Rs.{a2} Credited to A/c XX{ac} on {d} Info: IMPS-{r}-{m}. Bal Rs {b2}",
]
SUFFIX = ["PVT LTD", "LTD", "INDIA", "ONLINE", "PAYMENTS", "SERVICES", "BLR", "HYD", "MUMBAI", "DELHI", "CHENNAI", "IN", "LLP"]
PREFIX_D = ["UPI-", "POS ", "ECOM ", "PUR "]
PREFIX_C = ["NEFT-", "IMPS-", "UPI-"]
# plausible amount ranges (rupees, log-uniform) - deliberately wide and overlapping
AMT = {"elss_investment": (500, 150000), "life_insurance": (1500, 120000), "ppf_epf": (500, 150000), "tuition_fees": (2000, 300000),
       "nps": (500, 50000), "health_insurance": (2500, 80000), "preventive_healthcare": (400, 15000),
       "home_loan_interest": (5000, 150000), "donation": (100, 100000), "food_dining": (60, 4000), "groceries": (80, 9000),
       "shopping": (200, 60000), "transport": (20, 3000), "fuel": (100, 6000), "utilities": (150, 8000), "entertainment": (49, 5000),
       "travel": (300, 90000), "rent": (3000, 90000), "salary_income": (12000, 400000), "freelance_income": (2000, 600000),
       "other_income": (10, 100000), "uncategorized": (20, 60000)}


def _typo(s: str, rnd: random.Random) -> str:
    if len(s) < 6:
        return s
    i = rnd.randrange(1, len(s) - 1)
    op = rnd.choice("dsr")
    if op == "d":
        return s[:i] + s[i + 1:]
    if op == "s":
        return s[:i] + s[i + 1] + s[i] + s[i + 2:]
    return s[:i] + s[i] + s[i:]


def surfaces(base: str, credit: bool, rnd: random.Random, k: int):
    """k spelling variants of one entity (first is always the clean base name).
    Returns [(text_in_sms, is_handle, expected_merchant_after_parsing)]."""
    toks = base.split()
    pfx = rnd.choice(PREFIX_C if credit else PREFIX_D)
    opts = [
        lambda: (base + " " + rnd.choice(SUFFIX),) * 2,
        lambda: (base + " " + "".join(rnd.choices(string.digits, k=rnd.choice([4, 5, 6]))),) * 2,
        lambda: (" ".join(toks[:2]) if len(toks) >= 3 else base,) * 2,
        lambda: (_typo(base, rnd),) * 2,
        lambda: (pfx + base, base),                       # a bank prefix the parser should drop
        lambda: ((toks[0] + "*" + " ".join(toks[1:])) if len(toks) > 1 else base,) * 2,
    ]
    out = [(base, False, base)]
    for f in rnd.sample(opts, k=min(k - 1, len(opts))):
        t, clean = f()
        out.append((t, False, clean))
    if not credit and rnd.random() < 0.5:  # a UPI handle spelling for some entities
        sep = "" if rnd.random() < 0.5 else "."
        compact = sep.join(t.lower() for t in toks[:2])[:24]
        handle = compact + "@" + rnd.choice(["ybl", "oksbi", "okhdfcbank", "paytm", "axl", "icici"])
        out[-1] = (handle, True, compact.replace(".", " ").upper())
    return out[:k]


def _inr(x: float, dec: bool) -> str:
    s = f"{x:,.2f}" if dec else f"{x:,.0f}"
    return s


def _date(rnd: random.Random) -> str:
    d, m, y = rnd.randint(1, 28), rnd.randint(1, 12), rnd.choice([24, 25, 26])
    f = rnd.random()
    mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1]
    return f"{d:02d}-{m:02d}-{y}" if f < 0.45 else (f"{d:02d}/{m:02d}/20{y}" if f < 0.7 else f"{d:02d}-{mon}-{y}")


def render(cat: str, text: str, is_handle: bool, rnd: random.Random):
    credit = cat in CREDIT_CATEGORIES
    lo, hi = AMT[cat]
    import math
    a = math.exp(rnd.uniform(math.log(lo), math.log(hi)))
    if cat in ("rent", "elss_investment", "nps", "ppf_epf", "tuition_fees", "home_loan_interest", "salary_income") and rnd.random() < 0.6:
        a = max(500, round(a / 500) * 500)
    a = round(a) if rnd.random() < 0.55 else round(a, 2)
    bal = rnd.randint(2_000, 900_000) + rnd.random()
    fields = dict(a2=_inr(a, True), a0=_inr(round(a), False), b2=_inr(bal, True), d=_date(rnd), ac=str(rnd.randint(1000, 9999)),
                  r=str(rnd.randint(10**8, 10**9 - 1)), m=text, h=text)
    tmpl = HANDLE_T if is_handle else rnd.choice(CREDIT_T if credit else DEBIT_T)
    if "{a0}" in tmpl:  # the message shows the rounded figure, so the label must too
        a = float(round(a))
    return tmpl.format(**fields), float(round(a, 2)), ("credit" if credit else "debit")


def split_entities(seed: int):
    """entity -> split name, stratified by category."""
    rnd = random.Random(seed)
    out, seen = {}, set()
    for cat in CATEGORIES:
        ents = []
        for e in E[cat]:
            key = (e, cat in CREDIT_CATEGORIES)
            if key in seen:  # same spelling twice in the same direction would carry two labels
                continue
            seen.add(key)
            ents.append(e)
        rnd.shuffle(ents)
        n = len(ents)
        n_tr, n_va = max(2, round(n * SPLIT[0])), max(2, round(n * SPLIT[1]))
        for i, e in enumerate(ents):
            out[(cat, e)] = "train" if i < n_tr else ("val" if i < n_tr + n_va else "test")
    return out


def build_corpus(seed: int = 0, variants: int = 6):
    ent_split = split_entities(seed)
    rnd = random.Random(seed * 7919 + 13)
    rows = []
    for (cat, e), sp in sorted(ent_split.items()):
        credit = cat in CREDIT_CATEGORIES
        for text, is_handle, clean in surfaces(e, credit, rnd, variants):
            sms, amt, typ = render(cat, text, is_handle, rnd)
            rows.append({"sms": sms, "category": cat, "type": typ, "entity": e, "surface": text, "expected_merchant": clean,
                         "amount": amt, "split": sp})
    return rows


def write(rows, out=OUT):
    out.mkdir(parents=True, exist_ok=True)
    cols = ["sms", "category", "type", "entity", "surface", "expected_merchant", "amount"]
    for sp in ("train", "val", "test"):
        with (out / f"{sp}.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                if r["split"] == sp:
                    w.writerow({c: r[c] for c in cols})


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


if __name__ == "__main__":
    rows = build_corpus(0)
    write(rows)
    from collections import Counter
    c = Counter(r["split"] for r in rows)
    ents = {sp: {(r["category"], r["entity"]) for r in rows if r["split"] == sp} for sp in c}
    assert not (ents["train"] & ents["val"]) and not (ents["train"] & ents["test"]) and not (ents["val"] & ents["test"])
    print("rows:", dict(c), "| entities:", {k: len(v) for k, v in ents.items()}, "| classes:", len({r['category'] for r in rows}))
    for sp in ("train", "val", "test"):
        print(sp, checksum(OUT / f"{sp}.csv"))
