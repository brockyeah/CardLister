from sqlalchemy import create_engine, text

from backend.database import ensure_columns


def _cols(engine, table):
    with engine.connect() as conn:
        return {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


def test_ensure_columns_adds_missing_quantity(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE cards (id INTEGER PRIMARY KEY, player_name VARCHAR)"))
    ensure_columns(engine)
    assert "quantity" in _cols(engine, "cards")


def test_ensure_columns_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE cards (id INTEGER PRIMARY KEY)"))
    ensure_columns(engine)
    ensure_columns(engine)  # second run must not raise
    assert "quantity" in _cols(engine, "cards")


def test_ensure_columns_skips_missing_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    ensure_columns(engine)  # no cards table yet — create_all will build it complete
