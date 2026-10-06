"""Month-by-month cash-flow and investment planner (pure functions, no database access).

WHAT IT DOES
For every month of the financial year (April..March) it produces: income (actual if received, else expected
and a cautious "conservative" figure), expenses, known bills, advance tax due that month, the cash left at
month end, how much is *safe to invest*, how much of that is worth putting into tax-saving sections, and the
tax-saving room that remains. Past months show actuals. Future months adapt: every actual income or expense
re-fits the forecast the next time the plan is computed.

HOW "SAFE TO INVEST" IS DEFINED (this is the core idea)
Let C_s be the cash at the end of month s on the *conservative* path (income at the (1-alpha) quantile,
expenses with a small overrun allowance, all known bills and advance-tax instalments paid) and B the
emergency buffer. Investing x in month t lowers every later C_s by x, so the largest amount that keeps the
buffer intact in *all* later months is

        safe_t = max(0, min_{s >= t} (C_s - already_scheduled_s - B)).

A tax-saving investment is never recommended above safe_t, and never when the deduction would not lower the
tax under the better regime. Quarterly logic is reused only for the statutory advance-tax calendar.

WHAT IT IS NOT
It is decision support, not advice. It does not model market returns, capital gains tax on the investments,
interest under sections 234A/B/C, or any income source other than the figures supplied.
"""
from __future__ import annotations

import math
from calendar import month_abbr
from dataclasses import dataclass, field
from datetime import date
from statistics import NormalDist
from typing import Dict, List, Optional, Tuple

from .multi_period_optimizer import MIN_TICKET, SECTIONS, single_period_allocation
from .regime_engine import CAPS, CAPS_SENIOR_80D, compare, fy_label

FY_MONTHS = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
ADV_TAX = {2: 0.15, 5: 0.45, 8: 0.75, 11: 1.00}  # month index (Apr=0) -> cumulative share (Jun, Sep, Dec, Mar)
ADV_TAX_DAY = 15
ADV_TAX_THRESHOLD = 10000.0
PRIOR_SIGMA = {"freelancer": 0.25, "salaried": 0.05}
SIGMA_FLOOR = {"freelancer": 0.08, "salaried": 0.02}
STRATEGIES = ("even", "asap", "late")


@dataclass
class PlanInputs:
    today: date
    fy: int
    balance: float
    income_type: str = "freelancer"            # salaried | freelancer
    age: int = 30
    profile_annual_income: float = 0.0         # 0 = unknown
    profile_monthly_expenses: float = 0.0
    income_history: Dict[str, float] = field(default_factory=dict)   # 'YYYY-MM' -> income actually received
    expense_history: Dict[str, float] = field(default_factory=dict)  # 'YYYY-MM' -> regular expenses (months with data only)
    saving_actual: Dict[str, float] = field(default_factory=dict)    # 'YYYY-MM' -> tax-saving money actually invested
    deductions_used: Dict[str, float] = field(default_factory=dict)  # FY-to-date used per section (80C, 80CCD1B, 80D, 24b)
    bills: List[Tuple[str, str, float]] = field(default_factory=list)  # (YYYY-MM, name, amount), already expanded
    advance_tax_paid: float = 0.0
    # assumptions the user can change
    buffer_months: float = 3.0
    alpha: float = 0.9                          # confidence that cash stays above the buffer
    expected_income_override: Optional[float] = None
    sigma_override: Optional[float] = None
    expected_expense_override: Optional[float] = None
    expense_overrun_pct: float = 5.0
    tds_share: Optional[float] = None           # share of tax deducted at source; default by income type
    business_expense_pct: float = 0.0           # % of receipts treated as deductible business expense
    presumptive_44ada: bool = False             # 50% presumptive income + one advance-tax instalment in March
    strategy: str = "even"                      # even | asap | late
    income_shock_pct: float = 0.0               # what-if: expected income changes by this % from next month on
    use_milp: bool = True                       # False = greedy allocation (identical objective, used for simulation)


