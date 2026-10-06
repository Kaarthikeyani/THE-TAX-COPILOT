"""Demo mode for showing the app to many people:  COPILOT_DEMO=1

A walk-through of the sign-in and onboarding flow with FAKE everything. Nothing real is needed or collected.
  - "Sign in": type any 3-12 digit number, the code (123456) is shown on screen, new numbers fill in a short profile
    (name, work, salary, loans, investments, savings) and get fake bank messages built from those answers
  - two ready-made people exist at all times: 111 (salaried) and 222 (freelancer)
  - real phone login and the phone SMS webhook are switched off (enforced in auth.gate)
  - each number is its own sandbox; sandboxes are deleted after DEMO_TTL (except 111 and 222) and capped in number
"""
from __future__ import annotations

import os
import re
import secrets
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import event_stream, http_security, seed as seed_mod
from .database import SessionLocal, get_raw_db, scoped_session, utcnow
from .models import AuthSession, OtpChallenge, User, UserScoped
from .auth import SESSION_TTL, _h, mask_phone

router = APIRouter()

DEMO_TTL = timedelta(hours=int(os.environ.get("COPILOT_DEMO_HOURS", "24")))
DEMO_MAX_USERS = int(os.environ.get("COPILOT_DEMO_MAX", "300"))
DEMO_PREFIX = "+000"  # not a dialable number, so it can never collide with a real account
DEMO_CODE = "123456"  # the fake sign-in code, shown on screen: a walk-through of the flow, not real security
PERSONAS = {  # ready-made people, re-created on every start so a restart never leaves the pitch empty
    "111": dict(name="Priya Sharma", occupation="Software engineer", employer="Infosys", income_type="salaried", age=29,
                monthly_salary=95000, monthly_expenses=42000, current_balance=240000, savings_other=300000,
                loan_type="home", loan_emi=28000, loan_outstanding=3200000, home_loan_interest=210000,
                investments_value=450000, investments_note="Index fund SIP, PPF"),
    "222": dict(name="Arjun Mehta", occupation="Freelance designer", employer="Self-employed", income_type="freelancer", age=34,
                monthly_salary=85000, monthly_expenses=38000, current_balance=180000, savings_other=120000,
                loan_type="", loan_emi=0, loan_outstanding=0, investments_value=250000, investments_note="ELSS fund, NPS"),
}


def enabled() -> bool:
    return os.environ.get("COPILOT_DEMO") == "1"


def _require_demo():
    if not enabled():
        raise HTTPException(404, "Demo mode is off on this server.")


def purge_expired(raw: Session) -> int:
    cutoff = utcnow() - DEMO_TTL
    keep = [DEMO_PREFIX + k for k in PERSONAS]
    old = raw.query(User).filter(User.phone.like(DEMO_PREFIX + "%"), User.created_at < cutoff, User.phone.notin_(keep)).all()
    for u in old:
        _erase(raw, u.id, u.phone)
    return len(old)


def _erase(raw: Session, user_id: int, phone: str) -> None:
    s = scoped_session(user_id)
    try:
        for cls in UserScoped.__subclasses__():
            s.query(cls).delete()
        s.commit()
    finally:
        s.close()
    raw.query(AuthSession).filter(AuthSession.user_id == user_id).delete()
    raw.query(OtpChallenge).filter(OtpChallenge.phone == phone).delete()
    raw.query(User).filter(User.id == user_id).delete()
    raw.commit()
    event_stream.purge(user_id)


def _session(raw: Session, user: User) -> str:
    now = utcnow()
    token = "tcs_" + secrets.token_urlsafe(32)
    raw.add(AuthSession(user_id=user.id, token_hash=_h(token), expires_at=now + min(SESSION_TTL, DEMO_TTL), device="demo"))
    user.last_login_at = now
    raw.commit()
    return token


def _admit(raw: Session) -> None:
    """Rate limit and capacity checks before creating a new sandbox."""
    ok, retry = http_security.LIMITS.hit("demo:new", 30, 60.0)  # global: behind a proxy every client shares one IP
    if not ok:
        raise HTTPException(429, "Lots of people are trying the demo right now. Try again in a minute.", headers={"Retry-After": str(retry)})
    purge_expired(raw)
    if raw.query(User).filter(User.phone.like(DEMO_PREFIX + "%")).count() >= DEMO_MAX_USERS:
        raise HTTPException(503, "The demo is full right now. Please try again in a little while.")


