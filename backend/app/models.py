from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Text, Boolean
from .database import Base, utcnow


class UserScoped:
    """Mixin for every table that holds one person's data. The session layer (database.py) filters reads and stamps
    writes with the signed-in user's id, so a query can never return, change or delete another user's rows."""
    user_id = Column(Integer, index=True, nullable=True)  # NULL only for rows created before accounts existed


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"sqlite_autoincrement": True}  # ids are never reused, so a new account can never inherit an old one's id
    id = Column(Integer, primary_key=True)
    phone = Column(String(20), unique=True, nullable=False)  # E.164, e.g. +919876543210
    created_at = Column(DateTime, default=utcnow)
    last_login_at = Column(DateTime, nullable=True)
    sms_key_hash = Column(String(64), index=True, default="")  # sha256 of the phone-forwarder key (lookup)
    sms_key_enc = Column(Text, default="")  # the same key encrypted, so the Connect page can show it again
    last_sms_at = Column(DateTime, nullable=True)  # when the phone last delivered a message


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"
    id = Column(Integer, primary_key=True)
    phone = Column(String(20), index=True, nullable=False)
    code_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, default=0)
    used = Column(Boolean, default=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True, nullable=False)
    token_hash = Column(String(64), unique=True, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime, nullable=False)
    last_seen_at = Column(DateTime, default=utcnow)
    device = Column(String(80), default="")


class Transaction(UserScoped, Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=utcnow)
    txn_date = Column(Date, default=date.today, index=True)
    amount = Column(Float, nullable=False)
    txn_type = Column(String(10), nullable=False)  # debit | credit
    merchant = Column(String(120), default="")
    account_suffix = Column(String(10), default="")
    balance = Column(Float, nullable=True)
    category = Column(String(60), default="uncategorized")
    label = Column(String(80), default="Uncategorised")
    tax_section = Column(String(20), default="none")
    classification_source = Column(String(30), default="none")
    confidence = Column(Float, default=0.0)
    parse_confidence = Column(Float, default=0.0)
    amount_bucket = Column(String(20), default="")
    raw_encrypted = Column(Text, default="")
    sms_hash = Column(String(64), index=True, default="")  # sha256 of the SMS text
    dedupe_key = Column(String(64), nullable=True)  # set only for webhook messages (idempotency); unique index created in migrate()
    origin = Column(String(12), default="manual")  # manual | webhook | demo
    user_corrected = Column(Boolean, default=False)  # True once the user fixed the category
    auto_category = Column(String(60), default="")  # what the model/rules said before the correction
    auto_source = Column(String(30), default="")  # which tier made the original guess (kept after a correction)
    confirmed = Column(Boolean, default=False)  # True once the user said "this category is right" (a verified label)


class Profile(UserScoped, Base):
    __tablename__ = "profile"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), default="")
    income_type = Column(String(20), default="freelancer")  # salaried | freelancer
    annual_income = Column(Float, default=0.0)  # 0 => derive from income samples
    monthly_expenses = Column(Float, default=30000.0)
    current_balance = Column(Float, default=150000.0)
    safety_buffer_months = Column(Float, default=3.0)
    age = Column(Integer, default=30)
    home_loan_interest = Column(Float, default=0.0)
    risk_alpha = Column(Float, default=0.9)  # confidence level for liquidity
    tax_paid_so_far = Column(Float, default=0.0)  # advance tax + TDS paid this FY
    other_deductions_old = Column(Float, default=0.0)  # HRA, LTA, employer NPS etc. (old regime only); user-computed
    occupation = Column(String(80), default="")  # e.g. "Software engineer"
    employer = Column(String(80), default="")
    monthly_salary = Column(Float, default=0.0)  # take-home per month, as told by the user (demo onboarding)
    loan_type = Column(String(40), default="")  # home | car | personal | education | ...
    loan_emi = Column(Float, default=0.0)  # total EMI per month
    loan_outstanding = Column(Float, default=0.0)
    investments_value = Column(Float, default=0.0)  # current value of MFs, stocks, PPF, NPS ...
    investments_note = Column(String(160), default="")
    savings_other = Column(Float, default=0.0)  # FDs, RDs, cash beyond the bank balance


class IncomeSample(UserScoped, Base):
    __tablename__ = "income_samples"
    id = Column(Integer, primary_key=True)
    month = Column(String(7), index=True)  # YYYY-MM
    amount = Column(Float, nullable=False)


class ConsentRecord(UserScoped, Base):
    __tablename__ = "consents"
    id = Column(Integer, primary_key=True)
    consent_handle = Column(String(40), unique=True)
    purpose = Column(String(120), default="")
    data_types = Column(String(200), default="")
    fi_types = Column(String(120), default="DEPOSIT")
    granted_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    status = Column(String(12), default="ACTIVE")  # ACTIVE | REVOKED | EXPIRED


class MerchantRule(UserScoped, Base):
    """A rule the user created (directly or by correcting a transaction). Highest priority in classification."""
    __tablename__ = "merchant_rules"
    id = Column(Integer, primary_key=True)
    merchant_key = Column(String(120), index=True, nullable=False)  # normalised merchant text
    txn_type = Column(String(10), default="debit")  # debit | credit
    category = Column(String(60), nullable=False)
    created_at = Column(DateTime, default=utcnow)
    hits = Column(Integer, default=0)
    # uniqueness per user (user_id, merchant_key, txn_type) is enforced in code and by an index made in migrate()


class UpcomingBill(UserScoped, Base):
    """A known future outflow (insurance premium, school fee, rent increase, EMI...) used by the monthly planner."""
    __tablename__ = "upcoming_bills"
    id = Column(Integer, primary_key=True)
    month = Column(String(7), index=True, nullable=False)  # YYYY-MM
    name = Column(String(80), default="")
    amount = Column(Float, nullable=False)
    repeat_monthly = Column(Boolean, default=False)  # applies from `month` to the end of the FY
