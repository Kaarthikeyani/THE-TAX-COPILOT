"""Properties the month-by-month planner must satisfy, plus adaptation to actual income."""
import random
from datetime import date

import pytest

from app.monthly_planner import PlanInputs, plan_months, _greedy_alloc, SECTIONS
from app.multi_period_optimizer import single_period_allocation

TODAY = date(2026, 10, 5)


def base(**kw):
    d = dict(today=TODAY, fy=2026, balance=900_000, income_type="salaried", age=34, profile_annual_income=2_400_000,
             profile_monthly_expenses=80_000, income_history={f"2026-{m:02d}": 200_000 for m in range(4, 10)},
             expense_history={"2026-07": 78_000, "2026-08": 82_000, "2026-09": 80_000},
             deductions_used={"other": 700_000}, buffer_months=3, alpha=0.9)  # HRA etc. makes old regime win
    d.update(kw)
    return PlanInputs(**d)


def live(r):
    return [m for m in r["months"] if m["status"] != "past"]


def test_twelve_months_past_current_future_labels():
    r = plan_months(base())
    assert [m["status"] for m in r["months"]] == ["past"] * 6 + ["current"] + ["future"] * 5
    assert r["months"][0]["label"] == "Apr 2026" and r["months"][-1]["label"] == "Mar 2027"
    assert r["kind"] == "monthly"


def test_past_months_show_actuals_and_never_recommend():
    r = plan_months(base())
    for m in r["months"][:6]:
        assert m["income_actual"] == 200_000 and "tax_saving_invest" not in m


def test_old_regime_case_recommends_within_room_and_safe():
    r = plan_months(base())
    s = r["summary"]
    assert s["deduction_reduces_tax"] and s["tax_saving_invest_total"] > 0
    assert s["tax_saving_invest_total"] <= s["tax_room_start"]
    for m in live(r):
        assert m["tax_saving_invest"] <= m["safe_to_invest"] + 1
        assert sum(m["tax_saving_split"].values()) == m["tax_saving_invest"]
    assert s["tax_saved_by_plan"] > 0


def test_cash_never_falls_below_buffer_on_conservative_path():
    for seed in range(40):
        rnd = random.Random(seed)
        inc = rnd.choice([60_000, 150_000, 400_000])
        r = plan_months(base(balance=rnd.choice([100_000, 400_000, 1_500_000]),
                             income_type=rnd.choice(["salaried", "freelancer"]),
                             profile_annual_income=inc * 12, profile_monthly_expenses=rnd.choice([30_000, 80_000]),
                             income_history={f"2026-{m:02d}": inc * rnd.uniform(0.5, 1.5) for m in range(4, 10)},
                             deductions_used={"other": rnd.choice([0, 500_000, 900_000])},
                             strategy=rnd.choice(["even", "asap", "late"]), use_milp=False))
        start_ok = not r["summary"]["starts_below_buffer"]
        for m in live(r):
            if start_ok:
                assert m["cash_end_conservative"] + 1 >= m["buffer"] or m["tax_saving_invest"] == 0, (seed, m)
                # investing never *causes* a breach: only plain spending/tax can, and then nothing is recommended
            assert m["tax_saving_invest"] <= m["safe_to_invest"] + 1


def test_below_buffer_means_nothing_now_and_a_warning():
    r = plan_months(base(balance=100_000))
    cur = live(r)[0]
    assert r["summary"]["starts_below_buffer"]
    assert cur["safe_to_invest"] == 0 and cur["tax_saving_invest"] == 0
    assert any("below your safety buffer" in w for w in r["warnings"])
    for m in live(r):  # later months are allowed only once the cautious path is back above the buffer
        assert m["tax_saving_invest"] == 0 or m["cash_end_conservative"] + 1 >= m["buffer"]


def test_no_deduction_chasing_when_new_regime_wins():
    r = plan_months(base(deductions_used={}))
    assert not r["summary"]["deduction_reduces_tax"]
    assert r["summary"]["tax_saving_invest_total"] == 0
    assert any("would not lower your tax" in w for w in r["warnings"])


def test_adapts_when_actual_income_is_lower():
    # tds_share=1 removes advance tax so this isolates the cash effect of lower income arriving
    kw = dict(profile_annual_income=0, income_type="freelancer", tds_share=1.0, balance=500_000)
    good = plan_months(base(income_history={f"2026-{m:02d}": 250_000 for m in range(4, 10)}, **kw))
    bad = plan_months(base(income_history={f"2026-{m:02d}": 120_000 for m in range(4, 10)}, **kw))
    assert bad["summary"]["projected_annual_income"] < good["summary"]["projected_annual_income"]
    assert bad["summary"]["safe_now"] < good["summary"]["safe_now"]
    assert bad["summary"]["estimated_tax"] <= good["summary"]["estimated_tax"]


def test_volatile_income_is_more_cautious_than_steady_income():
    steady = {f"2026-{m:02d}": 150_000 for m in range(4, 10)}
    wild = {f"2026-{m:02d}": v for m, v in zip(range(4, 10), [30_000, 400_000, 60_000, 330_000, 90_000, 290_000])}  # same-ish mean
    kw = dict(income_type="freelancer", profile_annual_income=0, deductions_used={"other": 800_000}, balance=400_000)
    a = plan_months(base(income_history=steady, **kw))
    b = plan_months(base(income_history=wild, **kw))
    assert b["uncertainty"]["sigma"] > a["uncertainty"]["sigma"]
    assert b["summary"]["safe_now"] <= a["summary"]["safe_now"]


