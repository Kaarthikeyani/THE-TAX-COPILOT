"""Load demo data through the real pipeline.  Run:  python -m app.seed   (no arguments needed)."""
from datetime import date, timedelta

from .models import IncomeSample, Transaction, Profile
from .planner import get_profile, ingest_sms

DEMO_PROFILE = dict(name="Demo user", income_type="freelancer", annual_income=0.0, monthly_expenses=35000.0,
                    current_balance=220000.0, safety_buffer_months=3.0, age=30, home_loan_interest=0.0,
                    risk_alpha=0.9, tax_paid_so_far=0.0)

EARLIER_INCOME = [72000, 98000, 64000, 115000, 88000, 79000]  # 6 months before the SMS-fed ones


def _d(today: date, days_ago: int) -> str:
    return (today - timedelta(days=days_ago)).strftime("%d-%m-%y")


def demo_messages(today: date):
    bal = 20000
    msgs = []

    def income(days_ago, amt, who):
        nonlocal bal
        bal += amt
        msgs.append(f"INR {amt:,.2f} credited to A/c XX4821 on {_d(today, days_ago)} by {who}. Avl Bal INR {bal:,.2f}")

    def debit(days_ago, amt, to, kind="upi"):
        nonlocal bal
        bal -= amt
        if kind == "upi":
            msgs.append(f"Rs.{amt:,.2f} debited from A/c XX4821 on {_d(today, days_ago)} to {to} (UPI Ref 4{days_ago:03d}77). Bal Rs {bal:,.2f}")
        else:
            msgs.append(f"Your a/c no. XX4821 is debited for Rs {amt:,.0f} on {_d(today, days_ago)} and a/c credited to {to}. Avl bal Rs {bal:,.2f}")

    income(150, 96000, "UPWORK ESCROW")
    debit(148, 18000, "LANDLORD RAMESH", "upi")
    debit(140, 25000, "AXIS LONG TERM EQUITY FUND", "ne")
    income(120, 128000, "CLIENT PAYMENT INVOICE 1042")
    debit(118, 12000, "LIC OF INDIA", "ne")
    debit(110, 1450, "VPA swiggy@ybl")
    income(92, 74000, "FIVERR WITHDRAWAL")
    debit(90, 20000, "PPF DEPOSIT", "ne")
    debit(75, 2899, "AMAZON", "ne")
    income(62, 112000, "UPWORK ESCROW")
    debit(60, 18000, "STAR HEALTH INSURANCE", "ne")
    debit(52, 10000, "NPS TRUST", "ne")
    debit(45, 4500, "APEX FULL BODY CHECKUP", "ne")
    income(33, 86000, "PAYONEER TRANSFER")
    debit(30, 3200, "BIGBASKET", "ne")
    debit(24, 649, "NETFLIX", "ne")
    debit(18, 999, "AIRTEL", "ne")
    income(8, 104000, "CLIENT PAYMENT INVOICE 1051")
    debit(6, 340, "VPA uber@axisbank")
    debit(3, 2000, "GIVEINDIA DONATION", "ne")
    return msgs


def seed(db, today: date = None) -> int:
    """Load the demo into the signed-in user's account. `db` must be a user-scoped session."""
    today = today or date.today()
    prof = get_profile(db)
    for k, v in DEMO_PROFILE.items():
        setattr(prof, k, v)
    db.commit()
    for i, amt in enumerate(EARLIER_INCOME):
        m = today.replace(day=1) - timedelta(days=30 * (11 - i))
        month = m.strftime("%Y-%m")
        if not db.query(IncomeSample).filter(IncomeSample.month == month).first():
            db.add(IncomeSample(month=month, amount=float(amt)))
    db.commit()
    n = 0
    for text in demo_messages(today):
        try:
            ingest_sms(db, text, origin="demo")
            n += 1
        except ValueError as e:
            print("skipped:", text[:60], "-", e)
    return n


def clear(db) -> int:
    """Delete only demo transactions. Income samples are cleared only when nothing real remains."""
    removed = db.query(Transaction).filter(Transaction.origin == "demo").delete()
    if db.query(Transaction).count() == 0:
        db.query(IncomeSample).delete()
    db.commit()
    return removed


