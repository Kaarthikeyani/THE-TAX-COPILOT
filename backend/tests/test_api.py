"""API behaviour: manual ingestion, hardened webhook, corrections, rules, auth, rate limits, privacy, migration."""
import logging
import sqlite3
from datetime import date

import pytest

DEBIT = "Rs.2,450.00 debited from A/c XX4821 on 05-10-26 to VPA zomato@ybl (UPI Ref 481726). Bal Rs 1,48,200.00"
CREDIT = "INR 85,000.00 credited to A/c XX4821 on 04-10-26 by UPWORK ESCROW. Avl Bal INR 2,33,200.00"


def key_of(client):
    """The signed-in user's own phone-forwarder key."""
    return client.get("/me/connect").json()["key"]


def hook(client, body, key=None, **kw):
    return client.post("/sms/webhook", json=body, headers={"X-API-Key": key or key_of(client)}, **kw)


# ---------------------------------------------------------------- manual entry keeps working
def test_manual_ingest_debit_and_credit(client):
    d = client.post("/sms/ingest", json={"text": DEBIT}).json()
    c = client.post("/sms/ingest", json={"text": CREDIT}).json()
    assert d["type"] == "debit" and d["amount"] == 2450 and d["category"] == "food_dining"
    assert c["type"] == "credit" and c["amount"] == 85000 and c["category"] == "freelance_income"
    inc = client.get("/income").json()
    assert inc == [{"month": "2026-10", "amount": 85000.0}]


def test_manual_ingest_rejects_otp_with_helpful_message(client):
    r = client.post("/sms/ingest", json={"text": "OTP 482913 for txn of Rs 2,000 at FLIPKART. Do not share"})
    assert r.status_code == 422 and "OTP" in r.json()["detail"]


def test_validation_errors_never_echo_the_submitted_text(client):
    secret = "SECRET-NARRATION-9981"
    r = client.post("/sms/ingest", json={"text": secret[:4]})            # too short -> validation error
    assert r.status_code == 422 and "input" not in r.json() and secret[:4] not in r.text.replace("text", "")
    r = client.post("/profile", json={"annual_income": secret})
    assert secret not in client.put("/profile", json={"annual_income": secret}).text


# ---------------------------------------------------------------- webhook
def test_webhook_rejects_an_unknown_key(client):
    r = client.post("/sms/webhook", json={"messages": [{"text": DEBIT}]}, headers={"X-API-Key": "tcp_unknown"})
    assert r.status_code == 401 and r.json()["detail"]["error"] == "unauthorized"


def test_webhook_auth(client, monkeypatch):
    assert hook(client, {"messages": [{"text": DEBIT}]}, key="wrong").status_code == 401
    assert client.post("/sms/webhook", json={"messages": [{"text": DEBIT}]}).status_code == 401
    assert hook(client, {"messages": [{"text": DEBIT}]}).status_code == 200


def test_webhook_batch_reports_each_message(client, monkeypatch):
    body = {"messages": [
        {"text": DEBIT, "sender": "AX-HDFCBK", "received_at": "2026-10-05T10:15:00Z", "id": "m1"},
        {"text": CREDIT, "sender": "VM-SBIINB", "received_at": 1790000000000},
        {"text": DEBIT, "sender": "AX-HDFCBK", "received_at": "2026-10-05T10:15:00Z", "id": "m1"},          # same message again
        {"text": "Hi, are we still meeting for lunch? Rs 500 from me", "sender": "+919812345678"},          # personal sender
        {"text": "OTP 123456 for txn of Rs 2,000. Do not share", "sender": "AX-HDFCBK"},                    # OTP
        {"text": "hello world no money here", "sender": "AX-HDFCBK"},                                      # unparseable
        {"sender": "AX-HDFCBK"},                                                                           # invalid item
    ]}
    r = hook(client, body).json()
    assert r["received"] == 7
    assert (r["saved"], r["duplicate"], r["ignored"], r["error"]) == (2, 1, 3, 1)
    st = [x["status"] for x in r["results"]]
    assert st == ["saved", "saved", "duplicate", "ignored", "ignored", "ignored", "error"]
    codes = {x["index"]: x["code"] for x in r["results"] if "code" in x}
    assert codes == {3: "non_bank_sender", 4: "not_a_transaction", 5: "unparseable", 6: "invalid_item"}
    assert len(client.get("/transactions").json()) == 2


