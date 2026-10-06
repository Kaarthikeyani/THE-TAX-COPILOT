from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
import asyncio, csv, hashlib, json, logging, os, re, secrets, time

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import assistant, auth, demo_mode, event_stream, http_security, live, metrics, planner, seed as seed_mod
from .classifier import CATEGORY_META, normalize_merchant, reload_rules
from .auth import current_user, gate, get_db
from .database import get_raw_db, scoped_session, utcnow, engine, migrate, DB_PATH, BACKUP_DIR
from .explainability import explain
from .ml_classifier import CONFIG_PATH, TRAINING_CSV, get_config, get_model, retrain
from .models import ConsentRecord, IncomeSample, MerchantRule, Transaction, UpcomingBill, User
from .regime_engine import RULES_META, counterfactual
from .security import decrypt_text, key_source

BACKEND_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
log = logging.getLogger("copilot")  # only counts and ids are ever logged - never SMS text, amounts or keys
VERSION = "3.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    info = migrate()
    if info["added_columns"]:
        log.warning("database upgraded: added %s (backup: %s)", ", ".join(info["added_columns"]), info["backup"])
    get_model()  # train the Tier-2 model once at start-up
    demo_mode.ensure_personas()
    yield


app = FastAPI(title="Continuous Tax & Cash-Flow Co-Pilot", version=VERSION, lifespan=lifespan, dependencies=[Depends(gate)])
app.include_router(auth.router)
app.include_router(demo_mode.router)
_origins = [o.strip() for o in os.environ.get("COPILOT_CORS_ORIGINS", "").split(",") if o.strip()]
if _origins:  # default: no cross-origin access at all (the web app is served from the same origin)
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(http_security.SecurityMiddleware)


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    # report which field failed, never echo the submitted value (it may be an SMS)
    errs = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "problem": e["msg"]} for e in exc.errors()]
    return JSONResponse({"error": "invalid_request", "detail": "; ".join(f"{e['field']}: {e['problem']}" for e in errs),
                         "fields": errs}, status_code=422)


# ------------------------------------------------------------------ schemas
class SmsIn(BaseModel):
    text: str = Field(min_length=5, max_length=1000)


class ProfileIn(BaseModel):
    name: Optional[str] = Field(None, max_length=80)
    income_type: Optional[str] = Field(None, pattern="^(salaried|freelancer)$")
    annual_income: Optional[float] = Field(None, ge=0, le=1e9)
    monthly_expenses: Optional[float] = Field(None, ge=0, le=1e8)
    current_balance: Optional[float] = Field(None, ge=-1e8, le=1e10)
    safety_buffer_months: Optional[float] = Field(None, ge=0, le=24)
    age: Optional[int] = Field(None, ge=18, le=110)
    home_loan_interest: Optional[float] = Field(None, ge=0, le=1e8)
    risk_alpha: Optional[float] = Field(None, ge=0.5, le=0.99)
    tax_paid_so_far: Optional[float] = Field(None, ge=0, le=1e9)
    other_deductions_old: Optional[float] = Field(None, ge=0, le=1e8)
    occupation: Optional[str] = Field(None, max_length=80)
    employer: Optional[str] = Field(None, max_length=80)
    monthly_salary: Optional[float] = Field(None, ge=0, le=1e8)
    loan_type: Optional[str] = Field(None, max_length=40)
    loan_emi: Optional[float] = Field(None, ge=0, le=1e8)
    loan_outstanding: Optional[float] = Field(None, ge=0, le=1e10)
    investments_value: Optional[float] = Field(None, ge=0, le=1e10)
    investments_note: Optional[str] = Field(None, max_length=160)
    savings_other: Optional[float] = Field(None, ge=0, le=1e10)


class IncomeIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    amount: float = Field(gt=0, le=1e9)


class WhatIfIn(BaseModel):
    annual_income: float = Field(gt=0, le=1e10)
    age: int = Field(30, ge=18, le=110)
    salaried: bool = True
    d80C: float = Field(0, ge=0, le=1e8)
    d80CCD1B: float = Field(0, ge=0, le=1e8)
    d80D: float = Field(0, ge=0, le=1e8)
    d24b: float = Field(0, ge=0, le=1e8)
    d80G: float = Field(0, ge=0, le=1e8)
    other: float = Field(0, ge=0, le=1e8)


