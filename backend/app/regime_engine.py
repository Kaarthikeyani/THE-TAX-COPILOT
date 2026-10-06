"""Old vs New regime tax engine (slab-based, 87A rebate + marginal relief, surcharge + marginal relief, 4% cess)
and the investment-timing counterfactual.

Rule sets are versioned by financial year. Freelancers: enter *net* taxable business income - no standard
deduction is applied.

SUPPORTED: resident individual below 60 / 60-79 / 80+ (old regime slabs only vary by age), salaried or
self-employed, regular slab income, deductions 80C, 80CCD(1B), 80D (self only), 24(b), 80G (flat, user-supplied).
NOT SUPPORTED (the app says so on screen): capital gains and their special rates (including ELSS gains),
HRA/LTA exemptions, employer NPS 80CCD(2), 80D for parents, losses carried forward, NRIs, HUFs, companies,
surcharge cap on dividend/capital-gain income, presumptive taxation (44AD/44ADA) mechanics, interest u/s 234A/B/C.
Provenance of every number: see RULES_META below and docs/TAX_RULES.md.
"""
from datetime import date
from typing import Dict, Optional

INF = float("inf")
CESS = 0.04

NEW_RULES = {
    "FY2024-25": {"std": 75000, "rebate_limit": 700000, "rebate_max": 25000,
                  "slabs": [(300000, 0.0), (700000, 0.05), (1000000, 0.10), (1200000, 0.15), (1500000, 0.20), (INF, 0.30)]},
    "FY2025-26": {"std": 75000, "rebate_limit": 1200000, "rebate_max": 60000,
                  "slabs": [(400000, 0.0), (800000, 0.05), (1200000, 0.10), (1600000, 0.15), (2000000, 0.20), (2400000, 0.25), (INF, 0.30)]},
}

RULES_META = {
    "last_verified": "2026-10-05",
    "verified_against": [
        "https://incometaxindia.gov.in/Documents/Tax-Calendar/Payment-of-Advance-Tax.htm (advance-tax dates, Rs 10,000 threshold, senior/44ADA exceptions)",
        "https://cleartax.in/s/income-tax-slabs (slabs, 87A, standard deduction, surcharge - SECONDARY source)",
        "https://www.businesstoday.in/amp/union-budget/story/budget-2026-what-deductions-exemptions-and-capital-gains-rules-under-the-new-income-tax-act-mean-for-taxpayers-513819-2026-02-01 (Income-tax Act 2025 renumbering - SECONDARY source)",
    ],
    "caveat": "Slabs for FY2026-27 are taken from secondary sources reporting no change from FY2025-26. "
              "Confirm against the Finance Act text / incometax.gov.in before relying on them. Not professional tax advice.",
    "new_act_sections": {"80C": "s.123 (Income-tax Act 2025)", "80CCD1B": "s.124", "80D": "s.126"},
}

# surcharge on slab tax: (income above, rate). New regime tops out at 25%; old regime at 37%.
SURCHARGE_NEW = [(0, 0.0), (5_000_000, 0.10), (10_000_000, 0.15), (20_000_000, 0.25)]
SURCHARGE_OLD = [(0, 0.0), (5_000_000, 0.10), (10_000_000, 0.15), (20_000_000, 0.25), (50_000_000, 0.37)]

CAPS = {"80C": 150000, "80CCD1B": 50000, "80D": 25000, "24b": 200000}
CAPS_SENIOR_80D = 50000


def fy_start_year(d: date) -> int:
    return d.year if d.month >= 4 else d.year - 1


def fy_label(start_year: int) -> str:
    return f"FY{start_year}-{str(start_year + 1)[-2:]}"


def rules_label_for(start_year: int) -> str:
    # FY2025-26 slabs are the latest enacted set; they are applied to later years until changed.
    return "FY2024-25" if start_year <= 2024 else "FY2025-26"


def old_slabs(age: int):
    exempt = 250000 if age < 60 else (300000 if age < 80 else 500000)
    return [(exempt, 0.0), (500000, 0.05), (1000000, 0.20), (INF, 0.30)]


def slab_tax(taxable: float, slabs) -> float:
    tax, prev = 0.0, 0.0
    for upper, rate in slabs:
        if taxable > prev:
            tax += (min(taxable, upper) - prev) * rate
        prev = upper
        if taxable <= upper:
            break
    return tax


def marginal_slab_rate(taxable: float, slabs) -> float:
    prev = 0.0
    for upper, rate in slabs:
        if taxable <= upper:
            return rate
        prev = upper
    return slabs[-1][1]


def cap_deductions(ded: Dict[str, float], age: int) -> Dict[str, float]:
    caps = dict(CAPS)
    if age >= 60:
        caps["80D"] = CAPS_SENIOR_80D
    out = {}
    for k, v in (ded or {}).items():
        v = max(0.0, float(v or 0))
        out[k] = round(min(v, caps[k]) if k in caps else v, 2)
    return out


def _sur_rate(income: float, table) -> float:
    r = 0.0
    for lo, rate in table:
        if income > lo:
            r = rate
    return r


def with_surcharge(income: float, base_fn, table):
    """Return (tax_incl_surcharge, surcharge). Applies marginal relief: the extra tax caused by crossing a
    surcharge threshold can never exceed the extra income earned above that threshold."""
    base = base_fn(income)
    rate = _sur_rate(income, table)
    if rate == 0:
        return base, 0.0
    total = base * (1 + rate)
    lo = max(t for t, _ in table if income > t)
    prev_rate = _sur_rate(lo, table)  # rate that applied at the threshold itself
    cap = base_fn(lo) * (1 + prev_rate) + (income - lo)
    total = min(total, cap)
    return total, max(0.0, total - base)


