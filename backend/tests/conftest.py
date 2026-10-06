"""Test setup: every test run uses a throw-away data directory, so your real database and key are never touched.
Each test gets a fresh database with one signed-in user ("alice"); `other_client` signs in a second user ("bob")."""
import hashlib
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="copilot-test-")
os.environ["COPILOT_DATA_DIR"] = _TMP
os.environ.pop("COPILOT_OTP_PROVIDER", None)
os.environ["COPILOT_DEV_OTP"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def tmp_data_dir():
    return Path(_TMP)


def make_user(phone: str, token: str):
    """Create a user and a session for it. Returns the user id."""
    from app.database import SessionLocal, utcnow
    from app.models import AuthSession, User
    with SessionLocal() as s:
        u = User(phone=phone)
        s.add(u)
        s.flush()
        s.add(AuthSession(user_id=u.id, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                          expires_at=utcnow() + timedelta(days=1)))
        s.commit()
        return u.id


@pytest.fixture()
def db():
    """A session scoped to alice. The tables are emptied first so tests do not affect each other."""
    from app.database import Base, SessionLocal, engine, migrate, scoped_session
    from app import event_stream
    migrate()
    event_stream.reset()
    with engine.begin() as c:
        for t in reversed(Base.metadata.sorted_tables):
            c.execute(t.delete())
    uid = make_user("+919000000001", "tcs_alice_token")
    s = scoped_session(uid)
    yield s
    s.close()


ALICE = {"Authorization": "Bearer tcs_alice_token"}
BOB = {"Authorization": "Bearer tcs_bob_token"}


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient
    from app import http_security
    from app.main import app
    http_security.LIMITS.reset()
    with TestClient(app, headers=ALICE) as c:
        yield c


@pytest.fixture()
def anon(db):
    """A client with no credentials."""
    from fastapi.testclient import TestClient
    from app import http_security
    from app.main import app
    http_security.LIMITS.reset()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def other_client(db):
    """A second signed-in user (bob) against the same server."""
    from fastapi.testclient import TestClient
    from app.main import app
    make_user("+919000000002", "tcs_bob_token")
    with TestClient(app, headers=BOB) as c:
        yield c


@pytest.fixture()
def sms_key(client):
    """Alice's phone-forwarder key."""
    return client.get("/me/connect").json()["key"]
