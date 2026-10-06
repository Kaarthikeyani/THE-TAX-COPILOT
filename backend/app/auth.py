"""Accounts: sign in with a phone number + one-time code, then a revocable session token.

Flow            POST /auth/otp/request {phone}  ->  a 6-digit code is delivered
                POST /auth/otp/verify  {phone, code} -> {token}; send it as  Authorization: Bearer <token>
Delivery        COPILOT_OTP_PROVIDER = console (default: code is printed in the server window - for local use)
                                     | twilio  (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM or TWILIO_MESSAGING_SERVICE_SID)
                                     | webhook (COPILOT_OTP_WEBHOOK_URL gets {"phone","message"}; works with any SMS gateway)
                COPILOT_DEV_OTP=1 also returns the code in the API response. For local testing ONLY.
Storage         Codes and session tokens are stored only as SHA-256 hashes. A code works once, for 5 minutes,
                5 tries. Tokens last 30 days and can be revoked (logout / delete account).
Each user also has a private key for the phone's SMS forwarder (X-API-Key on /sms/webhook).
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import sys
from datetime import timedelta
from types import SimpleNamespace

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import event_stream, http_security
from .database import adopt_legacy_rows, get_raw_db, scoped_session, utcnow
from .models import AuthSession, OtpChallenge, User, UserScoped
from .security import decrypt_text, encrypt_text

log = logging.getLogger("copilot")
router = APIRouter()

OTP_TTL = timedelta(minutes=5)
OTP_MAX_TRIES = 5
OTP_PER_PHONE = (3, timedelta(minutes=10))  # at most 3 codes per phone per 10 minutes
OTP_COOLDOWN_S = 30
SESSION_TTL = timedelta(days=30)
PUBLIC_PATHS = {"/health", "/auth/mode", "/auth/demo", "/auth/demo/request", "/auth/demo/start", "/auth/otp/request", "/auth/otp/verify", "/sms/webhook", "/android/tax-copilot-sms.apk"}


def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def normalize_phone(raw: str) -> str:
    """-> E.164. A bare 10-digit Indian mobile number gets +91."""
    s = re.sub(r"[\s\-().]", "", raw or "")
    if s.startswith("00"):
        s = "+" + s[2:]
    if s.startswith("+"):
        digits = s[1:]
    elif re.fullmatch(r"[6-9]\d{9}", s):
        digits = "91" + s
    elif re.fullmatch(r"91[6-9]\d{9}", s):
        digits = s
    elif re.fullmatch(r"0[6-9]\d{9}", s):
        digits = "91" + s[1:]
    else:
        raise ValueError("Enter a valid mobile number, for example 98765 43210 or +91 98765 43210")
    if not re.fullmatch(r"[1-9]\d{7,14}", digits):
        raise ValueError("Enter a valid mobile number, for example 98765 43210 or +91 98765 43210")
    return "+" + digits


def mask_phone(p: str) -> str:
    return p[:3] + "•" * max(0, len(p) - 7) + p[-4:]


# ------------------------------------------------------------------ OTP delivery
def _deliver(phone: str, code: str) -> str:
    """Send the code. Returns the provider name. Raises HTTPException(502) when a real gateway fails."""
    provider = os.environ.get("COPILOT_OTP_PROVIDER", "console").lower()
    msg = f"{code} is your Tax & Cash Co-Pilot sign-in code. It expires in 5 minutes. Do not share it."
    if provider == "twilio":
        sid, tok = os.environ.get("TWILIO_ACCOUNT_SID", ""), os.environ.get("TWILIO_AUTH_TOKEN", "")
        data = {"To": phone, "Body": msg}
        if os.environ.get("TWILIO_MESSAGING_SERVICE_SID"):
            data["MessagingServiceSid"] = os.environ["TWILIO_MESSAGING_SERVICE_SID"]
        else:
            data["From"] = os.environ.get("TWILIO_FROM", "")
        try:
            r = httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data=data, auth=(sid, tok), timeout=15)
            r.raise_for_status()
        except Exception:
            log.error("OTP delivery failed (twilio)")  # never log the phone or the code
            raise HTTPException(502, "We couldn't send the code right now. Please try again in a minute.")
    elif provider == "webhook":
        try:
            r = httpx.post(os.environ["COPILOT_OTP_WEBHOOK_URL"], json={"phone": phone, "message": msg}, timeout=15)
            r.raise_for_status()
        except Exception:
            log.error("OTP delivery failed (webhook)")
            raise HTTPException(502, "We couldn't send the code right now. Please try again in a minute.")
    else:
        provider = "console"
        print(f"\n  [sign-in code] {phone}: {code}   (valid 5 minutes)\n", file=sys.stderr, flush=True)
    return provider


# ------------------------------------------------------------------ session resolution (used by every protected route)
def _bearer(request: Request) -> str:
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return ""


def _resolve(request: Request, db: Session) -> SimpleNamespace:
    cached = getattr(request.state, "user", None)
    if cached is not None:
        return cached
    tok = _bearer(request)
    client = request.client.host if request.client else "unknown"
    if tok and http_security.LIMITS.count(f"fail:session:{client}", http_security.FAIL_LIMIT[1]) >= http_security.FAIL_LIMIT[0]:
        raise HTTPException(429, "Too many failed sign-in attempts. Wait a few minutes.", headers={"Retry-After": "300"})
    row = db.query(AuthSession).filter(AuthSession.token_hash == _h(tok)).first() if tok else None
    now = utcnow()
    if row is None or row.expires_at < now:
        if tok:
            http_security.LIMITS.hit(f"fail:session:{client}", 10 ** 6, http_security.FAIL_LIMIT[1])
        raise HTTPException(401, "Sign in required", headers={"WWW-Authenticate": "Bearer"})
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(401, "Sign in required", headers={"WWW-Authenticate": "Bearer"})
    if (now - (row.last_seen_at or now)) > timedelta(hours=1):  # sliding expiry, written at most hourly
        row.last_seen_at, row.expires_at = now, now + SESSION_TTL
        db.commit()
    principal = SimpleNamespace(id=user.id, phone=user.phone)  # plain values: safe to use after the session closes
    request.state.user = principal
    return principal


def current_user(request: Request, raw: Session = Depends(get_raw_db)) -> SimpleNamespace:
    return _resolve(request, raw)


def gate(request: Request, raw: Session = Depends(get_raw_db)) -> None:
    """App-wide dependency: every route needs a signed-in user unless its path is in PUBLIC_PATHS."""
    path = request.url.path
    if os.environ.get("COPILOT_DEMO") == "1" and path in ("/auth/otp/request", "/auth/otp/verify", "/sms/webhook", "/me/connect", "/me/connect/rotate"):
        raise HTTPException(403, "This is a demo with fake data: phone sign-in and SMS forwarding are switched off.")
    if path in PUBLIC_PATHS:
        return
    _resolve(request, raw)


def get_db(user=Depends(current_user)):
    """The session every protected route uses. It can only see and write the signed-in user's rows."""
    s = scoped_session(user.id)
    try:
        yield s
    finally:
        s.close()


