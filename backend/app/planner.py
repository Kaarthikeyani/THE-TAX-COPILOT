"""Service layer: SMS ingestion pipeline and the planning views used by the API."""
import hashlib
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import event_stream, live
from .classifier import amount_bucket, normalize_merchant, tier1_classify, CATEGORY_META
from .ml_classifier import ml_classify
from .merchant_memory import MerchantMemory
from .models import IncomeSample, MerchantRule, Profile, Transaction, UpcomingBill
from .multi_period_optimizer import SECTIONS, single_period_allocation, solve_plan, _due_dates
from .parser import parse_sms
from .regime_engine import CAPS, CAPS_SENIOR_80D, compare, fy_label, fy_start_year
from .security import encrypt_text

DEDUCTION_SECTIONS = ["80C", "80CCD1B", "80D", "24b", "80G"]


# ---------------------------------------------------------------- ingestion
INCOME_CATS = {"salary_income", "freelance_income"}  # only these feed the taxable-income model
SAVING_CATS = {"elss_investment", "ppf_epf", "nps", "life_insurance", "health_insurance"}  # money put aside, not spent


class IngestError(ValueError):
    """Raised for messages we deliberately do not store. `code` is stable for API clients."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def sms_digest(text: str) -> str:
    return hashlib.sha256(" ".join((text or "").split()).encode("utf-8")).hexdigest()


def make_dedupe_key(text: str, sender: Optional[str] = None, received_at: Optional[str] = None,
                    source_id: Optional[str] = None, scope: Optional[int] = None) -> str:
    """Idempotency key for forwarded messages. With the forwarder's own message id (best) or its timestamp, two
    genuinely identical texts at different times are kept; without either, identical texts are treated as one."""
    anchor = source_id or received_at or ""
    raw = "v1|" + (f"u{scope}|" if scope is not None else "") + (sender or "").upper() + "|" + anchor + "|" + " ".join((text or "").split())
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _income_sample_adjust(db: Session, month: str, delta: float):
    row = db.query(IncomeSample).filter(IncomeSample.month == month).first()
    if row:
        row.amount = max(0.0, row.amount + delta)
        if row.amount <= 0:
            db.delete(row)
    elif delta > 0:
        db.add(IncomeSample(month=month, amount=delta))


def ingest_sms(db: Session, text: str, dedupe: bool = False, dedupe_key: Optional[str] = None,
               origin: str = "manual", fallback_date: Optional[date] = None) -> dict:
    text = (text or "").strip()
    if not text:
        raise IngestError("empty", "SMS text is empty")
    digest = sms_digest(text)
    if dedupe_key:
        old = db.query(Transaction).filter(Transaction.dedupe_key == dedupe_key).first()
        if old:
            return {**txn_dict(old), "duplicate": True}
    elif dedupe:
        old = db.query(Transaction).filter(Transaction.sms_hash == digest).first()
        if old:
            return {**txn_dict(old), "duplicate": True}
    parsed = parse_sms(text)
    if parsed.get("skipped"):
        raise IngestError("not_a_transaction", "This looks like an OTP, reminder or failed payment, so it was not recorded")
    if parsed["amount"] is None or parsed["txn_type"] is None:
        raise IngestError("unparseable", "Could not read an amount and debit/credit direction from this message")
    txn_date = parsed["txn_date"] or fallback_date or date.today()

    cls = rule_classify(db, parsed["merchant"], parsed["txn_type"]) or tier1_classify(parsed["merchant"], parsed["txn_type"])
    if cls is None:
        ml_text = parsed["merchant"] or text
        cls = ml_classify(ml_text, parsed["txn_type"])

    txn = Transaction(
        txn_date=txn_date, amount=parsed["amount"], txn_type=parsed["txn_type"],
        merchant=parsed["merchant"], account_suffix=parsed["account_suffix"], balance=parsed["balance"],
        category=cls["category"], label=cls["label"], tax_section=cls["tax_section"],
        classification_source=cls["source"], confidence=cls["confidence"],
        parse_confidence=parsed["confidence"], amount_bucket=amount_bucket(parsed["amount"]),
        raw_encrypted=encrypt_text(text), sms_hash=digest, dedupe_key=dedupe_key, origin=origin,
        auto_category=cls["category"], auto_source=cls["source"],
    )
    db.add(txn)

    # salary / business receipts feed the income model (month totals); refunds, gifts, own transfers do not
    if txn.txn_type == "credit" and txn.category in INCOME_CATS:
        _income_sample_adjust(db, txn_date.strftime("%Y-%m"), txn.amount)
    if txn.balance is not None:
        prof = get_profile(db)
        latest = db.query(func.max(Transaction.txn_date)).scalar()
        if latest is None or txn_date >= latest:
            prof.current_balance = txn.balance
    try:
        db.commit()
    except IntegrityError:  # a concurrent request stored the same webhook message first
        db.rollback()
        if dedupe_key:
            old = db.query(Transaction).filter(Transaction.dedupe_key == dedupe_key).first()
            if old:
                return {**txn_dict(old), "duplicate": True}
        raise
    db.refresh(txn)

    uid = db.info.get("user_id")
    event_stream.publish("txn.classified", {
        "txn_type": txn.txn_type, "category": txn.category, "tax_section": txn.tax_section,
        "amount_bucket": txn.amount_bucket, "source": txn.classification_source,
        "confidence": txn.confidence}, uid=uid)
    out = txn_dict(txn)
    if origin != "demo":
        live.notify(uid, {"type": "txn", "origin": origin, "txn": {k: out[k] for k in ("id", "merchant", "amount", "type", "label", "date")}})
    return out


def rule_classify(db: Session, merchant: str, txn_type: str):
    """Highest-priority tier: rules the user created or learned from corrections.
    Exact normalised merchant first, then the closest spelling variant (typos, store numbers, suffixes)."""
    key = normalize_merchant(merchant)
    if not key:
        return None
    r = db.query(MerchantRule).filter(MerchantRule.merchant_key == key, MerchantRule.txn_type == txn_type).first()
    how = "user_rule"
    if r is None:
        rows = db.query(MerchantRule).filter(MerchantRule.txn_type == txn_type).all()
        if not rows:
            return None
        mem = MerchantMemory()
        for x in rows:
            mem.learn(x.merchant_key, txn_type, x.category)
        hit = mem.lookup(key, txn_type)
        if not hit:
            return None
        r = next(x for x in rows if x.merchant_key == hit[1])
        how = "user_rule_similar"
    if r.category not in CATEGORY_META:
        return None
    r.hits = (r.hits or 0) + 1
    label, section, _ = CATEGORY_META[r.category]
    return {"category": r.category, "label": label, "tax_section": section, "source": how, "confidence": 1.0 if how == "user_rule" else 0.9}


def correct_transaction(db: Session, txn_id: int, category: str, apply_to_similar: bool = True) -> dict:
    """Persist a user's category fix, remember it as a rule for this merchant, optionally fix look-alikes."""
    t = db.get(Transaction, txn_id)
    if t is None:
        raise LookupError("Transaction not found")
    if category not in CATEGORY_META:
        raise ValueError(f"Unknown category '{category}'")
    is_income_cat = CATEGORY_META[category][2] == "income"
    if (t.txn_type == "credit") != is_income_cat:
        raise ValueError("A money-in transaction needs an income category and a money-out one needs a spending or investing category")
    changed = [t] + ([x for x in db.query(Transaction).filter(
        Transaction.txn_type == t.txn_type, Transaction.id != t.id, Transaction.user_corrected == False,  # noqa: E712
        Transaction.merchant == t.merchant).all() if x.category != category] if (apply_to_similar and t.merchant) else [])
    label, section, _ = CATEGORY_META[category]
    for x in changed:
        if x.txn_type == "credit":
            month = (x.txn_date or date.today()).strftime("%Y-%m")
            if x.category in INCOME_CATS:
                _income_sample_adjust(db, month, -x.amount)
            if category in INCOME_CATS:
                _income_sample_adjust(db, month, x.amount)
        x.auto_category = x.auto_category or x.category
        x.category, x.label, x.tax_section = category, label, section
        x.classification_source, x.confidence = "user_correction", 1.0
        x.user_corrected = x is t or x.user_corrected
    key = normalize_merchant(t.merchant)
    if key:
        r = db.query(MerchantRule).filter(MerchantRule.merchant_key == key, MerchantRule.txn_type == t.txn_type).first()
        if r:
            r.category = category
        else:
            db.add(MerchantRule(merchant_key=key, txn_type=t.txn_type, category=category))
    db.commit()
    live.notify(db.info.get("user_id"), {"type": "changed", "what": "transaction"})
    return {**txn_dict(t), "updated_similar": len(changed) - 1}


