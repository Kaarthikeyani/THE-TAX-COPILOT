"""Monte-Carlo backtest of the monthly planner against simple investing rules (SYNTHETIC income paths).

   python experiments/planner_backtest.py [--n 300]   -> results/planner_backtest.json

World: a self-employed person, expected income m per month with lognormal noise sigma, fixed expenses e, opening
cash, a monthly tax reserve identical for every policy. Five policies (incl. 'none' = never invest, the baseline breach rate caused by income noise alone) decide how much to put into 80C each month
(cap 1.5 lakh for the year). Metrics: probability that month-end cash ever falls below the buffer (3 months of
expenses) or below zero, mean deduction captured, and mean tax saved under the better regime (engine of the app).
Not modelled: market returns, advance-tax interest, behavioural effects. Results describe the *policy*, not real life.
"""
import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.monthly_planner import FY_MONTHS, PlanInputs, month_key, plan_months  # noqa: E402
from app.regime_engine import compare  # noqa: E402

FY = 2026
CAP = 150000.0
OTHER = 450000.0  # other old-regime deductions (rent/HRA-type, home-loan interest...) so that the old regime can win
OUT = Path(__file__).resolve().parent / "results"


def tax_saved(gross, invested):
    a = compare(gross, {"80C": invested, "other": OTHER}, 30, FY, False)["best_tax"]
    b = compare(gross, {"other": OTHER}, 30, FY, False)["best_tax"]
    return b - a


def simulate(policy, rng, m, sigma, e, open_cash, buffer_months=3.0):
    mu = math.log(m) - sigma ** 2 / 2
    inc = np.exp(rng.normal(mu, sigma, 12))
    cash, invested, hist, ded = open_cash, 0.0, {}, {}
    breach = ruin = False
    reserve = 0.12  # monthly tax reserve share, same for all policies
    for t in range(12):
        key = month_key(FY, t)
        mon = FY_MONTHS[t]
        yr = FY if mon >= 4 else FY + 1
        # policy decision at start of month t: income is not yet known, history is
        if policy == "adaptive":
            p = plan_months(PlanInputs(today=date(yr, mon, 10), fy=FY, balance=cash, income_type="freelancer",
                                       profile_annual_income=m * 12, profile_monthly_expenses=e,
                                       income_history=dict(hist), expense_history={k: e for k in hist},
                                       deductions_used={**ded, "other": OTHER}, buffer_months=buffer_months, use_milp=False))
            row = next(r for r in p["months"] if r["status"] == "current")
            x = min(row["tax_saving_invest"] or 0.0, CAP - invested)
        elif policy == "none":
            x = 0.0
        elif policy == "upfront":
            x = CAP if t == 0 else 0.0
        elif policy == "equal_sip":
            x = CAP / 12
        else:  # march lump
            x = CAP - invested if t == 11 else 0.0
        x = max(0.0, min(x, CAP - invested))
        cash += inc[t] * (1 - reserve) - e - x
        invested += x
        ded["80C"] = invested
        hist[key] = float(inc[t])
        if cash < buffer_months * e:
            breach = True
        if cash < 0:
            ruin = True
    return breach, ruin, invested, tax_saved(float(inc.sum()), invested)


def run(n=300, seed=0):
    rng = np.random.default_rng(seed)
    res = []
    for sigma in (0.10, 0.25, 0.45):
        for pol in ("none", "adaptive", "upfront", "equal_sip", "march_lump"):
            r = np.random.default_rng(seed + int(sigma * 1000))  # same income paths for every policy
            out = [simulate(pol, r, 130000, sigma, 85000, 250000) for _ in range(n)]
            b = np.array([o[0] for o in out]); ru = np.array([o[1] for o in out])
            res.append({"sigma": sigma, "policy": pol, "n": n,
                        "p_breach_buffer": float(b.mean()), "p_cash_negative": float(ru.mean()),
                        "mean_invested": float(np.mean([o[2] for o in out])),
                        "mean_tax_saved": float(np.mean([o[3] for o in out]))})
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=300)
    n = ap.parse_args().n
    res = run(n)
    OUT.mkdir(exist_ok=True)
    (OUT / "planner_backtest.json").write_text(json.dumps({"label": "SYNTHETIC", "world": "freelancer, m=1.3L/month, expenses 85k, opening cash 2.5L, buffer 3 months, 12% tax reserve, 4.5L other old-regime deductions", "rows": res}, indent=1))
    for r in res:
        print(f"sigma {r['sigma']:.2f} {r['policy']:<10} breach {r['p_breach_buffer']:.2f} negative {r['p_cash_negative']:.2f} invested {r['mean_invested']:>8.0f} tax saved {r['mean_tax_saved']:>7.0f}")