# ------------------------------------------------------------------ schemas
class PhoneIn(BaseModel):
    phone: str = Field(min_length=7, max_length=24)


class VerifyIn(PhoneIn):
    code: str = Field(pattern=r"^\d{6}$")
    device: str = Field("", max_length=80)


# ------------------------------------------------------------------ routes
@router.post("/auth/otp/request")
def otp_request(body: PhoneIn, db: Session = Depends(get_raw_db)):
    try:
        phone = normalize_phone(body.phone)
    except ValueError as e:
        raise HTTPException(422, str(e))
    now = utcnow()
    recent = (db.query(OtpChallenge).filter(OtpChallenge.phone == phone, OtpChallenge.created_at > now - OTP_PER_PHONE[1])
              .order_by(OtpChallenge.id.desc()).all())
    if recent and (now - recent[0].created_at).total_seconds() < OTP_COOLDOWN_S:
        wait = OTP_COOLDOWN_S - int((now - recent[0].created_at).total_seconds())
        raise HTTPException(429, f"Please wait {wait} seconds before asking for another code.", headers={"Retry-After": str(wait)})
    if len(recent) >= OTP_PER_PHONE[0]:
        raise HTTPException(429, "Too many codes requested for this number. Try again in a few minutes.", headers={"Retry-After": "600"})
    code = f"{secrets.randbelow(10 ** 6):06d}"
    db.add(OtpChallenge(phone=phone, code_hash=_h(f"{phone}:{code}"), expires_at=now + OTP_TTL))
    db.commit()
    provider = _deliver(phone, code)
    log.info("otp issued via %s", provider)
    out = {"sent": True, "phone": mask_phone(phone), "expires_in": int(OTP_TTL.total_seconds()),
           "resend_after": OTP_COOLDOWN_S, "provider": provider}
    if os.environ.get("COPILOT_DEV_OTP") == "1" and provider == "console":
        out["dev_code"] = code
    return out