def refresh_learned_examples(db: Session):
    """Kept for callers, deliberately a no-op. The shared ML model is trained only on the shipped examples: one person's
    corrections must never become another person's training data. Personal learning happens through that person's own
    merchant rules (rule_classify), which are private to the account."""
    return None


def confirm_transaction(db: Session, txn_id: int) -> dict:
    """The user says the current category is right. That makes it a verified label for the live accuracy numbers."""
    t = db.get(Transaction, txn_id)
    if t is None:
        raise LookupError("Transaction not found")
    t.confirmed = True
    db.commit()
    live.notify(db.info.get("user_id"), {"type": "changed", "what": "transaction"})
    return txn_dict(t)


def delete_transaction(db: Session, t: Transaction):
    if t.txn_type == "credit" and t.category in INCOME_CATS and t.txn_date:
        _income_sample_adjust(db, t.txn_date.strftime("%Y-%m"), -t.amount)
    db.delete(t)
    db.commit()
    live.notify(db.info.get("user_id"), {"type": "changed", "what": "transaction"})


def txn_dict(t: Transaction) -> dict:
    return {"id": t.id, "date": t.txn_date.isoformat() if t.txn_date else None, "amount": t.amount,
            "type": t.txn_type, "merchant": t.merchant, "account": t.account_suffix, "balance": t.balance,
            "category": t.category, "label": t.label, "tax_section": t.tax_section,
            "source": t.classification_source, "confidence": t.confidence,
            "parse_confidence": t.parse_confidence, "amount_bucket": t.amount_bucket,
            "user_corrected": bool(t.user_corrected), "confirmed": bool(t.confirmed), "auto_category": t.auto_category or "",
            "origin": t.origin or "manual"}


