"""Demo sign-in walk-through, onboarding data, and the AI assistant (Claude call is mocked)."""
import pytest

PROFILE = dict(name="Ravi Kumar", income_type="salaried", occupation="Engineer", employer="TCS", age=31, monthly_salary=80000,
               monthly_expenses=0, current_balance=150000, savings_other=50000, loan_type="home", loan_emi=25000,
               loan_outstanding=2500000, investments_value=300000, investments_note="Index fund SIP")


@pytest.fixture()
def demo_on(monkeypatch):
    monkeypatch.setenv("COPILOT_DEMO", "1")


def auth(tok):
    return {"Authorization": "Bearer " + tok}


def test_fake_login_any_short_number_then_onboarding(anon, demo_on):
    r = anon.post("/auth/demo/request", json={"phone": "123"}).json()
    assert r["sent"] and r["demo_code"] == "123456" and r["exists"] is False
    assert anon.post("/auth/demo/start", json={"phone": "123", "code": "000000"}).status_code == 400  # wrong code rejected
    assert anon.post("/auth/demo/start", json={"phone": "123", "code": "123456"}).json() == {"needs_profile": True}
    r = anon.post("/auth/demo/start", json={"phone": "123", "code": "123456", "profile": PROFILE}).json()
    assert r["is_new"] and r["token"]
    h = auth(r["token"])
    p = anon.get("/profile", headers=h).json()
    assert p["name"] == "Ravi Kumar" and p["monthly_salary"] == 80000 and p["loan_emi"] == 25000 and p["annual_income"] == 960000 and p["current_balance"] == 150000
    assert len(anon.get("/transactions", headers=h).json()) > 20  # fake SMS built from the answers
    again = anon.post("/auth/demo/start", json={"phone": "123", "code": "123456"}).json()
    assert again["is_new"] is False  # same number comes back to the same person
    assert anon.get("/profile", headers=auth(again["token"])).json()["name"] == "Ravi Kumar"


def test_two_numbers_are_separate_people(anon, demo_on):
    a = anon.post("/auth/demo/start", json={"phone": "555", "code": "123456", "profile": PROFILE}).json()["token"]
    b = anon.post("/auth/demo/start", json={"phone": "666", "code": "123456", "profile": {**PROFILE, "name": "Sita"}}).json()["token"]
    assert anon.get("/profile", headers=auth(a)).json()["name"] == "Ravi Kumar"
    assert anon.get("/profile", headers=auth(b)).json()["name"] == "Sita"


def test_bad_numbers_and_off_mode(anon, demo_on):
    assert anon.post("/auth/demo/request", json={"phone": "12"}).status_code == 422
    assert anon.post("/auth/demo/request", json={"phone": "1234567890123"}).status_code == 422


def test_personas_exist_and_survive_purge(anon, demo_on):
    from app import demo_mode
    demo_mode.ensure_personas()
    r = anon.post("/auth/demo/start", json={"phone": "111", "code": "123456"}).json()
    assert r["is_new"] is False
    p = anon.get("/profile", headers=auth(r["token"])).json()
    assert p["name"] == "Priya Sharma" and p["loan_emi"] == 28000


def test_assistant_uses_claude_with_history_and_hides_key(anon, demo_on, monkeypatch):
    from app import assistant
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-secret")
    seen = {}

    class R:
        def raise_for_status(self): pass
        def json(self): return {"content": [{"type": "text", "text": "<reasoning>EMI is 25000 of 80000</reasoning><answer>Your EMI is about 31% of income.</answer>"}]}

    def fake_post(url, **kw):
        seen.update(url=url, **kw)
        return R()
    monkeypatch.setattr(assistant.httpx, "post", fake_post)
    tok = anon.post("/auth/demo/start", json={"phone": "777", "code": "123456", "profile": PROFILE}).json()["token"]
    out = anon.post("/ask", headers=auth(tok), json={"question": "Is my EMI too high?", "history": [
        {"role": "user", "text": "hi"}, {"role": "assistant", "text": "hello"}]}).json()
    assert out["source"] == "llm" and out["provider"] == "claude"
    assert out["answer"] == "Your EMI is about 31% of income." and "EMI is 25000" in out["reasoning"]
    assert "sk-ant" not in str(out)  # the key never reaches the browser
    assert seen["url"].startswith("https://api.anthropic.com/")
    assert [m["role"] for m in seen["json"]["messages"]] == ["user", "assistant", "user"]
    assert "Ravi Kumar" in seen["json"]["system"] and "emi_as_percent_of_income" in seen["json"]["system"]


def test_assistant_falls_back_when_claude_fails(anon, demo_on, monkeypatch):
    from app import assistant
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-secret")
    monkeypatch.setattr(assistant.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(assistant, "_pick_model", lambda: None)
    tok = anon.post("/auth/demo/start", json={"phone": "888", "code": "123456", "profile": PROFILE}).json()["token"]
    out = anon.post("/ask", headers=auth(tok), json={"question": "Which regime is better?"}).json()
    assert out["source"] == "template" and out["answer"]


def test_assistant_uses_gemini_when_only_that_key_is_set(anon, demo_on, monkeypatch):
    from app import assistant
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test-secret")
    seen = {}

    class R:
        def raise_for_status(self): pass
        def json(self): return {"candidates": [{"content": {"parts": [{"text": "<reasoning>25000/80000</reasoning><answer>About 31%.</answer>"}]}}]}

    monkeypatch.setattr(assistant.httpx, "post", lambda url, **kw: seen.update(url=url, **kw) or R())
    tok = anon.post("/auth/demo/start", json={"phone": "999", "code": "123456", "profile": PROFILE}).json()["token"]
    out = anon.post("/ask", headers=auth(tok), json={"question": "Is my EMI too high?", "history": [
        {"role": "user", "text": "hi"}, {"role": "assistant", "text": "hello"}]}).json()
    assert out["provider"] == "gemini" and out["answer"] == "About 31%." and "AIza" not in str(out)
    assert "generativelanguage.googleapis.com" in seen["url"] and seen["headers"]["x-goog-api-key"] == "AIza-test-secret"
    assert [c["role"] for c in seen["json"]["contents"]] == ["user", "model", "user"]
    assert "Ravi Kumar" in seen["json"]["systemInstruction"]["parts"][0]["text"]
