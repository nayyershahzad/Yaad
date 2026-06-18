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
# Postgres connection pool, sized PER WORKER. With uvicorn --workers 4 each worker
# gets its own pool, so keep these modest: 4 * (10 + 15) = 100 max API connections,
# which fits under Postgres max_connections=200 alongside the reconcile timer + psql.
_engine_kwargs: dict = {}
if not DATABASE_URL.startswith("sqlite"):
    _engine_kwargs = {"pool_size": 10, "max_overflow": 15, "pool_pre_ping": True}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def create_all() -> None:
    """Create tables for SQLite dev/tests only. On Postgres the schema is owned by
    Alembic (`alembic upgrade head` at deploy) — no-op here to avoid drift."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    import billing  # noqa: F401 — registers the billing ORM models on Base.metadata
    import content_models  # noqa: F401 — registers PageContent on the same Base
    import auth_models  # noqa: F401 — registers User on the same Base
    import challenge_models  # noqa: F401 — registers Challenge/ChallengeAttempt on the same Base
    import social_models  # noqa: F401 — registers Friendship/SharedDeck/FeedEvent/Reaction on the same Base
    import dossier_models  # noqa: F401 — registers Dossier on the same Base
    billing.Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency: yield a session, always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
