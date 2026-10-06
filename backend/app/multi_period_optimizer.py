"""Chance-constrained MILP over India's advance-tax quarters, solved with PuLP/CBC.

Model
-----
* Monthly income ~ Lognormal(mu, sigma) fitted from trailing history.
* Cumulative income over M months is approximated as Normal (moment matched). The liquidity
  chance constraint  P(cash_t >= buffer) >= alpha  is replaced by its deterministic equivalent
  using the (1-alpha) quantile of cumulative income:  L_t = M*m + z_(1-alpha) * sqrt(M*v)
  (closed form with NormalDist().inv_cdf).
* Decision x[s,t] = amount invested in section s at period t, with a minimum-ticket binary y[s,t].
* Cumulative statutory caps are enforced per section across periods.
* Advance-tax cash reservation P_t is binding: cumulative payment >= cum% * estimated tax - paid.
* The quadratic risk term is linearised (no commercial solver needed).
"""
import math
from calendar import monthrange
from datetime import date
from statistics import NormalDist
from typing import Dict, List, Optional

import pulp

SECTIONS = ["80C", "80CCD1B", "80D"]
MIN_TICKET = {"80C": 1000.0, "80CCD1B": 1000.0, "80D": 500.0}
QUARTERS = [("Q1", 6, 15, 0.15), ("Q2", 9, 15, 0.45), ("Q3", 12, 15, 0.75), ("Q4", 3, 15, 1.00)]


def fit_lognormal(samples: List[float], fallback_mean: float):
    pos = [s for s in samples if s and s > 0]
    if len(pos) >= 3:
        logs = [math.log(s) for s in pos]
        mu = sum(logs) / len(logs)
        var = sum((l - mu) ** 2 for l in logs) / (len(logs) - 1)
        sigma = max(math.sqrt(var), 0.05)
        return mu, sigma, "fitted"
    mean = max(fallback_mean, 1.0)
    sigma = 0.25
    return math.log(mean) - sigma ** 2 / 2, sigma, "assumed"


def lognormal_moments(mu: float, sigma: float):
    m = math.exp(mu + sigma ** 2 / 2)
    v = (math.exp(sigma ** 2) - 1) * math.exp(2 * mu + sigma ** 2)
    return m, v


def cumulative_income_quantile(months: float, mu: float, sigma: float, alpha: float) -> float:
    m, v = lognormal_moments(mu, sigma)
    z = NormalDist().inv_cdf(1 - alpha)
    return max(0.0, months * m + z * math.sqrt(months * v))


def _due_dates(today: date, fy: int) -> List[dict]:
    out = []
    for name, month, day, pct in QUARTERS:
        year = fy if month >= 4 else fy + 1
        out.append({"name": name, "due": date(year, month, day), "cum_pct": pct})
    remaining = [q for q in out if q["due"] >= today]
    if not remaining:  # after 15 Mar: final window is the FY end
        remaining = [{"name": "FY-end", "due": date(fy + 1, 3, 31), "cum_pct": 1.0}]
    return remaining


def _months_between(a: date, b: date) -> float:
    return max(0.25, (b - a).days / 30.4375)