def month_key(fy: int, idx: int) -> str:
    y = fy if FY_MONTHS[idx] >= 4 else fy + 1
    return f"{y}-{FY_MONTHS[idx]:02d}"


def month_name(fy: int, idx: int) -> str:
    y = fy if FY_MONTHS[idx] >= 4 else fy + 1
    return f"{month_abbr[FY_MONTHS[idx]]} {y}"


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def _income_model(inp: PlanInputs, exclude: str = ""):
    """Return (expected_monthly, sigma, notes, assumed_flags). Shrinks history toward the profile figure and
    pools the sample log-variance with a prior so a handful of months cannot produce a silly sigma."""
    notes, flags = [], {}
    hist = [v for k, v in sorted(inp.income_history.items()) if v and v > 0 and k < (exclude or "9999")][-12:]  # complete months only
    n = len(hist)
    base = inp.profile_annual_income / 12 if inp.profile_annual_income and inp.profile_annual_income > 0 else None
    hist_mean = _mean(hist)
    if inp.expected_income_override is not None:
        exp, flags["expected_income"] = float(inp.expected_income_override), "you"
    elif base and n:
        w = n / (n + 3.0)
        exp, flags["expected_income"] = w * hist_mean + (1 - w) * base, "blend"
        notes.append(f"Expected income blends {n} months of history (weight {w:.0%}) with the yearly figure in your profile.")
    elif n:
        exp, flags["expected_income"] = hist_mean, "history"
    elif base:
        exp, flags["expected_income"] = base, "profile"
    else:
        exp, flags["expected_income"] = 0.0, "missing"
        notes.append("No income data: add your yearly income in Profile or record monthly income.")
    prior = PRIOR_SIGMA.get(inp.income_type, 0.25)
    floor = SIGMA_FLOOR.get(inp.income_type, 0.08)
    if inp.sigma_override is not None:
        sigma, flags["sigma"] = max(float(inp.sigma_override), 0.0), "you"
    elif n >= 3:
        logs = [math.log(v) for v in hist]
        mu = _mean(logs)
        s2 = sum((l - mu) ** 2 for l in logs) / (n - 1)
        sigma = math.sqrt((n * s2 + 3 * prior ** 2) / (n + 3))  # pooled with the prior
        sigma = max(sigma, floor)
        flags["sigma"] = "history"
        if n < 6:
            notes.append(f"Only {n} months of income history: volatility is partly assumed, so the cautious case is wide.")
    else:
        sigma, flags["sigma"] = prior, "assumed"
        notes.append(f"Fewer than 3 months of income history: volatility assumed at {prior:.0%} "
                     f"({'typical for self-employed income' if inp.income_type == 'freelancer' else 'typical for salary'}).")
    return exp, sigma, notes, flags


def _moments(mean: float, sigma: float):
    """Mean and variance of a lognormal with the given mean and log-sd."""
    v = (math.exp(sigma ** 2) - 1) * mean ** 2
    return mean, v


def _cum_quantile(months: float, mean: float, sigma: float, alpha: float) -> float:
    """(1-alpha) quantile of the cumulative income over `months` months (normal approximation, iid months)."""
    if months <= 0 or mean <= 0:
        return 0.0
    m, v = _moments(mean, sigma)
    z = NormalDist().inv_cdf(1 - alpha)
    return max(0.0, months * m + z * math.sqrt(months * v))


def _expense_model(inp: PlanInputs, exclude: str = ""):
    hist = [v for k, v in sorted(inp.expense_history.items()) if v and v > 0 and k < (exclude or "9999")][-6:]
    prof = inp.profile_monthly_expenses or 0.0
    notes = []
    if inp.expected_expense_override is not None:
        return float(inp.expected_expense_override), "you", notes
    if hist and prof:
        w = len(hist) / (len(hist) + 3.0)
        return w * _mean(hist) + (1 - w) * prof, "blend", notes
    if hist:
        return _mean(hist), "history", notes
    if prof:
        notes.append("No expense history from bank messages: using the monthly expenses typed in Profile.")
        return prof, "profile", notes
    notes.append("No expense data: expenses assumed to be zero, which overstates what is safe to invest.")
    return 0.0, "missing", notes