@router.post("/auth/otp/verify")
def otp_verify(body: VerifyIn, request: Request, db: Session = Depends(get_raw_db)):
    try:
        phone = normalize_phone(body.phone)
    except ValueError as e:
        raise HTTPException(422, str(e))
    now = utcnow()
    ch = (db.query(OtpChallenge).filter(OtpChallenge.phone == phone, OtpChallenge.used == False,  # noqa: E712
                                        OtpChallenge.expires_at > now).order_by(OtpChallenge.id.desc()).first())
    if ch is None or ch.attempts >= OTP_MAX_TRIES:
        raise HTTPException(400, "That code has expired or was used too many times. Ask for a new one.")
    ch.attempts += 1
    if not secrets.compare_digest(ch.code_hash, _h(f"{phone}:{body.code}")):
        db.commit()
        left = OTP_MAX_TRIES - ch.attempts
        raise HTTPException(400, f"Wrong code. {left} {'try' if left == 1 else 'tries'} left." if left > 0 else "Wrong code. Ask for a new one.")
    ch.used = True
    user = db.query(User).filter(User.phone == phone).first()
    is_new = user is None
    adopted = 0
    if is_new:
        user = User(phone=phone)
        db.add(user)
        db.flush()
        n_users = db.query(User).count()
        db.commit()
        if n_users == 1:  # first account on a database from before accounts: it inherits the existing data
            adopted = adopt_legacy_rows(user.id)
    token = "tcs_" + secrets.token_urlsafe(32)
    user.last_login_at = now
    db.add(AuthSession(user_id=user.id, token_hash=_h(token), expires_at=now + SESSION_TTL,
                       device=(body.device or request.headers.get("user-agent", ""))[:80]))
    db.commit()
    return {"token": token, "is_new": is_new, "adopted_existing_rows": adopted,
            "user": {"id": user.id, "phone": mask_phone(user.phone)}}


@router.post("/auth/logout")
def logout(request: Request, db: Session = Depends(get_raw_db), user=Depends(current_user)):
    db.query(AuthSession).filter(AuthSession.token_hash == _h(_bearer(request))).delete()
    db.commit()
    return {"signed_out": True}


def _new_sms_key() -> str:
    return "tcp_" + secrets.token_urlsafe(24)


def _ensure_key(db: Session, user: User, rotate: bool = False) -> str:
    u = db.get(User, user.id)
    if rotate or not u.sms_key_hash:
        key = _new_sms_key()
        u.sms_key_hash, u.sms_key_enc = _h(key), encrypt_text(key)
        db.commit()
        return key
    return decrypt_text(u.sms_key_enc)


@router.get("/me")
def me(user=Depends(current_user), db: Session = Depends(get_raw_db)):
    u = db.get(User, user.id)
    return {"id": u.id, "phone": mask_phone(u.phone), "member_since": u.created_at.isoformat(timespec="seconds") + "Z",
            "phone_connected": u.last_sms_at is not None,
            "last_sms_at": u.last_sms_at.isoformat(timespec="seconds") + "Z" if u.last_sms_at else None}


@router.get("/me/connect")
def connect_info(request: Request, user=Depends(current_user), db: Session = Depends(get_raw_db)):
    """Everything a phone-side SMS forwarder needs. The key is private to this account."""
    key = _ensure_key(db, user)
    base = os.environ.get("COPILOT_PUBLIC_URL") or f"{request.url.scheme}://{request.headers.get('host', 'localhost:8811')}"
    return {"url": base.rstrip("/") + "/sms/webhook", "key": key, "header": "X-API-Key",
            "local_only": any(h in base for h in ("127.0.0.1", "localhost")),
            "example_body": {"messages": [{"text": "<SMS body>", "sender": "<SMS sender>", "received_at": "<ISO time>"}]}}


@router.post("/me/connect/rotate")
def connect_rotate(user=Depends(current_user), db: Session = Depends(get_raw_db)):
    return {"key": _ensure_key(db, user, rotate=True), "note": "The old key stopped working. Update your phone."}


@router.delete("/me")
def delete_account(user=Depends(current_user), db: Session = Depends(get_raw_db)):
    """Erase the account and every row it owns."""
    s = scoped_session(user.id)
    try:
        for cls in UserScoped.__subclasses__():
            s.query(cls).delete()
        s.commit()
    finally:
        s.close()
    db.query(AuthSession).filter(AuthSession.user_id == user.id).delete()
    db.query(OtpChallenge).filter(OtpChallenge.phone == db.get(User, user.id).phone).delete()
    db.query(User).filter(User.id == user.id).delete()
    db.commit()
    event_stream.purge(user.id)
    return {"deleted": True}