def solve_plan(*, today: date, fy: int, balance: float, monthly_expenses: float, buffer_months: float,
               alpha: float, income_samples: List[float], mean_income_hint: float,
               tax_now: float, avg_saving_rate: float, headroom: Dict[str, float],
               tax_paid: float = 0.0) -> dict:
    alpha = min(max(alpha, 0.5), 0.99)
    mu, sigma, mode = fit_lognormal(income_samples, mean_income_hint)
    periods = _due_dates(today, fy)
    T = len(periods)
    buffer = buffer_months * monthly_expenses

    prev = today
    for p in periods:
        p["months"] = _months_between(prev, p["due"])
        prev = p["due"]
    cum_months, acc = [], 0.0
    for p in periods:
        acc += p["months"]
        cum_months.append(acc)
    income_low = [cumulative_income_quantile(M, mu, sigma, alpha) for M in cum_months]
    m_mean, _ = lognormal_moments(mu, sigma)
    income_mean = [M * m_mean for M in cum_months]
    expenses = [M * monthly_expenses for M in cum_months]

    prob = pulp.LpProblem("tax_cashflow_plan", pulp.LpMaximize)
    x = {(s, t): pulp.LpVariable(f"x_{s}_{t}", lowBound=0) for s in SECTIONS for t in range(T)}
    y = {(s, t): pulp.LpVariable(f"y_{s}_{t}", cat="Binary") for s in SECTIONS for t in range(T)}
    P = {t: pulp.LpVariable(f"P_{t}", lowBound=0) for t in range(T)}  # cumulative advance tax paid by t

    r = max(0.0, avg_saving_rate)
    total_x = pulp.lpSum(x.values())
    w = {t: 1.0 + 0.02 * (T - t) / T for t in range(T)}  # mild preference for investing earlier
    prob += r * pulp.lpSum(w[t] * x[(s, t)] for s in SECTIONS for t in range(T)) \
        - 50 * pulp.lpSum(y.values()) \
        - 0.001 * pulp.lpSum(P.values())

    for s in SECTIONS:
        cap = max(0.0, headroom.get(s, 0.0))
        prob += pulp.lpSum(x[(s, t)] for t in range(T)) <= cap
        for t in range(T):
            prob += x[(s, t)] <= cap * y[(s, t)]
            prob += x[(s, t)] >= min(MIN_TICKET[s], cap) * y[(s, t)] if cap > 0 else x[(s, t)] >= 0

    for t in range(T):
        est_tax = tax_now - r * pulp.lpSum(x[(s, k)] for s in SECTIONS for k in range(T))
        if tax_now >= 10000:  # advance tax applies at Rs 10,000+
            prob += P[t] >= periods[t]["cum_pct"] * est_tax - tax_paid
        cash = balance + income_low[t] - expenses[t] - P[t] \
            - pulp.lpSum(x[(s, k)] for s in SECTIONS for k in range(t + 1))
        prob += cash >= buffer

    status = prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=15))
    status_name = pulp.LpStatus[status]
    feasible = status_name == "Optimal"

    rows, prev_cum_pay = [], 0.0
    invest_total = 0.0
    for t, p in enumerate(periods):
        inv = {s: round(x[(s, t)].value() or 0.0, 0) if feasible else 0.0 for s in SECTIONS}
        cum_pay = (P[t].value() or 0.0) if feasible else 0.0
        cum_pay = max(cum_pay, prev_cum_pay)
        pay = cum_pay - prev_cum_pay
        prev_cum_pay = cum_pay
        spent_inv = sum(
            round(x[(s, k)].value() or 0.0, 0) for s in SECTIONS for k in range(t + 1)) if feasible else 0.0
        cash_q = balance + income_low[t] - expenses[t] - cum_pay - spent_inv
        invest_total += sum(inv.values())
        rows.append({
            "quarter": p["name"], "due_date": p["due"].isoformat(), "months": round(p["months"], 1),
            "expected_income_cum": round(income_mean[t]), "income_at_quantile_cum": round(income_low[t]),
            "expenses_cum": round(expenses[t]),
            "advance_tax_due": round(pay), "invest": inv, "invest_total": round(sum(inv.values())),
            "cash_at_quantile": round(cash_q), "buffer_required": round(buffer),
            "liquidity_ok": cash_q + 1 >= buffer,
        })
    return {"status": status_name, "feasible": feasible, "alpha": alpha,
            "income_model": {"type": "lognormal", "mu": round(mu, 4), "sigma": round(sigma, 4),
                             "mean_monthly": round(m_mean), "source": mode, "samples": len(income_samples)},
            "z_score": round(NormalDist().inv_cdf(1 - alpha), 3),
            "periods": rows, "total_invest": round(invest_total), "buffer": round(buffer)}


def single_period_allocation(investable: float, headroom: Dict[str, float], avg_saving_rate: float) -> dict:
    """One-shot MILP: split today's investable cash across sections for max tax saving."""
    prob = pulp.LpProblem("single_period", pulp.LpMaximize)
    x = {s: pulp.LpVariable(f"x_{s}", lowBound=0) for s in SECTIONS}
    y = {s: pulp.LpVariable(f"y_{s}", cat="Binary") for s in SECTIONS}
    pref = {"80D": 1.003, "80CCD1B": 1.002, "80C": 1.001}  # tie-break: protect first, then pension, then 80C
    prob += avg_saving_rate * pulp.lpSum(pref[s] * x[s] for s in SECTIONS) - 2 * pulp.lpSum(y.values())
    prob += pulp.lpSum(x.values()) <= max(0.0, investable)
    for s in SECTIONS:
        cap = max(0.0, headroom.get(s, 0.0))
        prob += x[s] <= cap * y[s]
        if cap > 0:
            prob += x[s] >= min(MIN_TICKET[s], cap) * y[s]
    status = pulp.LpStatus[prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=10))]
    alloc = {s: round(x[s].value() or 0.0) if status == "Optimal" else 0 for s in SECTIONS}
    return {"status": status, "investable_cash": round(max(0.0, investable)), "allocation": alloc,
            "total": sum(alloc.values())}
