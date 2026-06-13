"""
db.py — SQLAlchemy engine + session factory, and dev table creation.

DATABASE_URL drives the backend:
  - prod:  postgresql+psycopg://yaad:...@localhost:5432/yaad   (.env)
  - dev:   sqlite:///./yaad_dev.db                              (default here)

create_all() is for dev only — use Alembic for prod migrations (per CLAUDE.md).
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Default to a local SQLite file so the app stands up with zero provisioning and
# never collides with the other tenants' Postgres on this shared VPS.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./yaad_dev.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def create_all() -> None:
    """Create tables for all models registered on billing.Base (dev only)."""
    import billing  # noqa: F401 — registers the billing ORM models on Base.metadata
    import content_models  # noqa: F401 — registers PageContent on the same Base
    import auth_models  # noqa: F401 — registers User on the same Base
    billing.Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency: yield a session, always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
