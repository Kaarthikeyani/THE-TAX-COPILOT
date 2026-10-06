"""Demo mode: one-tap sandbox with fake data, no phone sign-in, no SMS forwarding, isolated per visitor."""
import pytest


@pytest.fixture()
def demo_on(monkeypatch):
    monkeypatch.setenv("COPILOT_DEMO", "1")


def test_mode_is_off_by_default(anon):
    assert anon.get("/auth/mode").json()["demo"] is False
    assert anon.post("/auth/demo").status_code == 404


def test_enter_demo_gives_private_sandbox_with_fake_data(anon, demo_on):
    assert anon.get("/auth/mode").json()["demo"] is True
    a = anon.post("/auth/demo").json()
    b = anon.post("/auth/demo").json()
    ha, hb = {"Authorization": "Bearer " + a["token"]}, {"Authorization": "Bearer " + b["token"]}
    ta = anon.get("/transactions", headers=ha).json()
    assert len(ta) > 10  # fake sample messages were loaded
    anon.delete("/transactions/%d" % ta[0]["id"], headers=ha)
    assert len(anon.get("/transactions", headers=hb).json()) == len(ta)  # b is untouched by a


def test_phone_login_and_webhook_are_off_in_demo(anon, demo_on):
    assert anon.post("/auth/otp/request", json={"phone": "9876543210"}).status_code == 403
    assert anon.post("/sms/webhook", json={"text": "x"}, headers={"X-API-Key": "tcp_x"}).status_code == 403
    token = anon.post("/auth/demo").json()["token"]
    assert anon.get("/me/connect", headers={"Authorization": "Bearer " + token}).status_code == 403


def test_old_sandboxes_are_purged(anon, demo_on):
    from datetime import timedelta
    from app.database import SessionLocal, utcnow
    from app.models import User
    anon.post("/auth/demo")
    with SessionLocal() as s:
        u = s.query(User).filter(User.phone.like("+000%")).first()
        u.created_at = utcnow() - timedelta(days=3)
        s.commit()
    anon.post("/auth/demo")
    with SessionLocal() as s:
        assert s.query(User).filter(User.phone.like("+000%")).count() == 1