def _caps(age: int):
    c = dict(CAPS)
    if age >= 60:
        c["80D"] = CAPS_SENIOR_80D
    return c


def _greedy_alloc(investable: float, headroom: Dict[str, float]) -> dict:
    """Priority fill (80D, then NPS, then 80C). Same optimum as the one-shot MILP because every section has
    the same tax-saving rate; used where thousands of plans must be computed."""
    left, alloc = max(0.0, investable), {s: 0 for s in SECTIONS}
    for s in ("80D", "80CCD1B", "80C"):
        cap = max(0.0, headroom.get(s, 0.0))
        amt = min(cap, left)
        if amt >= min(MIN_TICKET[s], cap) and amt > 0:
            alloc[s] = int(round(amt))
            left -= alloc[s]
    return {"allocation": alloc, "total": sum(alloc.values())}


def _tax(inp: PlanInputs, annual_income: float, extra: Dict[str, float]):
    ded = {k: v for k, v in inp.deductions_used.items()}
    for k, v in extra.items():
        ded[k] = ded.get(k, 0.0) + v
    pct = 50.0 if inp.presumptive_44ada else inp.business_expense_pct
    taxable_basis = annual_income * (1 - max(0.0, min(pct, 100.0)) / 100.0) if inp.income_type == "freelancer" else annual_income
    return compare(taxable_basis, ded, inp.age, inp.fy, inp.income_type == "salaried")


