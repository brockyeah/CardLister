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