# ---------------------------------------------------------------- profile
def get_profile(db: Session) -> Profile:
    p = db.query(Profile).first()
    if not p:
        p = Profile()
        db.add(p)
        db.commit()
        db.refresh(p)
    return p


def profile_dict(p: Profile) -> dict:
    return {c.name: getattr(p, c.name) for c in Profile.__table__.columns}


# ---------------------------------------------------------------- context
def _fy_bounds(fy: int):
    return date(fy, 4, 1), date(fy + 1, 3, 31)


def build_context(db: Session, today: Optional[date] = None) -> dict:
    today = today or date.today()
    fy = fy_start_year(today)
    start, end = _fy_bounds(fy)
    prof = get_profile(db)

    samples = [s.amount for s in db.query(IncomeSample).order_by(IncomeSample.month).all()]
    recent = samples[-12:]
    if prof.annual_income and prof.annual_income > 0:
        annual, source = float(prof.annual_income), "profile"
    elif recent:
        annual, source = mean(recent) * 12, "income_history"
    else:
        annual, source = 0.0, "none"

    used = {s: 0.0 for s in DEDUCTION_SECTIONS}
    rows = (db.query(Transaction.tax_section, func.sum(Transaction.amount))
            .filter(Transaction.txn_type == "debit", Transaction.txn_date >= start, Transaction.txn_date <= end,
                    Transaction.tax_section.in_(DEDUCTION_SECTIONS))
            .group_by(Transaction.tax_section).all())
    for sec, total in rows:
        used[sec] = float(total or 0)
    used["24b"] = float(prof.home_loan_interest or 0)  # EMI mixes principal; user supplies interest
    used["80G"] = used["80G"] * 0.5  # conservative 50% default

    caps = dict(CAPS)
    if prof.age >= 60:
        caps["80D"] = CAPS_SENIOR_80D
    used_capped = {s: min(used[s], caps[s]) if s in caps else used[s] for s in DEDUCTION_SECTIONS}
    used_capped["other"] = float(prof.other_deductions_old or 0)  # HRA/LTA/employer NPS etc.: old regime only, uncapped here
    headroom = {s: max(0.0, caps[s] - used_capped[s]) for s in caps}

    return {"today": today, "fy": fy, "fy_start": start, "fy_end": end, "profile": prof, "samples": samples,
            "annual_income": annual, "income_source": source, "used": used_capped, "caps": caps,
            "headroom": headroom, "salaried": prof.income_type == "salaried"}