class ConsentIn(BaseModel):
    purpose: str = Field("Continuous tax and cash-flow analysis", max_length=120)
    data_types: str = Field("TRANSACTIONS,BALANCE", max_length=200)
    fi_types: str = Field("DEPOSIT", max_length=120)
    days_valid: int = Field(90, ge=1, le=730)


class CorrectionIn(BaseModel):
    category: str = Field(max_length=60)
    apply_to_similar: bool = True


class RuleIn(BaseModel):
    merchant: str = Field(min_length=2, max_length=80)
    category: str = Field(max_length=60)
    txn_type: str = Field("debit", pattern="^(debit|credit)$")


class ExampleIn(BaseModel):
    text: str = Field(min_length=2, max_length=120)
    category: str = Field(max_length=60)


class BillIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    name: str = Field("", max_length=80)
    amount: float = Field(gt=0, le=1e9)
    repeat_monthly: bool = False


class Assumptions(BaseModel):
    """Every field is optional; anything left out uses your profile or a documented default."""
    expected_income_override: Optional[float] = Field(None, ge=0, le=1e9)
    sigma_override: Optional[float] = Field(None, ge=0, le=2)
    expected_expense_override: Optional[float] = Field(None, ge=0, le=1e8)
    expense_overrun_pct: Optional[float] = Field(None, ge=0, le=100)
    tds_share: Optional[float] = Field(None, ge=0, le=1)
    business_expense_pct: Optional[float] = Field(None, ge=0, le=100)
    presumptive_44ada: Optional[bool] = None
    strategy: Optional[str] = Field(None, pattern="^(even|asap|late)$")
    income_shock_pct: Optional[float] = Field(None, ge=-100, le=500)
    buffer_months: Optional[float] = Field(None, ge=0, le=24)
    alpha: Optional[float] = Field(None, ge=0.5, le=0.99)
    advance_tax_paid: Optional[float] = Field(None, ge=0, le=1e9)
    balance: Optional[float] = Field(None, ge=-1e8, le=1e10)

    def used(self) -> dict:
        return self.model_dump(exclude_none=True)


# ------------------------------------------------------------------ system
@app.get("/health")
def health():
    return {"status": "ok", "version": VERSION, "time": utcnow().isoformat(timespec="seconds") + "Z"}


@app.get("/system")
def system_info(user=Depends(current_user)):
    backups = sorted(BACKUP_DIR.glob("*.db")) if BACKUP_DIR.exists() else []
    return {"version": VERSION, "auth": "phone_otp", "otp_provider": os.environ.get("COPILOT_OTP_PROVIDER", "console"),
            "llm": assistant.llm_status(), "encryption_key_source": key_source(),
            "model": get_config()["name"], "backups": len(backups),
            "latest_backup": backups[-1].name if backups else None,
            "tax_rules": {"last_verified": RULES_META["last_verified"], "caveat": RULES_META["caveat"]}}


# ------------------------------------------------------------------ ingestion
@app.post("/sms/ingest")
def sms_ingest(body: SmsIn, db: Session = Depends(get_db)):
    try:
        return planner.ingest_sms(db, body.text)
    except planner.IngestError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/transactions")
def list_transactions(limit: int = Query(200, ge=1, le=1000), type: Optional[str] = None,
                      section: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Transaction)
    if type in ("debit", "credit"):
        q = q.filter(Transaction.txn_type == type)
    if section:
        q = q.filter(Transaction.tax_section == section)
    rows = q.order_by(Transaction.txn_date.desc(), Transaction.id.desc()).limit(limit).all()
    return [planner.txn_dict(t) for t in rows]


def _txn_or_404(db: Session, txn_id: int) -> Transaction:
    t = db.get(Transaction, txn_id)
    if not t:
        raise HTTPException(404, "Transaction not found")
    return t


@app.get("/transactions/{txn_id}")
def get_transaction(txn_id: int, db: Session = Depends(get_db)):
    return planner.txn_dict(_txn_or_404(db, txn_id))


