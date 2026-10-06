"""SQLite engine, session helper and a safe, additive schema migration.

Data location (default): backend/data/copilot.db  -  override with COPILOT_DATA_DIR.
`migrate()` only ever ADDS missing columns/indexes/tables. It never drops or rewrites user rows, and it copies
the database file to data/backups/ first whenever it has to change an existing table.
"""
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker, with_loader_criteria

DATA_DIR = Path(os.environ.get("COPILOT_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "copilot.db"
BACKUP_DIR = DATA_DIR / "backups"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def utcnow() -> datetime:
    """Naive UTC timestamp (what the database columns store)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_raw_db():
    """A session with NO user scope. Only for the accounts tables (users, otp, sessions) and the webhook's key lookup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def scoped_session(user_id: int) -> Session:
    """A session that can only see and write this user's rows (see the two events below)."""
    s = SessionLocal()
    s.info["user_id"] = int(user_id)
    return s


def _user_scoped():
    from .models import UserScoped
    return UserScoped


@event.listens_for(Session, "do_orm_execute")
def _scope_reads_and_writes(state):
    """Add `WHERE user_id = <current user>` to every SELECT / UPDATE / DELETE on a user-owned table."""
    uid = state.session.info.get("user_id")
    if uid is None or not (state.is_select or state.is_update or state.is_delete):
        return
    state.statement = state.statement.options(
        with_loader_criteria(_user_scoped(), lambda cls: cls.user_id == uid, include_aliases=True))


@event.listens_for(Session, "before_flush")
def _stamp_new_rows(session, flush_context, instances):
    """New user-owned rows get the current user's id. With no user in the session the write is refused (fail closed)."""
    UserScoped = _user_scoped()
    uid = session.info.get("user_id")
    for obj in session.new:
        if isinstance(obj, UserScoped) and obj.user_id is None:
            if uid is None:
                raise RuntimeError("Refusing to store user data without a signed-in user")
            obj.user_id = uid


def backup_db(label: str = "manual") -> Path | None:
    """Copy the SQLite file using the online backup API (safe while the app is running)."""
    if not DB_PATH.exists():
        return None
    BACKUP_DIR.mkdir(exist_ok=True)
    dest = BACKUP_DIR / f"copilot-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{label}.db"
    import sqlite3
    src = sqlite3.connect(DB_PATH)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return dest


def migrate() -> dict:
    """Create missing tables, then add any missing columns/indexes to existing tables. Idempotent."""
    from . import models  # noqa: F401  (registers tables on Base)
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    added = []
    needs_change = False
    for table in Base.metadata.sorted_tables:
        if table.name in existing:
            have = {c["name"] for c in insp.get_columns(table.name)}
            if any(c.name not in have for c in table.columns):
                needs_change = True
    backup = backup_db("pre-migration") if needs_change else None
    Base.metadata.create_all(engine)  # new tables only; never alters existing ones
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing:
                continue
            have = {c["name"] for c in inspect(conn).get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ctype = col.type.compile(engine.dialect)
                default = ""
                if col.default is not None and getattr(col.default, "is_scalar", False):
                    d = col.default.arg
                    default = f" DEFAULT {int(d) if isinstance(d, bool) else (repr(d) if isinstance(d, str) else d)}"
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ctype}{default}'))
                added.append(f"{table.name}.{col.name}")
        # unique index for webhook idempotency (NULLs are allowed many times in SQLite)
        conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ix_transactions_dedupe_key ON transactions (dedupe_key)'))
        _fix_merchant_rules_unique(conn)
    return {"added_columns": added, "backup": str(backup) if backup else None}


def _fix_merchant_rules_unique(conn):
    """Early databases made (merchant_key, txn_type) globally unique. With accounts it must be unique per user.
    SQLite cannot drop a constraint, so rebuild the table once (rows are copied unchanged)."""
    row = conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='merchant_rules'")).fetchone()
    if row and row[0] and "UNIQUE" in row[0].upper():
        conn.execute(text("ALTER TABLE merchant_rules RENAME TO merchant_rules_old"))
        for ix in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='merchant_rules_old' AND sql IS NOT NULL")).fetchall():
            conn.execute(text(f'DROP INDEX IF EXISTS "{ix[0]}"'))
        from .models import MerchantRule
        MerchantRule.__table__.create(conn)
        old = {c[1] for c in conn.execute(text("PRAGMA table_info(merchant_rules_old)")).fetchall()}
        new = [c.name for c in MerchantRule.__table__.columns]
        cols = ", ".join(f'"{c}"' for c in new if c in old)
        conn.execute(text(f'INSERT INTO merchant_rules ({cols}) SELECT {cols} FROM merchant_rules_old'))
        conn.execute(text("DROP TABLE merchant_rules_old"))
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_rule_user_merchant_type "
                      "ON merchant_rules (COALESCE(user_id, 0), merchant_key, txn_type)"))


def adopt_legacy_rows(user_id: int) -> int:
    """Rows saved before accounts existed have no owner. The first person to sign up inherits them (single-user upgrade)."""
    from .models import UserScoped
    n = 0
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if "user_id" in table.columns and table.name not in ("auth_sessions",):
                n += conn.execute(text(f'UPDATE "{table.name}" SET user_id = :u WHERE user_id IS NULL'), {"u": user_id}).rowcount or 0
    return n
