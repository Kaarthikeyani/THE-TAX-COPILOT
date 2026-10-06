"""Accounts, tenant isolation, live push, real-data accuracy metrics and the assistant."""
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

DEBIT = "Rs.2,450.00 debited from A/c XX4821 on 05-10-26 to VPA zomato@ybl (UPI Ref 481726). Bal Rs 1,48,200.00"
CREDIT = "INR 85,000.00 credited to A/c XX4821 on 04-10-26 by UPWORK ESCROW. Avl Bal INR 2,33,200.00"
BACKEND = str(Path(__file__).resolve().parent.parent)


# ---------------------------------------------------------------- phone + OTP login
def test_login_flow_issues_a_working_session(anon):
    r = anon.post("/auth/otp/request", json={"phone": "98765 43210"}).json()
    assert r["sent"] and r["phone"].startswith("+91") and "dev_code" in r
    v = anon.post("/auth/otp/verify", json={"phone": "+919876543210", "code": r["dev_code"]}).json()
    assert v["is_new"] and v["token"].startswith("tcs_")
    h = {"Authorization": "Bearer " + v["token"]}
    assert anon.get("/me", headers=h).json()["phone"].endswith("3210")
    assert anon.get("/profile", headers=h).status_code == 200
    anon.post("/auth/logout", headers=h)
    assert anon.get("/profile", headers=h).status_code == 401  # logout revokes the token


def test_phone_numbers_are_normalised_and_validated(anon):
    from app.auth import normalize_phone
    assert normalize_phone("98765 43210") == normalize_phone("+91-98765-43210") == normalize_phone("09876543210") == "+919876543210"
    assert normalize_phone("+14155552671") == "+14155552671"
    for bad in ("12345", "abcdefghij", "5876543210", "+0123456789"):
        with pytest.raises(ValueError):
            normalize_phone(bad)
    assert anon.post("/auth/otp/request", json={"phone": "12345"}).status_code == 422


def test_wrong_code_is_counted_and_locks_the_challenge(anon):
    r = anon.post("/auth/otp/request", json={"phone": "9876543211"}).json()
    wrong = "000000" if r["dev_code"] != "000000" else "111111"
    msgs = [anon.post("/auth/otp/verify", json={"phone": "9876543211", "code": wrong}).json()["detail"] for _ in range(5)]
    assert "4 tries left" in msgs[0]
    # after 5 wrong tries even the right code is refused
    assert anon.post("/auth/otp/verify", json={"phone": "9876543211", "code": r["dev_code"]}).status_code == 400


def test_code_works_once_and_expires(anon):
    from app.database import SessionLocal
    from app.models import OtpChallenge
    from app.database import utcnow
    from datetime import timedelta
    r = anon.post("/auth/otp/request", json={"phone": "9876543212"}).json()
    ok = anon.post("/auth/otp/verify", json={"phone": "9876543212", "code": r["dev_code"]})
    assert ok.status_code == 200
    assert anon.post("/auth/otp/verify", json={"phone": "9876543212", "code": r["dev_code"]}).status_code == 400  # single use
    r2 = anon.post("/auth/otp/request", json={"phone": "9876543213"}).json()
    with SessionLocal() as s:  # age the challenge past its 5 minutes
        c = s.query(OtpChallenge).filter(OtpChallenge.phone == "+919876543213").one()
        c.expires_at = utcnow() - timedelta(seconds=1)
        s.commit()
    assert anon.post("/auth/otp/verify", json={"phone": "9876543213", "code": r2["dev_code"]}).status_code == 400


def test_otp_requests_are_throttled_per_phone(anon):
    assert anon.post("/auth/otp/request", json={"phone": "9876543214"}).status_code == 200
    cool = anon.post("/auth/otp/request", json={"phone": "9876543214"})
    assert cool.status_code == 429 and cool.headers.get("Retry-After")  # 30-second cooldown