def test_webhook_is_idempotent_across_requests(client, monkeypatch):
    body = {"messages": [{"text": DEBIT, "sender": "AX-HDFCBK", "id": "abc"}]}
    assert hook(client, body).json()["saved"] == 1
    again = hook(client, body).json()
    assert again["saved"] == 0 and again["duplicate"] == 1
    assert len(client.get("/transactions").json()) == 1


def test_webhook_same_text_different_timestamps_are_both_kept(client, monkeypatch):
    a = {"text": DEBIT, "sender": "AX-HDFCBK", "received_at": "2026-10-05T10:15:00Z"}
    b = {"text": DEBIT, "sender": "AX-HDFCBK", "received_at": "2026-10-05T18:40:00Z"}
    assert hook(client, {"messages": [a, b]}).json()["saved"] == 2


def test_webhook_accepts_common_forwarder_field_names_and_single_message(client, monkeypatch):
    r = hook(client, {"body": DEBIT, "from": "AX-HDFCBK", "timestamp": 1790000000000, "uid": 7}).json()
    assert r["saved"] == 1
    r2 = hook(client, [{"message": CREDIT, "address": "JD-ICICIB-T"}]).json()
    assert r2["saved"] == 1


def test_webhook_whole_request_errors(client, monkeypatch):
    assert hook(client, {"messages": []}).status_code == 400
    assert hook(client, {"nothing": 1}).json()["detail"]["error"] == "invalid_payload"
    big = {"messages": [{"text": DEBIT}] * 201}
    assert hook(client, big).status_code == 413
    r = client.post("/sms/webhook", content=b"not json", headers={"X-API-Key": key_of(client), "Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["detail"]["error"] == "invalid_json"


def test_webhook_uses_message_time_when_sms_has_no_date(client, monkeypatch):
    hook(client, {"messages": [{"text": "Rs 1,200.00 debited from A/c XX1 to SWIGGY", "sender": "AX-HDFCBK",
                                "received_at": "2026-09-14T09:00:00Z"}]})
    assert client.get("/transactions").json()[0]["date"] == "2026-09-14"


# ---------------------------------------------------------------- security
def test_rate_limit_returns_429_with_retry_after(client, monkeypatch):
    from app import http_security
    monkeypatch.setattr(http_security, "LIMIT_RULES", [("/sms/webhook", 3, 60.0, "webhook")] + http_security.LIMIT_RULES)
    codes = [hook(client, {"messages": [{"text": DEBIT, "id": str(i)}]}).status_code for i in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]
    assert hook(client, {"messages": []}).headers.get("Retry-After")


def test_repeated_bad_keys_lock_the_webhook_but_not_the_signed_in_app(client, monkeypatch):
    good = key_of(client)
    codes = [hook(client, {"messages": [{"text": DEBIT}]}, key="bad").status_code for _ in range(12)]
    assert codes[:10] == [401] * 10 and 429 in codes[10:]
    assert hook(client, {"messages": [{"text": DEBIT}]}, key=good).status_code == 429  # even the right key is refused while locked
    assert client.get("/profile").status_code == 200  # a bad forwarder on the same network must not lock people out of the app


def test_every_route_needs_a_session_except_health_login_and_webhook(anon):
    assert anon.get("/health").status_code == 200
    for path in ("/transactions", "/profile", "/dashboard", "/plan/monthly", "/system", "/rules", "/glossary", "/me",
                 "/stream", "/metrics/live", "/experiments", "/categories"):
        assert anon.get(path).status_code == 401, path
    assert anon.post("/ask", json={"question": "what is my tax?"}).status_code == 401
    assert anon.get("/profile", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert anon.get("/profile", headers={"X-API-Key": "tcs_alice_token"}).status_code == 401  # headers other than Bearer do not sign in


def test_phone_key_can_post_sms_but_cannot_read_data(anon, client):
    key = key_of(client)
    assert anon.get("/transactions", headers={"X-API-Key": key}).status_code == 401
    assert anon.get("/transactions", headers={"Authorization": f"Bearer {key}"}).status_code == 401
    assert anon.post("/sms/webhook", json={"messages": [{"text": DEBIT}]}, headers={"X-API-Key": key}).status_code == 200


def test_host_header_allow_list_blocks_dns_rebinding(client):
    assert client.get("/health", headers={"Host": "evil.example.com"}).status_code == 400
    assert client.get("/health", headers={"Host": "localhost:8811"}).status_code == 200


def test_oversized_body_is_rejected(client):
    r = client.post("/sms/ingest", content=b"x" * (600 * 1024), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_no_cross_origin_access_by_default(client):
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_logs_never_contain_sms_text_or_keys(client, monkeypatch, caplog):
    key = key_of(client)
    with caplog.at_level(logging.DEBUG):
        hook(client, {"messages": [{"text": DEBIT, "id": "z"}]})
        client.post("/sms/ingest", json={"text": CREDIT})
        client.post("/sms/ingest", json={"text": "OTP 998877 Do not share Rs 5"})
        hook(client, {"messages": [{"text": "bad"}]}, key="wrong-key-value")
    blob = " ".join(r.getMessage() for r in caplog.records)
    for secret in ("zomato", "UPWORK", "998877", "481726", key, "wrong-key-value"):
        assert secret.lower() not in blob.lower()


def test_raw_sms_is_encrypted_at_rest(client, tmp_data_dir):
    client.post("/sms/ingest", json={"text": DEBIT})
    raw = sqlite3.connect(tmp_data_dir / "copilot.db").execute("select raw_encrypted from transactions").fetchone()[0]
    assert "zomato" not in raw.lower() and raw.startswith("gAAAA")
    assert client.get("/transactions/1/raw").json()["raw_sms"] == DEBIT


# ---------------------------------------------------------------- corrections and rules
def test_correction_persists_and_teaches_a_rule(client):
    t = client.post("/sms/ingest", json={"text": "Rs 700.00 debited from A/c XX1 on 05-10-26 to PHARMEASY. Bal Rs 90,000"}).json()
    r = client.patch(f"/transactions/{t['id']}/category", json={"category": "preventive_healthcare"})
    assert r.status_code == 200 and r.json()["category"] == "preventive_healthcare" and r.json()["tax_section"] == "80D"
    assert r.json()["user_corrected"] and r.json()["source"] == "user_correction"
    again = client.get(f"/transactions/{t['id']}").json()
    assert again["category"] == "preventive_healthcare"
    # the next message from the same merchant is classified by the learned rule
    n = client.post("/sms/ingest", json={"text": "Rs 300.00 debited from A/c XX1 on 06-10-26 to PHARMEASY. Bal Rs 89,000"}).json()
    assert n["category"] == "preventive_healthcare" and n["source"] == "user_rule"
    rules = client.get("/rules").json()["learned_from_you"]
    assert rules[0]["merchant"] == "PHARMEASY" and rules[0]["used"] >= 1


def test_correction_updates_look_alike_transactions(client):
    ids = [client.post("/sms/ingest", json={"text": f"Rs {a}.00 debited from A/c XX1 on 0{d}-10-26 to SRI VENKAT STORES. Bal Rs 90,000"}).json()["id"]
           for a, d in ((200, 1), (350, 2), (410, 3))]
    r = client.patch(f"/transactions/{ids[0]}/category", json={"category": "entertainment"}).json()
    assert r["updated_similar"] == 2
    assert {client.get(f"/transactions/{i}").json()["category"] for i in ids} == {"entertainment"}
    r2 = client.patch(f"/transactions/{ids[1]}/category", json={"category": "travel", "apply_to_similar": False}).json()
    assert r2["updated_similar"] == 0
    assert client.get(f"/transactions/{ids[2]}").json()["category"] == "entertainment"


def test_correction_validates_direction_and_category(client):
    d = client.post("/sms/ingest", json={"text": DEBIT}).json()["id"]
    c = client.post("/sms/ingest", json={"text": CREDIT}).json()["id"]
    assert client.patch(f"/transactions/{d}/category", json={"category": "salary_income"}).status_code == 422
    assert client.patch(f"/transactions/{c}/category", json={"category": "groceries"}).status_code == 422
    assert client.patch(f"/transactions/{d}/category", json={"category": "nonsense"}).status_code == 422
    assert client.patch("/transactions/9999/category", json={"category": "groceries"}).status_code == 404


def test_reclassifying_a_credit_as_non_income_removes_it_from_income_history(client):
    t = client.post("/sms/ingest", json={"text": "INR 5,000.00 credited to A/c XX1 on 04-10-26 by RAMESH FRIEND. Avl Bal INR 1,00,000.00"}).json()
    assert t["category"] == "other_income" and client.get("/income").json() == []     # gifts / friends are not taxable income
    client.patch(f"/transactions/{t['id']}/category", json={"category": "freelance_income"})
    assert client.get("/income").json() == [{"month": "2026-10", "amount": 5000.0}]
    client.patch(f"/transactions/{t['id']}/category", json={"category": "other_income"})
    assert client.get("/income").json() == []


def test_delete_reverses_income_sample(client):
    t = client.post("/sms/ingest", json={"text": CREDIT}).json()
    assert client.get("/income").json()
    client.delete(f"/transactions/{t['id']}")
    assert client.get("/income").json() == []


def test_add_rule_endpoint_and_direction_check(client):
    assert client.post("/rules", json={"merchant": "Local Dhaba 12", "category": "food_dining"}).status_code == 200
    assert client.post("/rules", json={"merchant": "x client", "category": "salary_income", "txn_type": "debit"}).status_code == 422
    t = client.post("/sms/ingest", json={"text": "Rs 90.00 debited from A/c XX1 on 05-10-26 to Local Dhaba 12. Bal Rs 9,000"}).json()
    assert t["source"] == "user_rule" and t["category"] == "food_dining"


def test_user_csv_rules_need_no_python(tmp_path, monkeypatch):
    from app import classifier
    f = tmp_path / "user_rules.csv"
    f.write_text("keyword,category\n# comment\nZYXWV COFFEE,food_dining\nBADLINE\nNOPE,not_a_category\n", encoding="utf-8")
    monkeypatch.setattr(classifier, "USER_RULES_PATH", f)
    classifier.reload_rules()
    try:
        assert classifier.tier1_classify("ZYXWV COFFEE BLR", "debit")["category"] == "food_dining"
        assert classifier.tier1_classify("NOPE", "debit") is None
    finally:
        monkeypatch.undo()
        classifier.reload_rules()


# ---------------------------------------------------------------- monthly plan API
def test_monthly_plan_endpoint_and_compare(client):
    assert client.post("/demo/load").status_code == 200
    r = client.get("/plan/monthly").json()
    assert r["kind"] == "monthly" and len(r["months"]) == 12 and r["data_coverage"]["transactions_in_fy"] > 0
    cmp = client.post("/plan/monthly/compare", json={"income_shock_pct": -40, "buffer_months": 6}).json()
    assert cmp["changed"] == ["buffer_months", "income_shock_pct"]
    assert cmp["diff"]["projected_annual_income"] < 0
    assert client.get("/dashboard/multi_period").json()["granularity"] == "quarterly"


def test_bills_flow_into_the_plan(client):
    client.post("/demo/load")
    b = client.post("/bills", json={"month": "2027-01", "name": "School fee", "amount": 50000}).json()
    plan = client.get("/plan/monthly").json()
    jan = next(m for m in plan["months"] if m["month"] == "2027-01")
    assert jan["bills"] == 50000
    client.delete(f"/bills/{b['id']}")
    assert next(m for m in client.get("/plan/monthly").json()["months"] if m["month"] == "2027-01")["bills"] == 0


def test_demo_never_wipes_real_data(client):
    client.post("/sms/ingest", json={"text": DEBIT})
    assert client.post("/demo/load").status_code == 409
    assert len(client.get("/transactions").json()) == 1
    client.delete("/transactions/1")
    client.post("/demo/load")
    client.post("/sms/ingest", json={"text": DEBIT})
    client.post("/demo/clear")
    left = client.get("/transactions").json()
    assert len(left) == 1 and left[0]["origin"] == "manual"


# ---------------------------------------------------------------- migration keeps user data
OLD_SCHEMA = """
CREATE TABLE transactions (id INTEGER PRIMARY KEY, created_at DATETIME, txn_date DATE, amount FLOAT NOT NULL,
  txn_type VARCHAR(10) NOT NULL, merchant VARCHAR(120), account_suffix VARCHAR(10), balance FLOAT, category VARCHAR(60),
  label VARCHAR(80), tax_section VARCHAR(20), classification_source VARCHAR(30), confidence FLOAT, parse_confidence FLOAT,
  amount_bucket VARCHAR(20), raw_encrypted TEXT, sms_hash VARCHAR(64));
CREATE TABLE profile (id INTEGER PRIMARY KEY, name VARCHAR(80), income_type VARCHAR(20), annual_income FLOAT,
  monthly_expenses FLOAT, current_balance FLOAT, safety_buffer_months FLOAT, age INTEGER, home_loan_interest FLOAT,
  risk_alpha FLOAT, tax_paid_so_far FLOAT);
INSERT INTO transactions (id, txn_date, amount, txn_type, merchant, category, tax_section, raw_encrypted, sms_hash)
  VALUES (1, '2026-09-01', 1234.5, 'debit', 'OLD MERCHANT', 'groceries', 'none', 'gAAAAxyz', 'h1'),
         (2, '2026-09-02', 99000, 'credit', 'OLD CLIENT', 'freelance_income', 'none', 'gAAAAabc', 'h2');
INSERT INTO profile (id, name, income_type, annual_income, monthly_expenses, current_balance, safety_buffer_months, age,
  home_loan_interest, risk_alpha, tax_paid_so_far) VALUES (1, 'Asha', 'freelancer', 1800000, 42000, 310000, 4, 36, 0, 0.9, 5000);
"""


def test_migration_adds_columns_without_losing_rows(tmp_path):
    """Build a database with the ORIGINAL schema (before this version), put data in it, migrate, check nothing is lost.
    Runs in a subprocess so it cannot disturb the other tests' database."""
    import json, os, subprocess, sys
    con = sqlite3.connect(tmp_path / "copilot.db")
    con.executescript(OLD_SCHEMA)
    con.commit()
    con.close()
    code = "import json; from app.database import migrate; print(json.dumps([migrate(), migrate()]))"
    env = {**os.environ, "COPILOT_DATA_DIR": str(tmp_path)}
    backend = str(__import__("pathlib").Path(__file__).resolve().parent.parent)
    out = subprocess.run([sys.executable, "-c", code], cwd=backend, env=env, capture_output=True, text=True, check=True).stdout
    first, second = json.loads(out.strip().splitlines()[-1])
    assert "transactions.user_corrected" in first["added_columns"] and "profile.other_deductions_old" in first["added_columns"]
    assert first["backup"] and list((tmp_path / "backups").glob("*pre-migration.db"))
    assert second["added_columns"] == []   # idempotent
    con = sqlite3.connect(tmp_path / "copilot.db")
    rows = con.execute("select id, amount, merchant, category, raw_encrypted, origin, user_corrected from transactions order by id").fetchall()
    assert rows == [(1, 1234.5, "OLD MERCHANT", "groceries", "gAAAAxyz", "manual", 0),
                    (2, 99000.0, "OLD CLIENT", "freelance_income", "gAAAAabc", "manual", 0)]
    assert con.execute("select name, annual_income, current_balance, other_deductions_old from profile").fetchone() == ("Asha", 1800000.0, 310000.0, 0.0)
    # the backup really holds the pre-migration data
    bk = sqlite3.connect(next((tmp_path / "backups").glob("*pre-migration.db")))
    assert bk.execute("select count(*) from transactions").fetchone()[0] == 2
    con.close()
    bk.close()


def test_learned_rule_also_matches_spelling_variants(client):
    t = client.post("/sms/ingest", json={"text": "Rs 700.00 debited from A/c XX1 on 05-10-26 to PHARMEASY LABS. Bal Rs 90,000"}).json()
    client.patch(f"/transactions/{t['id']}/category", json={"category": "preventive_healthcare"})
    v = client.post("/sms/ingest", json={"text": "Rs 300.00 debited from A/c XX1 on 06-10-26 to PHARMEASY LABS 4417. Bal Rs 89,000"}).json()
    assert v["category"] == "preventive_healthcare" and v["source"] == "user_rule_similar"
    other = client.post("/sms/ingest", json={"text": "Rs 300.00 debited from A/c XX1 on 06-10-26 to NETFLIX. Bal Rs 89,000"}).json()
    assert other["source"] != "user_rule_similar"
