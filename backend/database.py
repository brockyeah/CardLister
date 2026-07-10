"""SQLAlchemy engine, session, and base setup."""
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DB_PATH = os.getenv("DB_PATH", "./cardlister.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"


def uploads_dir() -> Path:
    """Uploads sit alongside the SQLite DB file so a single Railway volume covers both."""
    return Path(DB_PATH).resolve().parent / "uploads"

# check_same_thread=False is required for SQLite + FastAPI's threaded request model
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

# Columns added to tables that already exist. create_all() only creates missing
# tables — it never ALTERs existing ones — so every new column on an existing
# table needs a registry entry here; it is added idempotently at startup.
_COLUMN_MIGRATIONS = [
    ("cards", "quantity", "INTEGER NOT NULL DEFAULT 1"),
    ("cards", "back_image_path", "VARCHAR"),
    ("cards", "is_first_bowman", "BOOLEAN NOT NULL DEFAULT 0"),
]


def ensure_columns(target_engine=None) -> None:
    """Add any registered missing columns (idempotent, SQLite ALTER TABLE)."""
    from sqlalchemy import text

    eng = target_engine or engine
    with eng.begin() as conn:
        for table, column, ddl in _COLUMN_MIGRATIONS:
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            if not rows:
                continue  # table doesn't exist yet — create_all builds it complete
            if column not in {r[1] for r in rows}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a request-scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Called once on app startup."""
    # Import models so they register with Base before create_all
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    ensure_columns()