# ---------------------------------------------------------------- personalised fake data (demo onboarding)
def personal_messages(today: date, p) -> list:
    """Fake bank SMS built from what the demo user typed about themselves, oldest first, so the app shows THEIR story."""
    import random
    rnd = random.Random(f"{p.name}|{p.monthly_salary}|{p.loan_emi}")
    salaried = p.income_type == "salaried"
    base = float(p.monthly_salary or 0) or 50000.0
    spend = float(p.monthly_expenses or 0) or base * 0.5
    employer = (p.employer or "").strip().upper()[:24] or "EMPLOYER"
    loan_name = {"home": "HDFC HOME LOAN EMI", "car": "AUTO LOAN EMI", "education": "EDUCATION LOAN EMI"}.get((p.loan_type or "").lower(), "LOAN EMI")
    ev = []  # (days_ago, kind, amount, party)
    for k in range(6):
        d = 150 - 30 * k  # 150, 120, ... 0
        if salaried:
            ev.append((d + 1, "in", base, f"SALARY {employer}"))
        else:
            ev.append((d + 4, "in", round(base * rnd.uniform(0.6, 1.5), -2), f"CLIENT PAYMENT INVOICE {1040 + k}"))
        if p.loan_emi:
            ev.append((d + 3, "ne", float(p.loan_emi), loan_name))
        else:
            ev.append((d + 5, "upi", round(spend * 0.3, -2), "LANDLORD RAMESH"))
        if (p.investments_value or 0) > 0:
            ev.append((d + 2, "ne", round(min(base * 0.1, 25000), -2) or 1000, "AXIS LONG TERM EQUITY FUND"))
        ev.append((d + 7, "ne", round(spend * 0.12, -1), "BIGBASKET"))
        ev.append((d + 9, "upi", round(spend * 0.04, -1), "VPA swiggy@ybl"))
        ev.append((d + 11, "ne", round(spend * 0.06, -1), "AMAZON"))
        ev.append((d + 13, "ne", 649.0, "NETFLIX"))
        ev.append((d + 15, "ne", 999.0, "AIRTEL"))
    ev.append((6, "ne", 18000.0, "STAR HEALTH INSURANCE"))
    ev.append((20, "ne", 20000.0, "PPF DEPOSIT"))
    ev = [e for e in ev if e[0] >= 0 and e[2] > 0]
    ev.sort(key=lambda e: -e[0])
    net = sum(a if k == "in" else -a for _, k, a, _ in ev)
    bal = max(5000.0, float(p.current_balance or 0) - net)
    out = []
    for days, kind, amt, party in ev:
        bal += amt if kind == "in" else -amt
        if kind == "in":
            out.append(f"INR {amt:,.2f} credited to A/c XX4821 on {_d(today, days)} by {party}. Avl Bal INR {bal:,.2f}")
        elif kind == "upi":
            out.append(f"Rs.{amt:,.2f} debited from A/c XX4821 on {_d(today, days)} to {party} (UPI Ref 4{days:03d}77). Bal Rs {bal:,.2f}")
        else:
            out.append(f"Your a/c no. XX4821 is debited for Rs {amt:,.0f} on {_d(today, days)} and a/c credited to {party}. Avl bal Rs {bal:,.2f}")
    return out


def seed_personal(db, today: date = None) -> int:
    """Fill the signed-in user's account with fake messages that match their own profile (profile is left as typed)."""
    today = today or date.today()
    prof = get_profile(db)
    typed_balance = prof.current_balance  # the fake messages must not overwrite what the person said they have
    if prof.income_type != "salaried":
        for i in range(6):
            m = today.replace(day=1) - timedelta(days=30 * (6 - i))
            month = m.strftime("%Y-%m")
            if not db.query(IncomeSample).filter(IncomeSample.month == month).first():
                db.add(IncomeSample(month=month, amount=float(round((prof.monthly_salary or 60000) * (0.7 + 0.15 * (i % 4)), -2))))
        db.commit()
    n = 0
    for text in personal_messages(today, prof):
        try:
            ingest_sms(db, text, origin="demo")
            n += 1
        except ValueError:
            pass
    prof = get_profile(db)
    prof.current_balance = typed_balance
    db.commit()
    return n