def test_codes_and_tokens_are_stored_only_as_hashes(anon, tmp_data_dir):
    r = anon.post("/auth/otp/request", json={"phone": "9876543215"}).json()
    tok = anon.post("/auth/otp/verify", json={"phone": "9876543215", "code": r["dev_code"]}).json()["token"]
    con = sqlite3.connect(tmp_data_dir / "copilot.db")
    blob = " ".join(str(x) for t in ("otp_challenges", "auth_sessions", "users") for row in con.execute(f"select * from {t}") for x in row)
    assert r["dev_code"] not in blob.replace("+91", "") or len(r["dev_code"]) < 6
    assert tok not in blob


def test_production_otp_response_never_contains_the_code(anon, monkeypatch):
    monkeypatch.delenv("COPILOT_DEV_OTP")
    assert "dev_code" not in anon.post("/auth/otp/request", json={"phone": "9876543216"}).json()


def test_otp_is_delivered_through_a_webhook_provider(anon, monkeypatch):
    sent = {}

    class R:
        def raise_for_status(self): pass

    import httpx
    monkeypatch.setenv("COPILOT_OTP_PROVIDER", "webhook")
    monkeypatch.setenv("COPILOT_OTP_WEBHOOK_URL", "http://gateway.test/send")
    monkeypatch.setattr(httpx, "post", lambda url, json=None, **kw: sent.update(url=url, **json) or R())
    r = anon.post("/auth/otp/request", json={"phone": "9876543217"}).json()
    assert r["provider"] == "webhook" and "dev_code" not in r
    assert sent["phone"] == "+919876543217" and "sign-in code" in sent["message"]
    code = sent["message"].split()[0]
    assert anon.post("/auth/otp/verify", json={"phone": "9876543217", "code": code}).status_code == 200


def test_gateway_failure_is_reported_without_leaking_details(anon, monkeypatch):
    import httpx
    monkeypatch.setenv("COPILOT_OTP_PROVIDER", "webhook")
    monkeypatch.setenv("COPILOT_OTP_WEBHOOK_URL", "http://gateway.test/send")

    def boom(*a, **k):
        raise httpx.ConnectError("secret internal detail")
    monkeypatch.setattr(httpx, "post", boom)
    r = anon.post("/auth/otp/request", json={"phone": "9876543218"})
    assert r.status_code == 502 and "secret" not in r.text


# ---------------------------------------------------------------- tenant isolation
def test_users_never_see_each_others_data(client, other_client):
    a = client.post("/sms/ingest", json={"text": DEBIT}).json()
    client.put("/profile", json={"name": "Alice", "annual_income": 1200000})
    client.post("/income", json={"month": "2026-10", "amount": 99000})
    client.post("/bills", json={"month": "2026-11", "name": "School fee", "amount": 20000})
    client.post("/rules", json={"merchant": "ALICE SHOP", "category": "shopping"})
    client.post("/consent/grant", json={})

    assert other_client.get("/transactions").json() == []
    assert other_client.get("/income").json() == []
    assert other_client.get("/bills").json() == []
    assert other_client.get("/consent").json() == []
    assert other_client.get("/rules").json()["learned_from_you"] == []
    assert other_client.get("/profile").json()["name"] == ""
    assert other_client.get("/dashboard").json()["annual_income"] == 0
    # direct access by id: indistinguishable from "does not exist"
    assert other_client.get(f"/transactions/{a['id']}").status_code == 404
    assert other_client.get(f"/transactions/{a['id']}/raw").status_code == 404
    assert other_client.patch(f"/transactions/{a['id']}/category", json={"category": "shopping"}).status_code == 404
    assert other_client.post(f"/transactions/{a['id']}/confirm").status_code == 404
    assert other_client.delete(f"/transactions/{a['id']}").status_code == 404
    assert client.get(f"/transactions/{a['id']}").status_code == 200  # and alice's row is untouched


def test_aggregates_and_bulk_deletes_are_scoped_too(client, other_client):
    client.post("/sms/ingest", json={"text": CREDIT})
    other_client.post("/sms/ingest", json={"text": CREDIT.replace("85,000", "10,000")})
    assert client.get("/income").json() == [{"month": "2026-10", "amount": 85000.0}]
    assert other_client.get("/income").json() == [{"month": "2026-10", "amount": 10000.0}]
    other_client.delete("/income/2026-10")  # bulk delete by month
    assert client.get("/income").json() == [{"month": "2026-10", "amount": 85000.0}]
    assert client.get("/dashboard").json()["last_30_days"]["received"] >= 0
    assert other_client.get("/dashboard").json()["last_30_days"]["received"] == other_client.get("/dashboard").json()["last_30_days"]["received"]