@app.get("/transactions/{txn_id}/raw")
def transaction_raw(txn_id: int, db: Session = Depends(get_db)):
    t = _txn_or_404(db, txn_id)
    return {"id": t.id, "raw_sms": decrypt_text(t.raw_encrypted),
            "stored_as_ciphertext": t.raw_encrypted[:48] + "..."}


@app.get("/transactions/{txn_id}/explain")
def transaction_explain(txn_id: int, db: Session = Depends(get_db)):
    t = _txn_or_404(db, txn_id)
    return {"transaction": planner.txn_dict(t), "explanation": explain(t.tax_section)}


@app.patch("/transactions/{txn_id}/category")
def correct_category(txn_id: int, body: CorrectionIn, db: Session = Depends(get_db)):
    """Fix a wrong category. The fix is stored, remembered as a rule for this merchant and used to retrain."""
    try:
        return planner.correct_transaction(db, txn_id, body.category, body.apply_to_similar)
    except LookupError:
        raise HTTPException(404, "Transaction not found")
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.delete("/transactions/{txn_id}")
def delete_transaction(txn_id: int, db: Session = Depends(get_db)):
    planner.delete_transaction(db, _txn_or_404(db, txn_id))
    return {"deleted": txn_id}


@app.get("/categories")
def categories():
    return [{"id": k, "label": v[0], "tax_section": v[1], "kind": v[2],
             "direction": "credit" if v[2] == "income" else "debit"} for k, v in CATEGORY_META.items()]


@app.get("/events/recent")
def events_recent(n: int = Query(50, ge=1, le=500), user=Depends(current_user)):
    return event_stream.recent(n, uid=user.id)


# ------------------------------------------------------------------ rules, examples, retraining (no Python edits needed)
@app.get("/rules")
def list_rules(db: Session = Depends(get_db)):
    from .classifier import user_csv_rules
    rows = db.query(MerchantRule).order_by(MerchantRule.id.desc()).all()
    return {"learned_from_you": [{"id": r.id, "merchant": r.merchant_key, "type": r.txn_type, "category": r.category,
                                  "used": r.hits or 0} for r in rows],
            "csv_rules": {c: v for c, v in user_csv_rules().items()},
            "files": {"rules_csv": "backend/data/user_rules.csv", "examples_csv": "backend/data/training_examples.csv",
                      "built_in_taxonomy": "backend/data/merchant_taxonomy.json"}}


@app.post("/rules")
def add_rule(body: RuleIn, db: Session = Depends(get_db)):
    if body.category not in CATEGORY_META:
        raise HTTPException(422, f"Unknown category '{body.category}'")
    if (body.txn_type == "credit") != (CATEGORY_META[body.category][2] == "income"):
        raise HTTPException(422, "Direction and category do not match (money in needs an income category)")
    key = normalize_merchant(body.merchant)
    if not key:
        raise HTTPException(422, "Merchant text has no letters or digits")
    r = db.query(MerchantRule).filter(MerchantRule.merchant_key == key, MerchantRule.txn_type == body.txn_type).first()
    if r:
        r.category = body.category
    else:
        r = MerchantRule(merchant_key=key, txn_type=body.txn_type, category=body.category)
        db.add(r)
    db.commit()
    return {"id": r.id, "merchant": r.merchant_key, "type": r.txn_type, "category": r.category}


@app.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    r = db.get(MerchantRule, rule_id)
    if not r:
        raise HTTPException(404, "Rule not found")
    db.delete(r)
    db.commit()
    return {"deleted": rule_id}


@app.post("/examples")
def add_example(body: ExampleIn, db: Session = Depends(get_db)):
    """Teach the app a merchant. Stored as a private rule on your account only (the shared model never sees it)."""
    if body.category not in CATEGORY_META:
        raise HTTPException(422, f"Unknown category '{body.category}'")
    return add_rule(RuleIn(merchant=body.text, category=body.category,
                           txn_type="credit" if CATEGORY_META[body.category][2] == "income" else "debit"), db)


@app.post("/model/retrain")
def model_retrain():
    """Rebuild the shared model from the shipped examples and the rules file. Never uses anyone's private data."""
    reload_rules()
    return retrain()


