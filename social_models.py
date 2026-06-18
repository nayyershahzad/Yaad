"""
social_models.py — friends, deck sharing, activity feed, and reactions.

Friendship is a directed request that becomes an undirected relationship once
accepted; a unique pair constraint stops duplicate requests. SharedDeck lets a
user publish one of their own decks (keyed by content_hash). FeedEvent is a flat
activity log; Reaction lets users react to feed events.

Registered on billing.Base so db.create_all() / Alembic pick these up.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Integer,
    String,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from billing import Base, _now


class Friendship(Base):
    __tablename__ = "friendships"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    requester_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    addressee_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | accepted | blocked
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    responded_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # One relationship row per ordered pair; prevents duplicate requests.
        UniqueConstraint("requester_user_id", "addressee_user_id", name="uq_friendship_pair"),
    )


class SharedDeck(Base):
    __tablename__ = "shared_decks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # The deck being published, keyed like PageContent.content_hash.
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    visibility: Mapped[str] = mapped_column(String(16), default="friends")  # friends | public | link
    shared_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        # A user publishes a given deck at most once.
        UniqueConstraint("owner_user_id", "content_hash", name="uq_shared_deck_owner_hash"),
    )


class FeedEvent(Base):
    __tablename__ = "feed_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(32))  # shared_deck | completed_challenge | earned_streak
    # Loose reference to the related object: integer id (e.g. challenge_id) or a
    # content_hash (e.g. shared deck). Both nullable so any event_type fits.
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ref_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        # Feed read path: newest events first.
        Index("ix_feed_events_created_at", "created_at"),
    )


class Reaction(Base):
    __tablename__ = "reactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    feed_event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("feed_events.id", ondelete="CASCADE"), index=True
    )
    reaction_type: Mapped[str] = mapped_column(String(32))  # emoji shortcode or named type
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        # One reaction of a given type per user per event.
        UniqueConstraint("user_id", "feed_event_id", "reaction_type", name="uq_reaction_user_event_type"),
    )