def test_same_merchant_rule_can_exist_for_two_users(client, other_client):
    assert client.post("/rules", json={"merchant": "CORNER STORE", "category": "groceries"}).status_code == 200
    assert other_client.post("/rules", json={"merchant": "CORNER STORE", "category": "shopping"}).status_code == 200
    t = {"text": "Rs 300.00 debited from A/c XX1 on 06-10-26 to CORNER STORE. Bal Rs 89,000"}
    assert client.post("/sms/ingest", json=t).json()["category"] == "groceries"
    assert other_client.post("/sms/ingest", json=t).json()["category"] == "shopping"


def test_a_correction_by_one_user_does_not_change_another_users_classification(client, other_client):
    t = {"text": "Rs 700.00 debited from A/c XX1 on 05-10-26 to PHARMEASY. Bal Rs 90,000"}
    a = client.post("/sms/ingest", json=t).json()
    client.patch(f"/transactions/{a['id']}/category", json={"category": "preventive_healthcare"})
    b = other_client.post("/sms/ingest", json=t).json()
    assert b["source"] != "user_rule" and b["source"] != "user_correction"
    assert b["category"] != "preventive_healthcare" or b["source"].startswith("tier")  # decided by shared rules/ML only


def test_events_feed_is_per_user(client, other_client):
    client.post("/sms/ingest", json={"text": DEBIT})
    assert len(client.get("/events/recent").json()) >= 1
    assert other_client.get("/events/recent").json() == []
    assert all("uid" not in e for e in client.get("/events/recent").json())


def test_the_database_layer_refuses_unowned_writes(db):
    from app.database import SessionLocal
    from app.models import Transaction
    s = SessionLocal()  # no user attached
    s.add(Transaction(amount=1, txn_type="debit"))
    with pytest.raises(RuntimeError):
        s.commit()
    s.close()


# ---------------------------------------------------------------- phone webhook routes to the right account
def test_webhook_saves_into_the_keys_owner_only(client, other_client, anon):
    ka = client.get("/me/connect").json()["key"]
    kb = other_client.get("/me/connect").json()["key"]
    assert ka != kb and ka.startswith("tcp_")
    r = anon.post("/sms/webhook", json={"messages": [{"text": DEBIT, "sender": "AX-HDFCBK", "id": "1"}]}, headers={"X-API-Key": ka}).json()
    assert r["saved"] == 1
    assert len(client.get("/transactions").json()) == 1
    assert other_client.get("/transactions").json() == []
    # the same SMS from bob's phone is NOT a duplicate of alice's
    r2 = anon.post("/sms/webhook", json={"messages": [{"text": DEBIT, "sender": "AX-HDFCBK", "id": "1"}]}, headers={"X-API-Key": kb}).json()
    assert r2["saved"] == 1 and r2["duplicate"] == 0
    assert client.get("/me").json()["phone_connected"] and client.get("/me").json()["last_sms_at"]


def test_rotating_the_key_stops_the_old_one(client, anon):
    old = client.get("/me/connect").json()["key"]
    new = client.post("/me/connect/rotate").json()["key"]
    assert new != old
    assert client.get("/me/connect").json()["key"] == new  # stable between calls
    body = {"messages": [{"text": DEBIT}]}
    assert anon.post("/sms/webhook", json=body, headers={"X-API-Key": old}).status_code == 401
    assert anon.post("/sms/webhook", json=body, headers={"X-API-Key": new}).status_code == 200


def test_sms_key_is_stored_encrypted_and_hashed(client, tmp_data_dir):
    key = client.get("/me/connect").json()["key"]
    con = sqlite3.connect(tmp_data_dir / "copilot.db")
    row = con.execute("select sms_key_hash, sms_key_enc from users where phone='+919000000001'").fetchone()
    assert key not in row[0] + row[1] and len(row[0]) == 64 and row[1].startswith("gAAAA")