# ------------------------------------------------------------------ profile & income
@app.get("/profile")
def get_profile(db: Session = Depends(get_db)):
    return planner.profile_dict(planner.get_profile(db))


@app.put("/profile")
def put_profile(body: ProfileIn, db: Session = Depends(get_db)):
    p = planner.get_profile(db)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return planner.profile_dict(p)


@app.post("/income")
def post_income(body: IncomeIn, db: Session = Depends(get_db)):
    row = db.query(IncomeSample).filter(IncomeSample.month == body.month).first()
    if row:
        row.amount = body.amount
    else:
        row = IncomeSample(month=body.month, amount=body.amount)
        db.add(row)
    db.commit()
    return {"month": row.month, "amount": row.amount}


@app.get("/income")
def get_income(db: Session = Depends(get_db)):
    rows = db.query(IncomeSample).order_by(IncomeSample.month).all()
    return [{"month": r.month, "amount": r.amount} for r in rows]


@app.delete("/income/{month}")
def delete_income(month: str, db: Session = Depends(get_db)):
    db.query(IncomeSample).filter(IncomeSample.month == month).delete()
    db.commit()
    return {"deleted": month}


# ------------------------------------------------------------------ known upcoming bills
@app.get("/bills")
def list_bills(db: Session = Depends(get_db)):
    return [{"id": b.id, "month": b.month, "name": b.name, "amount": b.amount, "repeat_monthly": bool(b.repeat_monthly)}
            for b in db.query(UpcomingBill).order_by(UpcomingBill.month, UpcomingBill.id).all()]


@app.post("/bills")
def add_bill(body: BillIn, db: Session = Depends(get_db)):
    b = UpcomingBill(month=body.month, name=body.name.strip(), amount=body.amount, repeat_monthly=body.repeat_monthly)
    db.add(b)
    db.commit()
    return {"id": b.id, "month": b.month, "name": b.name, "amount": b.amount, "repeat_monthly": b.repeat_monthly}


@app.delete("/bills/{bill_id}")
def delete_bill(bill_id: int, db: Session = Depends(get_db)):
    b = db.get(UpcomingBill, bill_id)
    if not b:
        raise HTTPException(404, "Bill not found")
    db.delete(b)
    db.commit()
    return {"deleted": bill_id}


# ------------------------------------------------------------------ analysis
@app.get("/simulate/regime")
def simulate_regime(db: Session = Depends(get_db)):
    return planner.regime_view(db)


@app.post("/simulate/what_if")
def simulate_what_if(body: WhatIfIn):
    from .regime_engine import compare, fy_start_year
    ded = {"80C": body.d80C, "80CCD1B": body.d80CCD1B, "80D": body.d80D, "24b": body.d24b, "80G": body.d80G, "other": body.other}
    return compare(body.annual_income, ded, body.age, fy_start_year(date.today()), body.salaried)


@app.get("/simulate/counterfactual")
def simulate_counterfactual(amount: Optional[float] = Query(None, ge=0), days_earlier: int = Query(90, ge=0, le=3650),
                            annual_return: float = Query(0.12, ge=0, le=1.0), db: Session = Depends(get_db)):
    if amount is None:
        amount = (db.query(func.max(Transaction.amount))
                  .filter(Transaction.category == "elss_investment").scalar()) or 50000.0
    return counterfactual(amount, days_earlier, annual_return)


@app.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    return planner.dashboard_view(db)


@app.get("/dashboard/multi_period")
def dashboard_multi(db: Session = Depends(get_db)):
    """QUARTERLY advance-tax plan (four statutory dates). Not a monthly recommendation: see /plan/monthly."""
    out = planner.multi_period_view(db)
    out["granularity"] = "quarterly"
    return out


@app.get("/plan/monthly")
def plan_monthly(db: Session = Depends(get_db), expected_income_override: Optional[float] = Query(None, ge=0),
                 expected_expense_override: Optional[float] = Query(None, ge=0),
                 buffer_months: Optional[float] = Query(None, ge=0, le=24), alpha: Optional[float] = Query(None, ge=0.5, le=0.99),
                 strategy: Optional[str] = Query(None, pattern="^(even|asap|late)$"),
                 income_shock_pct: Optional[float] = Query(None, ge=-100, le=500)):
    ov = {k: v for k, v in dict(expected_income_override=expected_income_override, expected_expense_override=expected_expense_override,
                                buffer_months=buffer_months, alpha=alpha, strategy=strategy,
                                income_shock_pct=income_shock_pct).items() if v is not None}
    return planner.monthly_plan_view(db, ov)