def plan_months(inp: PlanInputs) -> dict:
    fy = inp.fy
    alpha = min(max(inp.alpha, 0.5), 0.99)
    idx_cur = (inp.today.month - 4) % 12
    cur_key = month_key(fy, idx_cur)
    exp_inc, sigma, inc_notes, flags = _income_model(inp, cur_key)
    exp_exp, exp_src, exp_notes = _expense_model(inp, cur_key)
    tds_share = inp.tds_share if inp.tds_share is not None else (0.9 if inp.income_type == "salaried" else 0.0)
    overrun = 1 + max(0.0, inp.expense_overrun_pct) / 100.0
    buffer = max(0.0, inp.buffer_months) * exp_exp
    caps = _caps(inp.age)
    missing, warnings = [], []
    if flags["expected_income"] == "missing":
        missing.append("income")
    if exp_src == "missing":
        missing.append("expenses")
    if inp.income_type == "freelancer" and len([1 for k, v in inp.income_history.items() if v and k < cur_key]) < 6:
        warnings.append("Self-employed income is volatile and you have under 6 months of history, so treat future months as rough.")

    # income expected per month (what-if shock applies to months after the current one)
    def exp_for(idx):
        return exp_inc * (1 + inp.income_shock_pct / 100.0) if idx > idx_cur else exp_inc

    # ---- projected annual income (actual where received, expected elsewhere)
    ytd_actual, annual_est, est_flags = 0.0, 0.0, 0
    for idx in range(12):
        k = month_key(fy, idx)
        got = inp.income_history.get(k)
        if idx < idx_cur:
            if got is not None:
                annual_est += got
                ytd_actual += got
            else:
                annual_est += exp_for(idx)
                est_flags += 1
        elif idx == idx_cur:
            annual_est += max(got or 0.0, exp_for(idx))
            ytd_actual += got or 0.0
        else:
            annual_est += exp_for(idx)
    if est_flags:
        warnings.append(f"{est_flags} earlier month(s) have no income record; the yearly estimate uses the expected figure for them.")

    # ---- tax, advance-tax instalments
    tax0 = _tax(inp, annual_est, {})
    est_tax = tax0["best_tax"]
    senior_exempt = inp.age >= 60 and inp.income_type == "salaried"
    net_liab = est_tax * (1 - tds_share)
    adv_applies = (net_liab >= ADV_TAX_THRESHOLD) and not senior_exempt
    inst_due: Dict[int, float] = {}
    inst_notes: Dict[int, str] = {}
    if senior_exempt:
        warnings.append("Resident seniors with no business income are not liable for advance tax, so none is scheduled.")
    elif not adv_applies:
        warnings.append("Estimated tax after TDS is under Rs 10,000, so no advance tax is scheduled.")
    else:
        schedule = {11: 1.0} if inp.presumptive_44ada else ADV_TAX
        paid, scheduled = max(0.0, inp.advance_tax_paid), 0.0
        for idx in sorted(schedule):
            target = schedule[idx] * net_liab
            amt = max(0.0, target - paid - scheduled)
            if amt <= 0:
                continue
            if idx < idx_cur:  # missed instalment: owed now
                inst_due[idx_cur] = inst_due.get(idx_cur, 0.0) + amt
                inst_notes[idx_cur] = f"catch-up for the {month_abbr[FY_MONTHS[idx]]} instalment (interest under 234C is not computed)"
            else:
                inst_due[idx] = inst_due.get(idx, 0.0) + amt
                inst_notes.setdefault(idx, f"{ADV_TAX_DAY} {month_abbr[FY_MONTHS[idx]]} instalment")
            scheduled += amt

    # ---- conservative cash path with NO new investing
    exp_rem_cur = max(0.0, exp_for(idx_cur) - (inp.income_history.get(cur_key) or 0.0))
    frac = min(1.0, exp_rem_cur / exp_inc) if exp_inc > 0 else 0.0
    exp_actual_cur = inp.expense_history.get(cur_key) or 0.0
    bills_by_month: Dict[str, float] = {}
    for mk, _, amt in inp.bills:
        bills_by_month[mk] = bills_by_month.get(mk, 0.0) + amt

    rows: List[dict] = []
    cash_c = cash_e = inp.balance  # conservative / expected running cash (before new investing)
    cur_cons = _cum_quantile(frac, exp_inc, sigma, alpha)
    fut_prev = 0.0
    for idx in range(12):
        k = month_key(fy, idx)
        row = {"month": k, "label": month_name(fy, idx), "index": idx,
               "status": "past" if idx < idx_cur else ("current" if idx == idx_cur else "future")}
        got = inp.income_history.get(k)
        if idx < idx_cur:
            row.update({"income_actual": got, "income_expected": round(exp_for(idx)),
                        "expenses_actual": inp.expense_history.get(k),
                        "invested_actual": round(inp.saving_actual.get(k, 0.0)),
                        "income_variance": round(got - exp_for(idx)) if got is not None else None})
            rows.append(row)
            continue
        j = idx - idx_cur  # months after the current one
        if j == 0:
            income_cons = cur_cons
        else:
            q_now = _cum_quantile(j, exp_for(idx), sigma, alpha)
            income_cons = max(0.0, q_now - fut_prev)
            fut_prev = q_now
        if idx == idx_cur:
            income_exp_m = exp_rem_cur
            exp_m = max(0.0, exp_exp - exp_actual_cur)
        else:
            income_exp_m = exp_for(idx)
            exp_m = exp_exp
        expense_cons = exp_m * overrun
        bills = bills_by_month.get(k, 0.0)
        tax_due = inst_due.get(idx, 0.0)
        cash_c += income_cons - expense_cons - bills - tax_due
        cash_e += income_exp_m - exp_m - bills - tax_due
        row.update({"income_actual": got, "income_expected": round(exp_for(idx) if idx else exp_inc),
                    "income_remaining_expected": round(income_exp_m), "income_conservative": round(income_cons),
                    "expenses": round(exp_m), "expenses_conservative": round(expense_cons), "bills": round(bills),
                    "advance_tax_due": round(tax_due), "advance_tax_note": inst_notes.get(idx, ""),
                    "_cash_c0": cash_c, "_cash_e0": cash_e})
        rows.append(row)

    live = [r for r in rows if r["status"] != "past"]

    # ---- sequential investing decisions
    room = {s: max(0.0, caps[s] - inp.deductions_used.get(s, 0.0)) for s in SECTIONS}
    room_total0 = sum(room.values())
    full_extra = dict(room)
    tax_full = _tax(inp, annual_est, full_extra)["best_tax"]
    deduction_helps = (est_tax - tax_full) > 1.0
    rate = (est_tax - tax_full) / room_total0 if (room_total0 > 0 and deduction_helps) else 0.0
    best_regime_now = tax0["recommended"]
    scheduled_cum = 0.0
    scheduled_tax_invest = 0.0
    alloc_totals = {s: 0.0 for s in SECTIONS}
    cum_alloc = {s: 0.0 for s in SECTIONS}
    n_live = len(live)
    for pos, r in enumerate(live):
        # safe amount: tightest later month on each path
        later_c = [x["_cash_c0"] - scheduled_cum - buffer for x in live[pos:]]
        later_e = [x["_cash_e0"] - scheduled_cum - buffer for x in live[pos:]]
        safe = max(0.0, min(later_c))
        safe_if_on_plan = max(0.0, min(later_e))
        bind = live[pos + min(range(len(later_c)), key=lambda i: later_c[i])]
        room_left = sum(room[s] - cum_alloc[s] for s in SECTIONS)
        months_left = n_live - pos
        if rate <= 0 or room_left <= 0:
            target = 0.0
        elif inp.strategy == "asap":
            target = room_left
        elif inp.strategy == "late":  # Jan-Mar only, spread over the months that remain
            target = room_left / max(1, 12 - r["index"]) if r["index"] >= 9 else 0.0
        else:
            target = room_left / months_left
        invest_tax = min(safe, target)
        headroom_now = {s: max(0.0, room[s] - cum_alloc[s]) for s in SECTIONS}
        if invest_tax < min(MIN_TICKET.values()):
            alloc = {"allocation": {s: 0 for s in SECTIONS}, "total": 0}
        elif inp.use_milp:
            alloc = single_period_allocation(invest_tax, headroom_now, rate)
        else:
            alloc = _greedy_alloc(invest_tax, headroom_now)
        got_total = float(alloc["total"])
        for s in SECTIONS:
            cum_alloc[s] += alloc["allocation"][s]
        scheduled_cum += got_total
        scheduled_tax_invest += got_total
        cash_c_end = r["_cash_c0"] - scheduled_cum
        cash_e_end = r["_cash_e0"] - scheduled_cum
        extra_cum = {s: cum_alloc[s] for s in SECTIONS}
        tax_after_cum = _tax(inp, annual_est, extra_cum)["best_tax"]
        r.update({
            "safe_to_invest": round(safe),
            "safe_if_income_on_plan": round(safe_if_on_plan),
            "binding_month": bind["label"] if bind is not r else r["label"],
            "tax_saving_invest": round(got_total),
            "tax_saving_split": {s: round(alloc["allocation"][s]) for s in SECTIONS},
            "other_investing_capacity": round(max(0.0, safe - got_total)),
            "cash_end_conservative": round(cash_c_end),
            "cash_end_expected": round(cash_e_end),
            "buffer": round(buffer),
            "tax_room_left_after": round(sum(room[s] - cum_alloc[s] for s in SECTIONS)),
            "est_tax_after_plan_to_date": round(tax_after_cum),
            "below_buffer": cash_c_end + 1 < buffer,
        })
        r["why"] = _explain(r, rate, deduction_helps, best_regime_now, buffer, alpha, room_left, target, safe)
        alloc_totals = cum_alloc

    for r in rows:
        r.pop("_cash_c0", None)
        r.pop("_cash_e0", None)

    tax_after = _tax(inp, annual_est, alloc_totals)
    live_rows = [r for r in rows if r["status"] != "past"]
    min_row = min(live_rows, key=lambda x: x["cash_end_conservative"]) if live_rows else None
    below = inp.balance < buffer
    if below:
        warnings.append("Your cash is already below your safety buffer, so nothing is recommended for investing now; later months only once the cautious path is back above the buffer.")
    if not deduction_helps and room_total0 > 0:
        warnings.append("Under the better regime for your income, extra 80C / NPS / 80D investing would not lower your tax, "
                        "so no tax-saving investing is scheduled. Invest for your own goals, not for the deduction.")

    summary = {
        "fy": fy_label(fy), "today": inp.today.isoformat(), "current_month": cur_key, "strategy": inp.strategy,
        "projected_annual_income": round(annual_est), "income_received_ytd": round(ytd_actual),
        "estimated_tax": round(est_tax), "recommended_regime": best_regime_now,
        "advance_tax_total_scheduled": round(sum(inst_due.values())),
        "tax_after_plan": round(tax_after["best_tax"]),
        "tax_saved_by_plan": round(max(0.0, est_tax - tax_after["best_tax"])),
        "tax_saving_invest_total": round(scheduled_tax_invest),
        "tax_room_start": round(room_total0), "tax_room_end": round(sum(room[s] - alloc_totals[s] for s in SECTIONS)),
        "deduction_reduces_tax": bool(deduction_helps),
        "min_cash_conservative": round(min_row["cash_end_conservative"]) if min_row else None,
        "min_cash_month": min_row["label"] if min_row else None,
        "buffer": round(buffer), "starts_below_buffer": bool(below),
        "months_with_zero_safe": sum(1 for r in live_rows if r["safe_to_invest"] <= 0),
        "safe_now": live_rows[0]["safe_to_invest"] if live_rows else 0,
    }
    ytd = _ytd(inp, rows, idx_cur)
    assumptions = [
        {"key": "expected_income", "label": "Expected monthly income", "value": round(exp_inc), "source": flags["expected_income"]},
        {"key": "sigma", "label": "Income volatility (log sd)", "value": round(sigma, 3), "source": flags["sigma"]},
        {"key": "expected_expense", "label": "Expected monthly expenses", "value": round(exp_exp), "source": exp_src},
        {"key": "expense_overrun_pct", "label": "Expense overrun allowance %", "value": inp.expense_overrun_pct, "source": "default"},
        {"key": "buffer_months", "label": "Safety buffer (months of expenses)", "value": inp.buffer_months, "source": "profile"},
        {"key": "alpha", "label": "Confidence cash stays above buffer", "value": alpha, "source": "profile"},
        {"key": "tds_share", "label": "Share of tax deducted at source", "value": tds_share, "source": "you" if inp.tds_share is not None else "default"},
        {"key": "business_expense_pct", "label": "Deductible business expenses % of receipts",
         "value": 50.0 if inp.presumptive_44ada else inp.business_expense_pct, "source": "44ADA" if inp.presumptive_44ada else "you"},
        {"key": "presumptive_44ada", "label": "Presumptive taxation (44ADA)", "value": inp.presumptive_44ada, "source": "you"},
        {"key": "advance_tax_paid", "label": "Advance tax paid so far (excluding TDS)", "value": round(inp.advance_tax_paid), "source": "profile"},
        {"key": "strategy", "label": "Timing of tax-saving investing", "value": inp.strategy, "source": "you"},
        {"key": "income_shock_pct", "label": "What-if change to future income %", "value": inp.income_shock_pct, "source": "you"},
    ]
    return {
        "kind": "monthly", "summary": summary, "months": rows, "ytd": ytd,
        "uncertainty": _uncertainty(exp_inc, sigma, alpha),
        "assumptions": assumptions, "missing_data": missing, "warnings": warnings + inc_notes + exp_notes,
        "limits": ["Not professional tax advice. Decision support only.",
                   "Market returns, capital gains tax on the investments and interest u/s 234A/B/C are not modelled.",
                   "Only the tax situation described by Profile and recorded bank messages is known; other income is not."],
    }