def _create(raw: Session, phone: str, profile: dict, sample: bool = True) -> tuple[User, str]:
    user = User(phone=phone, last_login_at=utcnow())
    raw.add(user)
    raw.commit()
    s = scoped_session(user.id)
    try:
        p = seed_mod.get_profile(s)
        for k, v in profile.items():
            setattr(p, k, v)
        s.commit()
        if sample:
            seed_mod.seed_personal(s)
    finally:
        s.close()
    return user, _session(raw, user)


@router.get("/auth/mode")
def auth_mode():
    return {"demo": enabled(), "demo_hours": int(DEMO_TTL.total_seconds() // 3600), "code": DEMO_CODE if enabled() else None}


# ------------------------------------------------------------------ one-tap sandbox with the stock sample data
@router.post("/auth/demo")
def enter_demo(raw: Session = Depends(get_raw_db)):
    _require_demo()
    _admit(raw)
    user = User(phone=f"{DEMO_PREFIX}{secrets.randbelow(10 ** 12):012d}", last_login_at=utcnow())
    raw.add(user)
    raw.commit()
    token = _session(raw, user)
    s = scoped_session(user.id)
    try:
        seed_mod.seed(s)
    finally:
        s.close()
    return {"token": token, "is_new": True, "user": {"id": user.id, "phone": mask_phone(user.phone)}}


# ------------------------------------------------------------------ fake sign-in with onboarding
class DemoProfile(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    occupation: str = Field("", max_length=80)
    employer: str = Field("", max_length=80)
    income_type: str = Field("salaried", pattern="^(salaried|freelancer)$")
    age: int = Field(30, ge=18, le=100)
    monthly_salary: float = Field(0, ge=0, le=1e7)
    monthly_expenses: float = Field(0, ge=0, le=1e7)
    current_balance: float = Field(0, ge=0, le=1e9)
    savings_other: float = Field(0, ge=0, le=1e9)
    loan_type: str = Field("", max_length=40)
    loan_emi: float = Field(0, ge=0, le=1e7)
    loan_outstanding: float = Field(0, ge=0, le=1e9)
    home_loan_interest: float = Field(0, ge=0, le=1e8)
    investments_value: float = Field(0, ge=0, le=1e9)
    investments_note: str = Field("", max_length=160)


class DemoRequest(BaseModel):
    phone: str = Field(min_length=1, max_length=24)


class DemoStart(DemoRequest):
    code: str = Field(min_length=4, max_length=8)
    profile: Optional[DemoProfile] = None


def _digits(raw: str) -> str:
    d = re.sub(r"\D", "", raw or "")
    if not 3 <= len(d) <= 12:
        raise HTTPException(422, "Type any number of 3 to 12 digits, for example 123.")
    return d


def _profile_values(p: DemoProfile) -> dict:
    v = p.model_dump()
    v["annual_income"] = float(round(v["monthly_salary"] * 12)) if v["income_type"] == "salaried" else 0.0
    if not v["monthly_expenses"]:
        v["monthly_expenses"] = float(round(v["monthly_salary"] * 0.5 + v["loan_emi"]))
    return v


@router.post("/auth/demo/request")
def demo_request(body: DemoRequest, raw: Session = Depends(get_raw_db)):
    """Pretend to text a code. Any 3-12 digit number works; the code is shown on screen."""
    _require_demo()
    d = _digits(body.phone)
    exists = raw.query(User).filter(User.phone == DEMO_PREFIX + d).first() is not None
    return {"sent": True, "phone": d, "demo_code": DEMO_CODE, "exists": exists}


@router.post("/auth/demo/start")
def demo_start(body: DemoStart, raw: Session = Depends(get_raw_db)):
    """Fake verify + sign in. Known number -> that sandbox. New number without a profile -> asks for details first."""
    _require_demo()
    d = _digits(body.phone)
    if not secrets.compare_digest(body.code.strip(), DEMO_CODE):
        raise HTTPException(400, f"Wrong code. In this demo the code is {DEMO_CODE}.")
    phone = DEMO_PREFIX + d
    user = raw.query(User).filter(User.phone == phone).first()
    if user:
        return {"token": _session(raw, user), "is_new": False, "user": {"id": user.id, "phone": d}}
    if body.profile is None:
        return {"needs_profile": True}
    _admit(raw)
    user, token = _create(raw, phone, _profile_values(body.profile))
    return {"token": token, "is_new": True, "user": {"id": user.id, "phone": d}}


def ensure_personas() -> None:
    """Create the ready-made demo people (111, 222) if missing. Called at start-up in demo mode."""
    if not enabled():
        return
    with SessionLocal() as raw:
        for d, prof in PERSONAS.items():
            if raw.query(User).filter(User.phone == DEMO_PREFIX + d).first() is None:
                _create(raw, DEMO_PREFIX + d, _profile_values(DemoProfile(**prof)))