@app.post("/plan/monthly/compare")
def plan_monthly_compare(body: Assumptions, db: Session = Depends(get_db)):
    """Recompute the month-by-month plan with changed assumptions and show it next to the saved-settings plan."""
    return planner.monthly_plan_compare(db, body.used())


@app.post("/transactions/{txn_id}/confirm")
def confirm_category(txn_id: int, db: Session = Depends(get_db)):
    """'Looks right': marks this category as verified, which feeds your real-world accuracy numbers."""
    try:
        return planner.confirm_transaction(db, txn_id)
    except LookupError:
        raise HTTPException(404, "Transaction not found")


@app.get("/metrics/live")
def metrics_live(db: Session = Depends(get_db)):
    """Accuracy, precision and recall measured on YOUR real messages that you have reviewed."""
    return metrics.live_metrics(db)


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=400)
    history: list[dict] = Field(default_factory=list, max_length=12)  # earlier turns: [{"role": "user"|"assistant", "text": "..."}]


@app.post("/ask")
def ask(body: AskIn, db: Session = Depends(get_db)):
    """Plain-language answer about your own numbers (local LLM if available; every figure is checked against the facts)."""
    return assistant.ask(db, body.question, body.history)


@app.get("/stream")
async def stream(request: Request, user=Depends(current_user)):
    """Server-Sent Events: a new message from the phone shows up in an open tab within a moment."""
    uid = user.id
    q = live.subscribe(uid)

    async def gen():
        try:
            yield "retry: 3000\n\n"
            yield f"event: hello\ndata: {json.dumps({'user': uid})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"event: {ev.get('type', 'message')}\ndata: {json.dumps(ev)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            live.unsubscribe(uid, q)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


@app.get("/explain/{section}")
def explain_section(section: str):
    return explain(section)


# ------------------------------------------------------------------ consent
def _consent_dict(c: ConsentRecord) -> dict:
    status = c.status
    if status == "ACTIVE" and c.expires_at and c.expires_at < utcnow():
        status = "EXPIRED"
    return {"id": c.id, "consentHandle": c.consent_handle, "status": status,
            "purpose": {"code": "101", "text": c.purpose},
            "dataTypes": c.data_types.split(","), "fiTypes": c.fi_types.split(","),
            "consentStart": c.granted_at.isoformat(timespec="seconds") + "Z",
            "consentExpiry": c.expires_at.isoformat(timespec="seconds") + "Z" if c.expires_at else None,
            "revokedAt": c.revoked_at.isoformat(timespec="seconds") + "Z" if c.revoked_at else None,
            "dataConsumer": {"id": "COPILOT-MINI", "type": "FIU"},
            "note": "Consent-artifact structure only - not a live Account Aggregator integration."}


@app.post("/consent/grant")
def consent_grant(body: ConsentIn, db: Session = Depends(get_db)):
    c = ConsentRecord(consent_handle="CH-" + secrets.token_hex(6).upper(), purpose=body.purpose,
                      data_types=body.data_types, fi_types=body.fi_types,
                      expires_at=utcnow() + timedelta(days=body.days_valid))
    db.add(c)
    db.commit()
    db.refresh(c)
    event_stream.publish("consent.granted", {"fi_types": body.fi_types})
    return _consent_dict(c)


@app.post("/consent/{consent_id}/revoke")
def consent_revoke(consent_id: int, db: Session = Depends(get_db)):
    c = db.get(ConsentRecord, consent_id)
    if not c:
        raise HTTPException(404, "Consent not found")
    if c.status == "REVOKED":
        return _consent_dict(c)
    c.status, c.revoked_at = "REVOKED", utcnow()
    db.commit()
    event_stream.publish("consent.revoked", {"fi_types": c.fi_types})
    return _consent_dict(c)


@app.get("/consent")
def consent_list(db: Session = Depends(get_db)):
    return [_consent_dict(c) for c in db.query(ConsentRecord).order_by(ConsentRecord.id.desc()).all()]


# ------------------------------------------------------------------ real SMS feed (phone -> API)
MAX_BATCH = 200
_SENDER_OK = re.compile(r"^(?:[A-Z]{2}-)?[A-Z][A-Z0-9]{2,9}(?:-[A-Z])?$")


class SmsItem(BaseModel):
    """One forwarded message. Common forwarder field names are accepted as aliases."""
    model_config = ConfigDict(extra="ignore")
    text: str = Field(validation_alias=AliasChoices("text", "body", "message", "sms"), min_length=5, max_length=1000)
    sender: Optional[str] = Field(None, validation_alias=AliasChoices("sender", "from", "address"), max_length=40)
    received_at: Optional[Any] = Field(None, validation_alias=AliasChoices("received_at", "timestamp", "date", "time"))
    id: Optional[Any] = Field(None, validation_alias=AliasChoices("id", "message_id", "uid"))


def _parse_ts(v) -> Optional[datetime]:
    if v in (None, ""):
        return None
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip().isdigit()):
            x = float(v)
            return datetime.fromtimestamp(x / 1000.0 if x > 1e11 else x, timezone.utc).replace(tzinfo=None)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, OverflowError, OSError):
        return None