def _uncertainty(mean: float, sigma: float, alpha: float) -> dict:
    nd = NormalDist()
    mu = math.log(mean) - sigma ** 2 / 2 if mean > 0 else 0.0
    q = lambda p: round(math.exp(mu + sigma * nd.inv_cdf(p))) if mean > 0 else 0
    return {"monthly_income_p10": q(0.10), "monthly_income_p50": q(0.50), "monthly_income_p90": q(0.90),
            "conservative_quantile": round(1 - alpha, 2), "sigma": round(sigma, 3)}


def _ytd(inp: PlanInputs, rows: List[dict], idx_cur: int) -> dict:
    past = [r for r in rows if r["status"] == "past"]
    got = [r for r in past if r.get("income_actual") is not None]
    exp_sum = sum(r["income_expected"] for r in got)
    act_sum = sum(r["income_actual"] for r in got)
    cur = next((r for r in rows if r["status"] == "current"), None)
    cur_actual = (cur or {}).get("income_actual") or 0.0
    spent = [r["expenses_actual"] for r in past if r.get("expenses_actual") is not None]
    return {"months_elapsed": idx_cur, "months_with_income_data": len(got),
            "income_actual_past_months": round(act_sum), "income_expected_past_months": round(exp_sum),
            "income_variance_pct": round((act_sum - exp_sum) / exp_sum * 100, 1) if exp_sum else None,
            "income_this_month_so_far": round(cur_actual),
            "expenses_actual_past_months": round(sum(spent)), "months_with_expense_data": len(spent),
            "tax_saving_invested_ytd": round(sum(inp.deductions_used.get(s, 0.0) for s in SECTIONS)),
            "advance_tax_paid": round(inp.advance_tax_paid)}