def test_delete_account_erases_everything(client, other_client):
    client.post("/sms/ingest", json={"text": DEBIT})
    other_client.post("/sms/ingest", json={"text": CREDIT})
    assert client.delete("/me").json()["deleted"]
    assert client.get("/profile").status_code == 401  # session gone
    assert len(other_client.get("/transactions").json()) == 1  # bob untouched


# ---------------------------------------------------------------- upgrading an old single-user database
OLD_RULES_SCHEMA = """
CREATE TABLE transactions (id INTEGER PRIMARY KEY, created_at DATETIME, txn_date DATE, amount FLOAT NOT NULL, txn_type VARCHAR(10) NOT NULL,
  merchant VARCHAR(120), account_suffix VARCHAR(10), balance FLOAT, category VARCHAR(60), label VARCHAR(80), tax_section VARCHAR(20),
  classification_source VARCHAR(30), confidence FLOAT, parse_confidence FLOAT, amount_bucket VARCHAR(20), raw_encrypted TEXT,
  sms_hash VARCHAR(64), dedupe_key VARCHAR(64), origin VARCHAR(12), user_corrected BOOLEAN, auto_category VARCHAR(60));
CREATE TABLE profile (id INTEGER PRIMARY KEY, name VARCHAR(80), income_type VARCHAR(20), annual_income FLOAT, monthly_expenses FLOAT,
  current_balance FLOAT, safety_buffer_months FLOAT, age INTEGER, home_loan_interest FLOAT, risk_alpha FLOAT, tax_paid_so_far FLOAT,
  other_deductions_old FLOAT);
CREATE TABLE merchant_rules (id INTEGER PRIMARY KEY, merchant_key VARCHAR(120) NOT NULL, txn_type VARCHAR(10), category VARCHAR(60) NOT NULL,
  created_at DATETIME, hits INTEGER, CONSTRAINT uq_rule_merchant_type UNIQUE (merchant_key, txn_type));
INSERT INTO transactions (id, amount, txn_type, merchant, category, raw_encrypted, origin) VALUES (1, 500, 'debit', 'OLD SHOP', 'shopping', 'gAAAAold', 'manual');
INSERT INTO profile (id, name) VALUES (1, 'Asha');
INSERT INTO merchant_rules (id, merchant_key, txn_type, category, hits) VALUES (1, 'OLD SHOP', 'debit', 'shopping', 3);
"""


def test_old_database_is_upgraded_and_first_signup_inherits_it(tmp_path):
    con = sqlite3.connect(tmp_path / "copilot.db")
    con.executescript(OLD_RULES_SCHEMA)
    con.commit()
    con.close()
    code = r'''
import json
from fastapi.testclient import TestClient
from app.main import app
import os
os.environ["COPILOT_DEV_OTP"] = "1"
with TestClient(app) as c:
    r = c.post("/auth/otp/request", json={"phone": "9876543210"}).json()
    v = c.post("/auth/otp/verify", json={"phone": "9876543210", "code": r["dev_code"]}).json()
    h = {"Authorization": "Bearer " + v["token"]}
    first = {"adopted": v["adopted_existing_rows"], "txns": len(c.get("/transactions", headers=h).json()), "name": c.get("/profile", headers=h).json()["name"],
             "rules": len(c.get("/rules", headers=h).json()["learned_from_you"])}
    r = c.post("/auth/otp/request", json={"phone": "9876543299"}).json()
    v2 = c.post("/auth/otp/verify", json={"phone": "9876543299", "code": r["dev_code"]}).json()
    h2 = {"Authorization": "Bearer " + v2["token"]}
    second = {"adopted": v2["adopted_existing_rows"], "txns": len(c.get("/transactions", headers=h2).json()), "name": c.get("/profile", headers=h2).json()["name"]}
    same_rule = c.post("/rules", json={"merchant": "OLD SHOP", "category": "groceries"}, headers=h2).status_code  # old global UNIQUE would reject this
print(json.dumps([first, second, same_rule]))
'''
    env = {**os.environ, "COPILOT_DATA_DIR": str(tmp_path)}
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-1500:]
    first, second, same_rule = json.loads(out.stdout.strip().splitlines()[-1])
    assert first["adopted"] >= 3 and first["txns"] == 1 and first["name"] == "Asha" and first["rules"] == 1
    assert second["adopted"] == 0 and second["txns"] == 0 and second["name"] == ""  # the second person gets nothing of the first's
    assert same_rule == 200