def _webhook_items(payload) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if isinstance(payload.get("messages"), list):
            return payload["messages"]
        if any(k in payload for k in ("text", "body", "message", "sms")):
            return [payload]
    raise HTTPException(400, detail={"error": "invalid_payload", "detail":
                        'Send JSON like {"messages":[{"text":"...","sender":"AX-HDFCBK","received_at":"2026-10-05T10:15:00Z"}]}'})


@app.post("/sms/webhook")
async def sms_webhook(request: Request, x_api_key: str = Header(default=""), raw: Session = Depends(get_raw_db)):
    """Called by the SMS forwarder on a person's phone. The X-API-Key identifies WHICH account the messages belong to
    (each account has its own key, shown on the Connect phone page). Messages are saved into that account only.

    Returns 200 with one result per message (saved | duplicate | ignored | error) so one bad message never
    rejects the batch. Whole-request problems return 400/401/413/429 with {"error", "detail"}.
    """
    client = request.client.host if request.client else "unknown"
    if http_security.LIMITS.count(f"fail:hook:{client}", http_security.FAIL_LIMIT[1]) >= http_security.FAIL_LIMIT[0]:
        raise HTTPException(429, detail={"error": "locked_out", "detail": "Too many failed attempts. Wait a few minutes."},
                            headers={"Retry-After": "300"})
    owner = None
    if x_api_key and x_api_key.startswith("tcp_"):
        owner = raw.query(User).filter(User.sms_key_hash == hashlib.sha256(x_api_key.encode()).hexdigest()).first()
    if owner is None:
        http_security.LIMITS.hit(f"fail:hook:{client}", 10 ** 6, http_security.FAIL_LIMIT[1])
        raise HTTPException(401, detail={"error": "unauthorized", "detail": "Invalid or missing X-API-Key. Copy it from Connect phone in the app."})
    uid = owner.id
    db = scoped_session(uid)
    try:
        return await _webhook_body(request, db, raw, uid)
    finally:
        db.close()