def _explain(r, rate, helps, regime, buffer, alpha, room_left, target, safe) -> List[str]:
    out = []
    out.append(f"Cautious income {_r(r['income_conservative'])} (there is a {round(alpha*100)}% chance of getting at least this much "
               f"this month), expenses {_r(r['expenses_conservative'])}, bills {_r(r['bills'])}"
               + (f", advance tax {_r(r['advance_tax_due'])}" if r["advance_tax_due"] else "") + ".")
    if r["binding_month"] != r["label"]:
        out.append(f"Safe-to-invest is limited by {r['binding_month']}, the tightest later month, not by this month.")
    out.append(f"Safe to invest {_r(safe)} while keeping your {_r(buffer)} buffer in every later month.")
    if not helps:
        out.append("No tax-saving investing recommended: extra deductions would not reduce your tax under the better regime.")
    elif room_left <= 0:
        out.append("Your tax-saving room is already used up.")
    elif r["tax_saving_invest"] < target - 1:
        out.append(f"Even-pace target was {_r(target)} but only {_r(r['tax_saving_invest'])} fits safely; the rest moves to later months "
                   f"if cash allows. A deduction is never worth leaving you short of cash.")
    else:
        out.append(f"Put {_r(r['tax_saving_invest'])} into tax-saving sections (target {_r(target)}).")
    if r["safe_if_income_on_plan"] > r["safe_to_invest"] + 1:
        out.append(f"If income arrives exactly as expected you could invest up to {_r(r['safe_if_income_on_plan'])}. "
                   f"Wait for the money to land before acting on that.")
    return out


def _r(x) -> str:
    return "Rs " + f"{round(x or 0):,}"