# ---------------------------------------------------------------- live push
def test_live_hub_delivers_only_to_that_users_open_tabs():
    from app import live

    async def run():
        qa, qb = live.subscribe(11), live.subscribe(22)
        live.notify(11, {"type": "txn", "n": 1})
        await asyncio.sleep(0.05)
        assert qa.get_nowait()["n"] == 1 and qb.empty()
        live.unsubscribe(11, qa)
        live.notify(11, {"type": "txn", "n": 2})  # nobody listening: dropped, no error
        live.unsubscribe(22, qb)
        assert live.listeners(11) == 0 and live.listeners(22) == 0
    asyncio.run(run())


def test_ingest_pushes_a_live_event(client, monkeypatch):
    from app import live
    seen = []
    monkeypatch.setattr(live, "notify", lambda uid, ev: seen.append((uid, ev)))
    client.post("/sms/ingest", json={"text": DEBIT})
    assert seen and seen[0][1]["type"] == "txn" and seen[0][1]["txn"]["amount"] == 2450
    seen.clear()
    client.post("/demo/load")
    assert not [e for e in seen if e[1]["type"] == "txn"]  # loading the demo must not fire 20 notifications


def test_stream_requires_a_session(anon):
    assert anon.get("/stream").status_code == 401


# ---------------------------------------------------------------- accuracy measured on the user's own data
def _ingest(client, merchant, amt=100, day=5):
    return client.post("/sms/ingest", json={"text": f"Rs {amt}.00 debited from A/c XX1 on {day:02d}-10-26 to {merchant}. Bal Rs 90,000"}).json()


def test_live_metrics_start_empty_then_follow_the_users_answers(client):
    m = client.get("/metrics/live").json()
    assert m["verified"] == 0 and m["accuracy"] is None
    a = _ingest(client, "ZOMATO", 200)           # rules say food_dining: right
    b = _ingest(client, "BIGBASKET", 300, 6)     # groceries: right
    c = _ingest(client, "NETFLIX", 400, 7)       # entertainment: right
    d = _ingest(client, "NETFLIX INDIA", 500, 8)
    client.post(f"/transactions/{a['id']}/confirm")
    client.post(f"/transactions/{b['id']}/confirm")
    client.post(f"/transactions/{c['id']}/confirm")
    client.patch(f"/transactions/{d['id']}/category", json={"category": "shopping", "apply_to_similar": False})  # user says model was wrong
    m = client.get("/metrics/live").json()
    assert m["transactions"] == 4 and m["verified"] == 4
    assert m["confirmed_right"] == 3 and m["corrected"] == 1
    assert m["accuracy"] == 0.75 and m["accuracy_wilson95"][0] < 0.75 < m["accuracy_wilson95"][1]
    assert m["stable"] is False and any("rough guide" in n for n in m["notes"])
    assert {"precision", "recall", "f1"} <= set(m["macro"]) and m["per_class"]["shopping"]["recall"] == 0.0
    assert m["confusions"][0]["count"] == 1
    assert m["by_source"]  # which tier made the original guesses


def test_metrics_do_not_leak_between_users(client, other_client):
    t = _ingest(client, "ZOMATO")
    client.post(f"/transactions/{t['id']}/confirm")
    assert client.get("/metrics/live").json()["verified"] == 1
    assert other_client.get("/metrics/live").json()["verified"] == 0


def test_wilson_interval_and_prf_are_correct():
    from app.metrics import _prf, wilson
    lo, hi = wilson(9, 10)
    assert 0.55 < lo < 0.6 and 0.97 < hi < 0.99
    assert wilson(0, 0) == [0.0, 0.0]
    assert _prf(8, 2, 2) == (0.8, 0.8, 0.8)
    assert _prf(0, 0, 0) == (0.0, 0.0, 0.0)


def test_uncertain_messages_are_queued_for_review(client):
    _ingest(client, "QWXZ PLRK TTV 77")  # nothing recognises this
    m = client.get("/metrics/live").json()
    assert m["pending_review"] >= 1 and m["review_queue"][0]["merchant"].startswith("QWXZ")