async def _webhook_body(request: Request, db: Session, acct: Session, uid: int):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, detail={"error": "invalid_json", "detail": "Body must be valid JSON"})
    items = _webhook_items(payload)
    if not items:
        raise HTTPException(400, detail={"error": "empty_batch", "detail": "messages is empty"})
    if len(items) > MAX_BATCH:
        raise HTTPException(413, detail={"error": "too_many_messages", "detail": f"At most {MAX_BATCH} messages per request"})

    results, counts = [], {"saved": 0, "duplicate": 0, "ignored": 0, "error": 0}
    for i, raw in enumerate(items):
        try:
            m = SmsItem.model_validate(raw)
        except ValidationError as e:
            counts["error"] += 1
            results.append({"index": i, "status": "error", "code": "invalid_item",
                            "detail": "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())})
            continue
        sender = (m.sender or "").strip().upper()
        if sender and not _SENDER_OK.match(sender):
            counts["ignored"] += 1
            results.append({"index": i, "status": "ignored", "code": "non_bank_sender", "detail": "Sender is not a bank/alert ID"})
            continue
        ts = _parse_ts(m.received_at)
        dkey = planner.make_dedupe_key(m.text, sender, str(m.id) if m.id not in (None, "") else (ts.strftime("%Y%m%d%H%M") if ts else None), scope=uid)
        try:
            r = planner.ingest_sms(db, m.text, dedupe_key=dkey, origin="webhook", fallback_date=ts.date() if ts else None)
        except planner.IngestError as e:
            counts["ignored"] += 1
            results.append({"index": i, "status": "ignored", "code": e.code, "detail": str(e)})
            continue
        except Exception:  # never leak internals or message text
            db.rollback()
            counts["error"] += 1
            results.append({"index": i, "status": "error", "code": "internal", "detail": "Could not store this message"})
            continue
        if r.get("duplicate"):
            counts["duplicate"] += 1
            results.append({"index": i, "status": "duplicate", "id": r["id"]})
        else:
            counts["saved"] += 1
            results.append({"index": i, "status": "saved", "id": r["id"], "category": r["category"], "type": r["type"]})
    if counts["saved"] or counts["duplicate"]:
        acct.get(User, uid).last_sms_at = utcnow()
        acct.commit()
    log.info("webhook batch: received=%d %s", len(items), counts)
    return {"received": len(items), **counts, "results": results}


# ------------------------------------------------------------------ learning content & accuracy report
@app.get("/glossary")
def glossary():
    return json.loads((BACKEND_DIR / "data" / "glossary.json").read_text(encoding="utf-8"))


@app.get("/experiments")
def experiments():
    """Model comparison produced by experiments/run_experiments.py (synthetic data, labelled as such)."""
    f = BACKEND_DIR / "experiments" / "results" / "summary.json"
    if not f.exists():
        raise HTTPException(404, "Run `python experiments/run_experiments.py` from the backend folder first")
    out = json.loads(f.read_text(encoding="utf-8"))
    for key, name in (("hitl", "hitl.json"), ("planner_backtest", "planner_backtest.json")):
        g = f.parent / name
        if g.exists():
            out[key] = json.loads(g.read_text(encoding="utf-8"))
    return out


# ------------------------------------------------------------------ demo data
@app.post("/demo/load")
def demo_load(db: Session = Depends(get_db)):
    """Loads sample data. Refuses when you have real transactions, so it can never wipe your data."""
    real = db.query(Transaction).filter(Transaction.origin != "demo").count()
    if real:
        raise HTTPException(409, f"You have {real} real transaction(s). Demo data is only loaded into an empty app.")
    seed_mod.clear(db)
    n = seed_mod.seed(db)
    return {"loaded": n}


@app.post("/demo/clear")
def demo_clear(db: Session = Depends(get_db)):
    """Removes only the sample transactions (origin = demo); your own data is untouched."""
    removed = seed_mod.clear(db)
    return {"cleared": True, "removed": removed}


# ------------------------------------------------------------------ frontend (same origin)
APK_PATH = BACKEND_DIR.parent / "android" / "build" / "tax-copilot-sms.apk"


@app.get("/android/tax-copilot-sms.apk")
def phone_app():
    """The SMS-forwarder app for Android, built by android/build.py. It holds no secrets (your key is entered on the phone)."""
    if not APK_PATH.exists():
        raise HTTPException(404, "The phone app has not been built yet. Run `python build.py` in the android folder.")
    return FileResponse(APK_PATH, media_type="application/vnd.android.package-archive", filename="tax-copilot-sms.apk")


class _Revalidate(StaticFiles):
    """Static files are re-checked with the server on every load (cheap 304 when unchanged), so an upgrade never
    leaves a browser running old scripts or styles."""

    def file_response(self, *args, **kwargs):
        r = super().file_response(*args, **kwargs)
        r.headers["Cache-Control"] = "no-cache"
        return r


if FRONTEND_DIR.exists():
    app.mount("/", _Revalidate(directory=str(FRONTEND_DIR), html=True), name="frontend")
