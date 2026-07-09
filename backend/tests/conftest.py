"""Shared test setup. Env must be set BEFORE any backend import — the engine
binds DB_PATH at module import time."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("CARDLISTER_USERS", "tester:pw")
os.environ.pop("ANTHROPIC_API_KEY", None)  # endpoint tests run in mock mode

import pytest  # noqa: E402


@pytest.fixture
def db_session():
    # NOTE: Correction/Scan models don't exist until Task 4 — this fixture is
    # upgraded then to also clear those tables. Keep it minimal until then.
    from backend.database import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    yield db
    db.close()