def _best_tax_with(ctx, extra: dict):
    ded = dict(ctx["used"])
    for k, v in extra.items():
        ded[k] = ded.get(k, 0) + v
    return compare(ctx["annual_income"], ded, ctx["profile"].age, ctx["fy"], ctx["salaried"])


def _avg_saving_rate(ctx) -> float:
    full = {s: ctx["headroom"][s] for s in SECTIONS}
    total = sum(full.values())
    if total <= 0 or ctx["annual_income"] <= 0:
        return 0.0
    now = _best_tax_with(ctx, {})["best_tax"]
    best = _best_tax_with(ctx, full)["best_tax"]
    return max(0.0, (now - best) / total)


# ---------------------------------------------------------------- views
def regime_view(db: Session) -> dict:
    ctx = build_context(db)
    res = compare(ctx["annual_income"], ctx["used"], ctx["profile"].age, ctx["fy"], ctx["salaried"])
    res["annual_income"] = round(ctx["annual_income"])
    res["income_source"] = ctx["income_source"]
    res["deductions_used"] = {k: round(v) for k, v in ctx["used"].items()}
    res["old_deductions_total"] = round(res["old"]["deductions_total"] + res["old"]["standard_deduction"])
    return res


def dashboard_view(db: Session) -> dict:
    ctx = build_context(db)
    prof = ctx["profile"]
    income = ctx["annual_income"]
    now = _best_tax_with(ctx, {})
    full = {s: ctx["headroom"][s] for s in SECTIONS}
    potential = _best_tax_with(ctx, full)
    avoidable = max(0.0, now["best_tax"] - potential["best_tax"])
    drag_pct = (avoidable / now["best_tax"] * 100) if now["best_tax"] > 0 else 0.0
    rate = _avg_saving_rate(ctx)

    monthly_exp = float(prof.monthly_expenses or 0)
    buffer = prof.safety_buffer_months * monthly_exp
    upcoming = [q for q in _due_dates(ctx["today"], ctx["fy"])][:1]
    next_due = upcoming[0] if upcoming else None
    reserve = 0.0
    if next_due and now["best_tax"] >= 10000:
        reserve = max(0.0, next_due["cum_pct"] * now["best_tax"] - prof.tax_paid_so_far)
    investable = max(0.0, prof.current_balance - buffer - reserve)
    alloc = single_period_allocation(investable, ctx["headroom"], rate)
    after = _best_tax_with(ctx, alloc["allocation"])
    alloc["tax_saved_if_followed"] = round(max(0.0, now["best_tax"] - after["best_tax"]))

    spend_30 = (db.query(func.sum(Transaction.amount))
                .filter(Transaction.txn_type == "debit",
                        Transaction.txn_date >= ctx["today"] - timedelta(days=30)).scalar() or 0.0)
    inc_30 = (db.query(func.sum(Transaction.amount))
              .filter(Transaction.txn_type == "credit",
                      Transaction.txn_date >= ctx["today"] - timedelta(days=30)).scalar() or 0.0)

    sections = []
    for s in ["80C", "80CCD1B", "80D", "24b"]:
        cap = ctx["caps"][s]
        sections.append({"section": s, "cap": cap, "used": round(ctx["used"][s]),
                         "headroom": round(ctx["headroom"].get(s, 0)),
                         "pct_used": round(ctx["used"][s] / cap * 100, 1) if cap else 0})

    return {
        "fy": fy_label(ctx["fy"]), "as_of": ctx["today"].isoformat(),
        "has_income": income > 0, "annual_income": round(income), "income_source": ctx["income_source"],
        "tax": {"recommended_regime": now["recommended"], "estimated_tax": round(now["best_tax"]),
                "old": round(now["old"]["total_tax"]), "new": round(now["new"]["total_tax"]),
                "effective_rate": now[now["recommended"]]["effective_rate"],
                "paid_so_far": round(prof.tax_paid_so_far),
                "remaining": round(max(0.0, now["best_tax"] - prof.tax_paid_so_far))},
        "tax_drag": {"avoidable_tax": round(avoidable), "drag_pct": round(drag_pct, 1),
                     "efficiency_score": round(max(0.0, 100 - drag_pct)),
                     "best_regime_if_optimised": potential["recommended"]},
        "sections": sections,
        "liquidity": {"balance": round(prof.current_balance), "monthly_expenses": round(monthly_exp),
                      "safety_buffer": round(buffer), "advance_tax_reserve": round(reserve),
                      "next_advance_tax_due": next_due["due"].isoformat() if next_due else None,
                      "investable_now": round(investable),
                      "runway_months": round(prof.current_balance / monthly_exp, 1) if monthly_exp else None},
        "last_30_days": {"spent": round(spend_30), "received": round(inc_30)},
        "allocation": alloc,
        "tip": _tip(now, avoidable, alloc, investable),
    }