def test_upcoming_bill_lowers_safe_amount_in_earlier_months():
    no_bill = plan_months(base(balance=450_000, buffer_months=2))
    bill = plan_months(base(balance=450_000, buffer_months=2, bills=[("2027-01", "School fee", 1_500_000)]))
    jan = next(m for m in bill["months"] if m["month"] == "2027-01")
    assert jan["bills"] == 1_500_000
    assert bill["summary"]["safe_now"] < no_bill["summary"]["safe_now"]
    oct_ = next(m for m in bill["months"] if m["status"] == "current")
    assert oct_["binding_month"] == "Jan 2027"  # explains WHY October is limited


def test_advance_tax_only_in_statutory_months_and_cumulative_share():
    r = plan_months(base(income_type="freelancer", profile_annual_income=0, deductions_used={},
                         income_history={f"2026-{m:02d}": 400_000 for m in range(4, 10)}, advance_tax_paid=0))
    due = {m["label"][:3]: m["advance_tax_due"] for m in r["months"] if m["status"] != "past" and m["advance_tax_due"]}
    assert set(due) <= {"Oct", "Dec", "Mar"}          # Jun and Sep already passed -> catch-up lands in the current month (Oct)
    assert sum(due.values()) == pytest.approx(r["summary"]["advance_tax_total_scheduled"], abs=2)
    # by 15 Dec the cumulative payments must reach 75% of the net liability
    tax = r["summary"]["estimated_tax"]
    assert sum(v for k, v in due.items() if k in ("Oct", "Dec")) == pytest.approx(0.75 * tax, rel=0.01)
    assert sum(due.values()) == pytest.approx(tax, rel=0.01)


def test_presumptive_44ada_has_single_march_instalment_and_lower_tax():
    kw = dict(income_type="freelancer", profile_annual_income=0, deductions_used={},
              income_history={f"2026-{m:02d}": 400_000 for m in range(4, 10)})
    normal = plan_months(base(**kw))
    pres = plan_months(base(presumptive_44ada=True, **kw))
    assert pres["summary"]["estimated_tax"] < normal["summary"]["estimated_tax"]
    months = [m["label"][:3] for m in pres["months"] if m.get("advance_tax_due")]
    assert months == ["Mar"]


def test_senior_salaried_has_no_advance_tax():
    r = plan_months(base(age=65, income_type="salaried", tds_share=0.0, profile_annual_income=3_000_000,
                         income_history={f"2026-{m:02d}": 250_000 for m in range(4, 10)}, deductions_used={}))
    assert r["summary"]["advance_tax_total_scheduled"] == 0
    assert any("seniors" in w.lower() for w in r["warnings"])


def test_missing_data_is_reported_not_invented():
    r = plan_months(base(profile_annual_income=0, profile_monthly_expenses=0, income_history={}, expense_history={}))
    assert "income" in r["missing_data"] and "expenses" in r["missing_data"]
    assert r["summary"]["estimated_tax"] == 0


def test_few_months_of_history_widen_uncertainty_and_warn():
    r = plan_months(base(income_type="freelancer", profile_annual_income=0, income_history={"2026-08": 100_000, "2026-09": 140_000}))
    assert any("Fewer than 3 months" in w for w in r["warnings"])
    assert any("under 6 months" in w for w in r["warnings"])


def test_current_partial_month_is_not_used_to_fit_the_model():
    h = {f"2026-{m:02d}": 200_000 for m in range(4, 10)}
    a = plan_months(base(income_history={**h, "2026-10": 1_000}))   # a few rupees received so far this month
    b = plan_months(base(income_history=h))
    assert a["assumptions"][0]["value"] == b["assumptions"][0]["value"]


def test_strategies_change_timing_not_total_room():
    totals = {}
    for st in ("even", "asap", "late"):
        r = plan_months(base(strategy=st, use_milp=False))
        totals[st] = r["summary"]["tax_saving_invest_total"]
        if st == "asap":
            assert live(r)[0]["tax_saving_invest"] >= live(plan_months(base(strategy="even", use_milp=False)))[0]["tax_saving_invest"]
        if st == "late":
            assert all(m["tax_saving_invest"] == 0 for m in live(r) if m["index"] < 9)
    assert max(totals.values()) <= plan_months(base())["summary"]["tax_room_start"]


def test_greedy_allocation_matches_milp_objective():
    rnd = random.Random(3)
    for _ in range(25):
        head = {"80C": rnd.choice([0, 20_000, 150_000]), "80CCD1B": rnd.choice([0, 50_000]), "80D": rnd.choice([0, 25_000])}
        x = rnd.choice([0, 700, 5_000, 40_000, 300_000])
        g = _greedy_alloc(x, head)["total"]
        m = single_period_allocation(x, head, 0.3)["total"]
        assert g == m, (x, head, g, m)


def test_income_shock_what_if_lowers_future_safe_amounts():
    a = plan_months(base(income_type="freelancer", profile_annual_income=0, deductions_used={"other": 800_000}))
    b = plan_months(base(income_type="freelancer", profile_annual_income=0, deductions_used={"other": 800_000}, income_shock_pct=-40))
    assert b["summary"]["projected_annual_income"] < a["summary"]["projected_annual_income"]
    assert b["summary"]["min_cash_conservative"] <= a["summary"]["min_cash_conservative"]
