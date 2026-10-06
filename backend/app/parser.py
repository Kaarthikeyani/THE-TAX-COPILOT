"""Tier-1 grammar parser for Indian bank / UPI / card SMS."""
import re
from datetime import date, datetime
from typing import Optional

AMOUNT = r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d{1,2})?)"
_amt_re = re.compile(AMOUNT, re.I)
_bal_re = re.compile(
    r"(?:avl\.?\s*bal(?:ance)?|available\s*bal(?:ance)?|bal(?:ance)?|clear\s*bal)\s*(?:is|:|-)?\s*"
    r"(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d{1,2})?)", re.I)
_acct_re = re.compile(
    r"(?:a/c|ac|acct|account|card)\s*(?:no\.?)?\s*(?:ending\s*)?[:\-]?\s*[xX*]*\s*(\d{3,6})\b", re.I)
_date_res = [
    (re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4}|\d{2})\b"), "dmy"),
    (re.compile(r"\b(\d{1,2})[-/ ]([A-Za-z]{3})[-/ ,]*(\d{4}|\d{2})\b"), "dMy"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

DEBIT_WORDS = re.compile(r"\b(debited|debit|spent|paid|purchase|withdrawn|sent|txn of|payment of|deducted)\b", re.I)
CREDIT_WORDS = re.compile(r"\b(credited|credit|received|deposited|salary|refund|reversed)\b", re.I)

_merchant_patterns = [
    re.compile(r"(?:to|towards)\s+vpa\s+([\w.\-]+@[\w]+)", re.I),
    re.compile(r"(?:info|desc|narration)\s*[:\-]\s*([A-Za-z0-9 &.\-/*]{3,60}?)(?=\s*[.(]|\s+(?:on\s+\d|(?:ref|bal|avl)\b)|\s*$)", re.I),
    re.compile(r"(?:payment|paid|transfer)\s+(?:to|towards)\s+([A-Za-z0-9 &.\-*]{2,60}?)(?=\s*[.(,]|\s+(?:on\s+\d|(?:ref|bal|avl)\b)|\s*$)", re.I),
    re.compile(r"\bat\s+([A-Za-z0-9 &.\-*]{2,60}?)(?=\s+(?:on\s+\d|(?:using|via|ref|bal|avl)\b)|\s*[.,]|\s*$)", re.I),
    re.compile(r"(?:credited|received)\b.*?\bby\s+([A-Za-z0-9 &.\-/*]{2,60}?)(?=\s*[.(,]|\s+(?:on\s+\d|(?:ref|bal|avl)\b)|\s*$)", re.I),
    re.compile(r"\bfrom\s+(?!your\b|a/c|ac\b|account)([A-Za-z][A-Za-z0-9 &.\-*]{2,60}?)(?=\s*[.(,]|\s+(?:on\s+\d|(?:ref|bal|avl)\b)|\s*$)", re.I),
    re.compile(r"\b(?:to|towards|for)\s+(?!a/c|ac\b|account|your|vpa|rs|inr)([A-Za-z][A-Za-z0-9 &.\-*]{2,60}?)(?=\s*[.(,]|\s+(?:on\s+\d|(?:ref|bal|avl|upi)\b)|\s*$)", re.I),
]


NON_TXN = re.compile(r"\b(otp|one[- ]time password|do not share|declined|failed|unsuccessful|insufficient|will be debited|is due|due on|"
                     r"request(?:ed)? for|e-?mandate|reminder|offer|loan up to|pre-?approved)\b", re.I)


# "reversal of failed txn" / "refund ... failed" are real money coming back, not failed payments
_INFLOW_EXCEPTION = re.compile(r"\b(?:credited|received)\b.*\b(?:reversal|reversed|refund(?:ed)?)\b|\b(?:reversal|refund(?:ed)?)\b.*\b(?:credited|received)\b", re.I)


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _parse_date(text: str) -> Optional[date]:
    for rx, kind in _date_res:
        m = rx.search(text)
        if not m:
            continue
        try:
            d, mo, y = m.group(1), m.group(2), m.group(3)
            day = int(d)
            month = int(mo) if kind == "dmy" else _MONTHS.get(mo.lower())
            if month is None:
                continue
            year = int(y)
            if year < 100:
                year += 2000
            return date(year, month, day)
        except ValueError:
            continue
    return None


_PREFIX = re.compile(r"^(?:upi[-/]\d{6,}[-/]|upi[-/]|neft[-/]|imps[-/](?:\d{6,}[-/])?|rtgs[-/]|(?:upi|imps|neft)\s+from\s+|ecom\s+|pos\s+|pur\s+)+", re.I)


def _clean_merchant(raw: str) -> str:
    raw = raw.strip(" .,-")
    raw = _PREFIX.sub("", raw)  # "UPI/123456789/NAME", "NEFT-NAME", "POS NAME" -> "NAME"
    if "@" in raw:  # UPI handle -> readable name
        raw = raw.split("@")[0]
        raw = re.sub(r"[._\-]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw)
    return raw.upper()[:60]


def parse_sms(text: str) -> dict:
    """Return structured fields + confidence. Never raises."""
    t = " ".join(text.split())
    if NON_TXN.search(t) and not _INFLOW_EXCEPTION.search(t):
        return {"amount": None, "txn_type": None, "merchant": "", "account_suffix": "", "balance": None,
                "txn_date": None, "confidence": 0.0, "skipped": "not a completed transaction"}
    out = {"amount": None, "txn_type": None, "merchant": "", "account_suffix": "",
           "balance": None, "txn_date": None, "confidence": 0.0}

    # strip the balance clause first so it isn't mistaken for the amount
    bal_m = _bal_re.search(t)
    t_no_bal = t
    if bal_m:
        out["balance"] = _num(bal_m.group(1))
        t_no_bal = t[:bal_m.start()] + " " + t[bal_m.end():]

    amt_m = _amt_re.search(t_no_bal)
    if amt_m:
        out["amount"] = _num(amt_m.group(1))

    deb, cred = DEBIT_WORDS.search(t_no_bal), CREDIT_WORDS.search(t_no_bal)
    if deb and cred:
        out["txn_type"] = "debit" if deb.start() < cred.start() else "credit"
        # "a/c credited to MERCHANT" after a debit phrasing -> still a debit for the user
        if re.search(r"debited", t_no_bal, re.I):
            out["txn_type"] = "debit"
    elif deb:
        out["txn_type"] = "debit"
    elif cred:
        out["txn_type"] = "credit"

    acc = _acct_re.search(t_no_bal)
    if acc:
        out["account_suffix"] = acc.group(1)[-4:]

    out["txn_date"] = _parse_date(t_no_bal)

    for rx in _merchant_patterns:
        m = rx.search(t_no_bal)
        if m:
            name = _clean_merchant(m.group(1))
            if len(name) >= 2 and not re.fullmatch(r"[\d\sX*]+", name):
                out["merchant"] = name
                break

    score = 0.0
    score += 0.35 if out["amount"] is not None else 0
    score += 0.25 if out["txn_type"] else 0
    score += 0.20 if out["merchant"] else 0
    score += 0.08 if out["account_suffix"] else 0
    score += 0.07 if out["txn_date"] else 0
    score += 0.05 if out["balance"] is not None else 0
    out["confidence"] = round(min(score, 1.0), 2)
    return out