def _tip(now, avoidable, alloc, investable):
    if now["new"]["gross"] <= 0:
        return "Add your annual income in Profile (or load the demo data) to see your tax and cash-flow plan."
    if now["best_tax"] <= 0:
        return "Your estimated tax is nil under the better regime - keep your cash flexible."
    if avoidable <= 0:
        return (f"The {now['recommended']} regime is your best option and extra investments would not lower your tax further.")
    if alloc["total"] > 0:
        return (f"You can cut roughly Rs {alloc['tax_saved_if_followed']:,} of tax by investing Rs {alloc['total']:,} "
                f"now while staying above your safety buffer.")
    return (f"Up to Rs {round(avoidable):,} of tax is avoidable, but your cash is needed for the safety buffer "
            f"and advance tax right now.")


def multi_period_view(db: Session) -> dict:
    ctx = build_context(db)
    prof = ctx["profile"]
    if ctx["annual_income"] <= 0:
        return {"feasible": False, "status": "No income data", "periods": [],
                "message": "Add your annual income in Profile or ingest income SMS first."}
    now = _best_tax_with(ctx, {})
    rate = _avg_saving_rate(ctx)
    plan = solve_plan(today=ctx["today"], fy=ctx["fy"], balance=prof.current_balance,
                      monthly_expenses=prof.monthly_expenses, buffer_months=prof.safety_buffer_months,
                      alpha=prof.risk_alpha, income_samples=ctx["samples"][-12:],
                      mean_income_hint=ctx["annual_income"] / 12, tax_now=now["best_tax"],
                      avg_saving_rate=rate, headroom=ctx["headroom"], tax_paid=prof.tax_paid_so_far)
    totals = {s: 0 for s in SECTIONS}
    for p in plan["periods"]:
        for s in SECTIONS:
            totals[s] += p["invest"][s]
    after = _best_tax_with(ctx, totals)
    plan["fy"] = fy_label(ctx["fy"])
    plan["tax_before"] = round(now["best_tax"])
    plan["tax_after"] = round(after["best_tax"])
    plan["tax_saved"] = round(max(0.0, now["best_tax"] - after["best_tax"]))
    plan["totals_by_section"] = totals
    plan["regime_after"] = after["recommended"]
    if rate <= 0:
        plan["message"] = ("Extra deductions will not reduce your tax under the best regime for your income, "
                           "so no tax-saving investments are scheduled.")
    elif not plan["feasible"]:
        plan["message"] = "No plan keeps your cash above the safety buffer. Consider a lower buffer or confidence level."
    else:
        plan["message"] = (f"Follow this plan to save about Rs {plan['tax_saved']:,} of tax while keeping cash above "
                           f"your buffer with {round(plan['alpha']*100)}% confidence.")
    return plan


# ---------------------------------------------------------------- monthly plan (database -> PlanInputs)
OVERRIDE_KEYS = {"expected_income_override", "sigma_override", "expected_expense_override", "expense_overrun_pct",
                 "tds_share", "business_expense_pct", "presumptive_44ada", "strategy", "income_shock_pct",
                 "buffer_months", "alpha", "advance_tax_paid", "balance"}