def new_regime_tax(gross: float, fy: int, salaried: bool = True) -> dict:
    r = NEW_RULES[rules_label_for(fy)]
    std = r["std"] if salaried else 0
    taxable = max(0.0, gross - std)
    base = slab_tax(taxable, r["slabs"])
    rebate = 0.0
    if taxable <= r["rebate_limit"]:
        rebate = min(base, r["rebate_max"])
    elif base > taxable - r["rebate_limit"]:  # marginal relief just above the rebate threshold
        rebate = base - (taxable - r["rebate_limit"])
    after = max(0.0, base - rebate)

    def _base(x):  # slab tax after 87A rebate / marginal relief, before surcharge and cess
        b = slab_tax(x, r["slabs"])
        if x <= r["rebate_limit"]:
            return max(0.0, b - min(b, r["rebate_max"]))
        return min(b, x - r["rebate_limit"])
    total_sur, sur = with_surcharge(taxable, _base, SURCHARGE_NEW)
    after = after + sur
    cess = after * CESS
    return {"regime": "new", "gross": gross, "standard_deduction": std, "deductions": {},
            "deductions_total": 0.0, "taxable_income": round(taxable, 2),
            "slab_tax": round(base, 2), "rebate_87a": round(rebate, 2), "surcharge": round(sur, 2), "cess": round(cess, 2),
            "total_tax": round(after + cess, 2),
            "effective_rate": round((after + cess) / gross * 100, 2) if gross else 0.0,
            "marginal_rate": round(marginal_slab_rate(taxable, r["slabs"]) * (1 + CESS) * 100, 1) if rebate == 0 else 0.0}


def old_regime_tax(gross: float, ded: Dict[str, float], age: int, fy: int, salaried: bool = True) -> dict:
    capped = cap_deductions(ded, age)
    total_ded = sum(capped.values())
    std = 50000 if salaried else 0
    taxable = max(0.0, gross - std - total_ded)
    slabs = old_slabs(age)
    base = slab_tax(taxable, slabs)
    rebate = min(base, 12500) if taxable <= 500000 else 0.0
    after = max(0.0, base - rebate)
    _b = lambda x: max(0.0, slab_tax(x, slabs) - (min(slab_tax(x, slabs), 12500) if x <= 500000 else 0.0))
    total_sur, sur = with_surcharge(taxable, _b, SURCHARGE_OLD)
    after = after + sur
    cess = after * CESS
    return {"regime": "old", "gross": gross, "standard_deduction": std, "deductions": capped,
            "deductions_total": round(total_ded, 2), "taxable_income": round(taxable, 2),
            "slab_tax": round(base, 2), "rebate_87a": round(rebate, 2), "surcharge": round(sur, 2), "cess": round(cess, 2),
            "total_tax": round(after + cess, 2),
            "effective_rate": round((after + cess) / gross * 100, 2) if gross else 0.0,
            "marginal_rate": round(marginal_slab_rate(taxable, slabs) * (1 + CESS) * 100, 1) if rebate == 0 else 0.0}


def breakeven_deductions(gross: float, age: int, fy: int, salaried: bool = True) -> Optional[float]:
    """Total old-regime deductions (80C, 80D, 24b ...) at which the old regime matches the new regime."""
    target = new_regime_tax(gross, fy, salaried)["total_tax"]
    if old_regime_tax(gross, {}, age, fy, salaried)["total_tax"] <= target:
        return 0.0
    lo, hi = 0.0, gross
    if old_regime_tax(gross, {"x": hi}, age, fy, salaried)["total_tax"] > target:
        return None
    for _ in range(40):
        mid = (lo + hi) / 2
        if old_regime_tax(gross, {"x": mid}, age, fy, salaried)["total_tax"] <= target:
            hi = mid
        else:
            lo = mid
    return round(hi, -2)


def compare(gross: float, ded: Optional[Dict[str, float]], age: int, fy: int, salaried: bool = True) -> dict:
    new = new_regime_tax(gross, fy, salaried)
    old = old_regime_tax(gross, ded or {}, age, fy, salaried)
    better = "old" if old["total_tax"] < new["total_tax"] else "new"
    saving = abs(old["total_tax"] - new["total_tax"])
    best = old if better == "old" else new
    return {"fy": fy_label(fy), "rules": rules_label_for(fy), "old": old, "new": new,
            "recommended": better, "saving_by_choosing": round(saving, 2),
            "best_tax": best["total_tax"],
            "breakeven_deductions": breakeven_deductions(gross, age, fy, salaried) if gross > 0 else None,
            "note": "Decision-support only, not tax advice. Capital gains, HRA/LTA, employer NPS and other special cases are not modelled.",
            "rules_meta": {"last_verified": RULES_META["last_verified"], "caveat": RULES_META["caveat"]}}


def counterfactual(amount: float, days_earlier: int, annual_return: float = 0.12) -> dict:
    """If `amount` had been invested `days_earlier` days sooner at an assumed annual return."""
    amount = max(0.0, float(amount))
    days_earlier = max(0, int(days_earlier))
    extra = amount * ((1 + annual_return) ** (days_earlier / 365.0) - 1)
    return {"amount": round(amount, 2), "days_earlier": days_earlier,
            "assumed_annual_return_pct": round(annual_return * 100, 2),
            "extra_earned": round(extra, 2),
            "message": f"If you had moved Rs {amount:,.0f} to ELSS {days_earlier} days earlier, "
                       f"you would have earned about Rs {extra:,.0f} more (assuming {annual_return*100:.0f}% a year; "
                       f"market returns are not guaranteed)."}
