"""
dossier_models.py — per-user chapter dossiers.

A Dossier is the chapter-level container for a user's study material, keyed by
(user_id, subject, chapter). It does NOT duplicate page rows: its member pages
are derived from billing.UserPage where subject+chapter match. The Dossier only
caches the AI-generated study notes (notes_md) so we generate them once and
re-serve them for free — the same cost guard pattern as PageContent.

Registered on billing.Base so db.create_all() / Alembic pick it up.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Integer, String, Text, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from billing import Base, _now


class Dossier(Base):
    """One row per (user, subject, chapter). Stores only the generated chapter
    notes; member pages are derived from UserPage at read time."""
    __tablename__ = "dossiers"
    __table_args__ = (
        UniqueConstraint("user_id", "subject", "chapter", name="uq_dossier_user_subject_chapter"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    subject: Mapped[str] = mapped_column(String(255))
    chapter: Mapped[str] = mapped_column(String(255))
    notes_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes_generated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
