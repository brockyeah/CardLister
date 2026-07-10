"""Shared test setup. Env must be set BEFORE any backend import — the engine
binds DB_PATH at module import time."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("CARDLISTER_USERS", "tester:pw")
os.environ.setdefault("DISABLE_CALLUP_POLLER", "1")
os.environ.pop("ANTHROPIC_API_KEY", None)  # endpoint tests run in mock mode

import pytest  # noqa: E402


@pytest.fixture
def db_session():
    from backend.database import SessionLocal, init_db
    from backend.models import Card, Correction, Scan, CallupEvent  # noqa: E402

    init_db()
    db = SessionLocal()
    db.query(Card).delete()
    db.query(Correction).delete()
    db.query(Scan).delete()
    db.query(CallupEvent).delete()
    db.commit()
    yield db
    db.close()
