"""
challenge_models.py — quiz challenges, attempts, and leaderboards.

A Challenge wraps an existing generated deck/quiz (referenced by the same
content_hash used by content_models.PageContent / billing.ExtractedPage) and
opens it for competition. Each ChallengeAttempt is one user's run; the
leaderboard is derived by ordering a challenge's attempts by score desc.

Registered on billing.Base so db.create_all() / Alembic pick these up.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Integer,
    String,
    Text,
    Float,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from billing import Base, _now


class Challenge(Base):
    __tablename__ = "challenges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    creator_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The deck/quiz this challenge is based on, keyed like PageContent.content_hash.
    source_content_hash: Mapped[str] = mapped_column(String(64), index=True)
    # Scoring rule, e.g. {"points_per_correct": 10, "time_bonus": true}. Stored as
    # JSON text to stay portable across sqlite (dev) and postgres (prod).
    scoring_rule_json: Mapped[str] = mapped_column(Text, default="{}")
    starts_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | open | closed
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ChallengeAttempt(Base):
    __tablename__ = "challenge_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    challenge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("challenges.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    score: Mapped[int] = mapped_column(Integer, default=0)
    num_correct: Mapped[int] = mapped_column(Integer, default=0)
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        # Leaderboard read path: pull a challenge's attempts ordered by score desc.
        Index("ix_challenge_attempts_challenge_score", "challenge_id", "score"),
    )