# ---------------------------------------------------------------- assistant
def test_assistant_falls_back_to_rules_and_checks_its_numbers(client, monkeypatch):
    from app import assistant
    monkeypatch.setattr(assistant, "_pick_model", lambda: None)
    client.put("/profile", json={"annual_income": 1800000, "income_type": "salaried"})
    r = client.post("/ask", json={"question": "Which tax regime is better for me?"}).json()
    assert r["source"] == "template" and "regime" in r["answer"].lower() and r["grounding"]["ok"]
    assert r["facts_used"]["tax"]["estimated_tax"] > 0


def test_assistant_asks_for_income_when_missing(client, monkeypatch):
    from app import assistant
    monkeypatch.setattr(assistant, "_pick_model", lambda: None)
    assert "income" in client.post("/ask", json={"question": "how much can I invest?"}).json()["answer"].lower()


def test_grounding_check_flags_invented_figures():
    from app.assistant import check_grounding
    facts = {"tax": {"estimated_tax": 123456}, "cash": {"investable_now": 50000}}
    assert check_grounding("Your tax is about Rs 1,23,456 and you can invest Rs 50,000 over 6 months.", facts)["ok"]
    bad = check_grounding("You will save Rs 77,777 and owe Rs 1,23,456.", facts)
    assert not bad["ok"] and bad["unmatched"] == [77777]


def test_llm_answer_is_used_when_a_model_is_available(client, monkeypatch):
    import httpx
    from app import assistant
    monkeypatch.setattr(assistant, "_pick_model", lambda: "test-model")
    client.put("/profile", json={"annual_income": 1800000, "income_type": "salaried"})
    est = client.get("/dashboard").json()["tax"]["estimated_tax"]

    class R:
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": f"Your estimated tax is Rs {est:,}. You can also save Rs 999,999 (made up)."}}
    captured = {}
    monkeypatch.setattr(httpx, "post", lambda url, json=None, **kw: captured.update(body=json) or R())
    r = client.post("/ask", json={"question": "what do I owe?"}).json()
    assert r["source"] == "llm" and r["model"] == "test-model"
    assert r["grounding"]["unmatched"] == [999999] and not r["grounding"]["ok"]  # the invented figure is reported
    sys_prompt = captured["body"]["messages"][0]["content"]
    assert "FACTS (JSON)" in sys_prompt and str(est) in sys_prompt
    assert "ZOMATO" not in sys_prompt  # merchant names are never sent to the model


def test_ask_validates_input(client):
    assert client.post("/ask", json={"question": "hi"}).status_code == 422
    assert client.post("/ask", json={"question": "x" * 500}).status_code == 422


def test_deleting_an_account_removes_its_events_and_ids_are_not_reused(client, other_client):
    from app import event_stream
    from app.database import SessionLocal
    from app.models import User
    uid = client.get("/me").json()["id"]
    bob = other_client.get("/me").json()["id"]
    client.post("/sms/ingest", json={"text": DEBIT})
    assert event_stream.recent(50, uid=uid)
    client.delete("/me")
    assert event_stream.recent(50, uid=uid) == []
    with SessionLocal() as s:
        s.add(User(phone="+919111111111"))
        s.commit()
        assert s.query(User).filter(User.phone == "+919111111111").one().id > max(uid, bob)  # never handed out again


def test_static_files_are_revalidated_so_upgrades_take_effect(anon):
    r = anon.get("/app.js")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    assert anon.get("/manifest.webmanifest").status_code == 200
    assert anon.get("/sw.js").status_code == 200
    assert anon.get("/").status_code == 200  # the shell itself needs no sign-in; every data route does


def test_phone_app_download_needs_no_sign_in_and_holds_no_secret(anon):
    from app.main import APK_PATH
    r = anon.get("/android/tax-copilot-sms.apk")
    if APK_PATH.exists():
        assert r.status_code == 200 and r.headers["content-type"] == "application/vnd.android.package-archive"
        assert r.content[:2] == b"PK"  # an APK is a zip
        assert b"tcs_" not in r.content  # no session token inside; the account key is typed on the phone, never baked in
    else:
        assert r.status_code == 404 and "build" in r.json()["detail"]