def _month_of(d: date) -> str:
    return d.strftime("%Y-%m")


def build_monthly_inputs(db: Session, overrides: Optional[dict] = None, today: Optional[date] = None) -> tuple:
    """Gather everything the pure planner needs from the database. Returns (PlanInputs, coverage)."""
    from .monthly_planner import FY_MONTHS, PlanInputs, month_key
    overrides = {k: v for k, v in (overrides or {}).items() if k in OVERRIDE_KEYS and v is not None}
    ctx = build_context(db, today)
    prof, fy = ctx["profile"], ctx["fy"]
    income_history = {r.month: r.amount for r in db.query(IncomeSample).all()}
    start, end = ctx["fy_start"], ctx["fy_end"]
    rows = (db.query(Transaction.txn_date, Transaction.txn_type, Transaction.category, Transaction.amount)
            .filter(Transaction.txn_date >= start - timedelta(days=185), Transaction.txn_date <= end).all())
    spend: dict = {}
    saving: dict = {}
    count: dict = {}
    for d, typ, cat, amt in rows:
        m = _month_of(d)
        count[m] = count.get(m, 0) + 1
        if typ != "debit":
            continue
        if cat in SAVING_CATS:
            if d >= start:
                saving[m] = saving.get(m, 0.0) + amt
        else:
            spend[m] = spend.get(m, 0.0) + amt
    expense_history = {m: v for m, v in spend.items() if count.get(m, 0) >= 3}  # months with enough messages to trust
    bills = []
    for b in db.query(UpcomingBill).order_by(UpcomingBill.month).all():
        if b.repeat_monthly:
            idx0 = next((i for i in range(12) if month_key(fy, i) >= b.month), None)
            for i in range(idx0 if idx0 is not None else 12, 12):
                bills.append((month_key(fy, i), b.name, b.amount))
        elif month_key(fy, 0) <= b.month <= month_key(fy, 11):
            bills.append((b.month, b.name, b.amount))
    inp = PlanInputs(
        today=ctx["today"], fy=fy, balance=float(overrides.pop("balance", prof.current_balance) or 0),
        income_type=prof.income_type, age=prof.age or 30, profile_annual_income=float(prof.annual_income or 0),
        profile_monthly_expenses=float(prof.monthly_expenses or 0), income_history=income_history,
        expense_history=expense_history, saving_actual=saving, deductions_used=dict(ctx["used"]), bills=bills,
        advance_tax_paid=float(overrides.pop("advance_tax_paid", prof.tax_paid_so_far) or 0),
        buffer_months=float(overrides.pop("buffer_months", prof.safety_buffer_months)),
        alpha=float(overrides.pop("alpha", prof.risk_alpha)))
    for k, v in overrides.items():
        setattr(inp, k, v)
    coverage = {"income_months_recorded": len([1 for v in income_history.values() if v]),
                "expense_months_with_data": len(expense_history),
                "transactions_in_fy": sum(1 for d, *_ in rows if d >= start),
                "bills": len(bills)}
    return inp, coverage


def monthly_plan_view(db: Session, overrides: Optional[dict] = None, today: Optional[date] = None) -> dict:
    from .monthly_planner import plan_months
    inp, coverage = build_monthly_inputs(db, overrides, today)
    out = plan_months(inp)
    out["data_coverage"] = coverage
    return out


def monthly_plan_compare(db: Session, overrides: dict, today: Optional[date] = None) -> dict:
    base = monthly_plan_view(db, None, today)
    scen = monthly_plan_view(db, overrides, today)
    b, s = base["summary"], scen["summary"]
    keys = ["estimated_tax", "tax_saving_invest_total", "tax_saved_by_plan", "min_cash_conservative",
            "months_with_zero_safe", "safe_now", "advance_tax_total_scheduled", "projected_annual_income"]
    diff = {k: (s[k] - b[k]) if isinstance(s.get(k), (int, float)) and isinstance(b.get(k), (int, float)) else None for k in keys}
    return {"baseline": base, "scenario": scen, "diff": diff, "changed": sorted(overrides)}
