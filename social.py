"""
social.py — friends, deck sharing, activity feed, and reactions (M3 Social API).

Sync SQLAlchemy + FastAPI, mirroring billing.py/auth.py exactly:
  - DB session via `db_module.get_db` (sync `Session`, `db.get`/`db.execute(select(...))`).
  - Auth via `auth.current_user_id` (Bearer JWT -> integer user id).

Friendship is a directed request that becomes an undirected relationship once
accepted (uq on (requester,addressee)). Sharing a deck publishes a SharedDeck
(idempotent on (owner,content_hash)) and emits a FeedEvent. The feed shows the
current user's own events plus those of their accepted friends, newest first,
with per-type reaction counts and whether the current user reacted.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, or_, and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import db as db_module
from auth import current_user_id
from auth_models import User
from billing import _now
from content_models import PageContent
from social_models import Friendship, SharedDeck, FeedEvent, Reaction


def _load_deck_content(db: Session, content_hash: str) -> tuple[list, list]:
    """Read flashcards + quiz for a page from PageContent. Empty lists if the
    page has no generated content yet or the JSON is unparseable."""
    pc = db.get(PageContent, content_hash)
    if pc is None:
        return [], []

    def _parse(raw: str | None) -> list:
        if not raw:
            return []
        try:
            val = json.loads(raw)
        except (ValueError, TypeError):
            return []
        return val if isinstance(val, list) else []

    return _parse(pc.flashcards_json), _parse(pc.quiz_json)

log = logging.getLogger(__name__)

get_db = db_module.get_db

router = APIRouter(prefix="/social", tags=["social"])


# --------------------------------------------------------------------------- schemas
class FriendRequestIn(BaseModel):
    addressee_user_id: int | None = None
    email: EmailStr | None = None


class FriendRespondIn(BaseModel):
    action: str  # accept | block


class ShareDeckIn(BaseModel):
    content_hash: str
    visibility: str = "friends"  # friends | public | link


class ReactIn(BaseModel):
    reaction_type: str  # like | fire | clap | ...


# --------------------------------------------------------------------------- helpers
def _accepted_friend_ids(db: Session, user_id: int) -> list[int]:
    """User ids who are accepted friends of `user_id` (either direction)."""
    rows = db.execute(
        select(Friendship.requester_user_id, Friendship.addressee_user_id).where(
            Friendship.status == "accepted",
            or_(
                Friendship.requester_user_id == user_id,
                Friendship.addressee_user_id == user_id,
            ),
        )
    ).all()
    ids: set[int] = set()
    for requester, addressee in rows:
        ids.add(addressee if requester == user_id else requester)
    ids.discard(user_id)
    return list(ids)


def _existing_friendship(db: Session, a: int, b: int) -> Friendship | None:
    """Any friendship row between two users, in either direction."""
    return db.execute(
        select(Friendship).where(
            or_(
                and_(Friendship.requester_user_id == a, Friendship.addressee_user_id == b),
                and_(Friendship.requester_user_id == b, Friendship.addressee_user_id == a),
            )
        )
    ).scalars().first()


# --------------------------------------------------------------------------- friends
@router.post("/friends/request")
def request_friend(
    body: FriendRequestIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> dict:
    """Create a pending friendship from the current user to another user (by id or
    email). Rejects self-requests, unknown users, and any existing relationship."""
    if body.addressee_user_id is not None:
        target = db.get(User, body.addressee_user_id)
    elif body.email is not None:
        target = db.execute(
            select(User).where(User.email == body.email.lower())
        ).scalar_one_or_none()
    else:
        raise HTTPException(status_code=400, detail={"reason": "addressee_user_id_or_email_required"})

    if target is None:
        raise HTTPException(status_code=404, detail={"reason": "user_not_found"})
    if target.id == user_id:
        raise HTTPException(status_code=400, detail={"reason": "cannot_friend_self"})

    if _existing_friendship(db, user_id, target.id) is not None:
        raise HTTPException(status_code=409, detail={"reason": "friendship_already_exists"})

    fr = Friendship(requester_user_id=user_id, addressee_user_id=target.id, status="pending")
    db.add(fr)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail={"reason": "friendship_already_exists"})
    db.refresh(fr)
    return {
        "id": fr.id,
        "requester_user_id": fr.requester_user_id,
        "addressee_user_id": fr.addressee_user_id,
        "status": fr.status,
    }


@router.get("/friends/requests")
def incoming_requests(
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> dict:
    """Pending friend requests where the current user is the addressee."""
    rows = db.execute(
        select(Friendship, User)
        .join(User, User.id == Friendship.requester_user_id)
        .where(Friendship.addressee_user_id == user_id, Friendship.status == "pending")
        .order_by(Friendship.created_at.desc())
    ).all()
    requests = [{
        "friendship_id": fr.id,
        "requester": {"id": u.id, "email": u.email},
        "created_at": fr.created_at.isoformat() if fr.created_at else None,
    } for fr, u in rows]
    return {"count": len(requests), "requests": requests}


@router.post("/friends/{friendship_id}/respond")
def respond_friend(
    friendship_id: int,
    body: FriendRespondIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> dict:
    """Accept or block a pending request. Only the addressee may respond."""
    if body.action not in {"accept", "block"}:
        raise HTTPException(status_code=400, detail={"reason": "invalid_action", "allowed": ["accept", "block"]})

    fr = db.get(Friendship, friendship_id)
    if fr is None:
        raise HTTPException(status_code=404, detail={"reason": "friendship_not_found"})
    if fr.addressee_user_id != user_id:
        raise HTTPException(status_code=403, detail={"reason": "not_addressee"})
    if fr.status != "pending":
        raise HTTPException(status_code=409, detail={"reason": "already_responded", "status": fr.status})

    fr.status = "accepted" if body.action == "accept" else "blocked"
    fr.responded_at = _now()
    db.commit()
    return {"id": fr.id, "status": fr.status, "responded_at": fr.responded_at.isoformat()}


@router.get("/friends")
def list_friends(
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> dict:
    """Accepted friends of the current user (the OTHER user's id + email)."""
    friend_ids = _accepted_friend_ids(db, user_id)
    if not friend_ids:
        return {"count": 0, "friends": []}
    users = db.execute(select(User).where(User.id.in_(friend_ids))).scalars().all()
    friends = [{"id": u.id, "email": u.email} for u in users]
    return {"count": len(friends), "friends": friends}


# --------------------------------------------------------------------------- decks
@router.post("/decks/share")
def share_deck(
    body: ShareDeckIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> dict:
    """Publish one of the current user's decks (idempotent on (owner,content_hash))
    and emit a `shared_deck` FeedEvent the first time it is shared."""
    if body.visibility not in {"friends", "public", "link"}:
        raise HTTPException(status_code=400, detail={"reason": "invalid_visibility",
                                                     "allowed": ["friends", "public", "link"]})

    existing = db.execute(
        select(SharedDeck).where(
            SharedDeck.owner_user_id == user_id,
            SharedDeck.content_hash == body.content_hash,
        )
    ).scalar_one_or_none()

    if existing is not None:
        # Idempotent: keep the share, allow visibility update, no duplicate feed event.
        if existing.visibility != body.visibility:
            existing.visibility = body.visibility
            db.commit()
        return {
            "id": existing.id,
            "content_hash": existing.content_hash,
            "visibility": existing.visibility,
            "created": False,
        }

    deck = SharedDeck(owner_user_id=user_id, content_hash=body.content_hash, visibility=body.visibility)
    db.add(deck)
    try:
        db.flush()
    except IntegrityError:
        # Lost a race on the unique (owner,content_hash) constraint.
        db.rollback()
        existing = db.execute(
            select(SharedDeck).where(
                SharedDeck.owner_user_id == user_id,
                SharedDeck.content_hash == body.content_hash,
            )
        ).scalar_one_or_none()
        return {
            "id": existing.id if existing else None,
            "content_hash": body.content_hash,
            "visibility": existing.visibility if existing else body.visibility,
            "created": False,
        }

    db.add(FeedEvent(actor_user_id=user_id, event_type="shared_deck", ref_hash=body.content_hash))
    db.commit()
    db.refresh(deck)
    return {"id": deck.id, "content_hash": deck.content_hash, "visibility": deck.visibility, "created": True}


@router.get("/shared/{content_hash}")
def get_shared_deck(content_hash: str, db: Session = Depends(get_db)) -> dict:
    """PUBLIC (no auth): fetch a deck shared by URL.

    Returns the deck if ANY user has a SharedDeck row for this content_hash with
    visibility in {"link", "public"}. This lets a student share a deck with anyone
    via a link — no login, friendship, or ownership required. 404 if the page is
    not shared as link/public.
    """
    deck = db.execute(
        select(SharedDeck, User)
        .join(User, User.id == SharedDeck.owner_user_id)
        .where(
            SharedDeck.content_hash == content_hash,
            SharedDeck.visibility.in_(["link", "public"]),
        )
        .order_by(SharedDeck.shared_at.asc())  # earliest public share wins
    ).first()

    if deck is None:
        raise HTTPException(status_code=404, detail={"reason": "deck_not_shared"})

    shared_deck, owner = deck
    flashcards, quiz = _load_deck_content(db, content_hash)
    return {
        "content_hash": content_hash,
        "flashcards": flashcards,
        "quiz": quiz,
        "shared_by": owner.email or owner.id,
        "visibility": shared_deck.visibility,
    }


# --------------------------------------------------------------------------- feed
@router.get("/feed")
def get_feed(
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
    limit: int = 50,
) -> dict:
    """Activity feed: the current user's events plus those of accepted friends,
    newest first. Each event carries actor (id+email), event_type, ref, created_at,
    reaction counts grouped by type, and whether the current user reacted."""
    limit = max(1, min(limit, 100))
    actor_ids = _accepted_friend_ids(db, user_id) + [user_id]

    rows = db.execute(
        select(FeedEvent, User)
        .join(User, User.id == FeedEvent.actor_user_id)
        .where(FeedEvent.actor_user_id.in_(actor_ids))
        .order_by(FeedEvent.created_at.desc())  # uses ix_feed_events_created_at
        .limit(limit)
    ).all()

    event_ids = [fe.id for fe, _ in rows]
    counts: dict[int, dict[str, int]] = {}
    mine: dict[int, set[str]] = {}

    if event_ids:
        # Per-(event,type) reaction counts in one grouped query.
        count_rows = db.execute(
            select(Reaction.feed_event_id, Reaction.reaction_type, func.count())
            .where(Reaction.feed_event_id.in_(event_ids))
            .group_by(Reaction.feed_event_id, Reaction.reaction_type)
        ).all()
        for ev_id, rtype, n in count_rows:
            counts.setdefault(ev_id, {})[rtype] = n

        # Which reaction types the current user has placed on these events.
        my_rows = db.execute(
            select(Reaction.feed_event_id, Reaction.reaction_type)
            .where(Reaction.feed_event_id.in_(event_ids), Reaction.user_id == user_id)
        ).all()
        for ev_id, rtype in my_rows:
            mine.setdefault(ev_id, set()).add(rtype)

    events = [{
        "id": fe.id,
        "actor": {"id": u.id, "email": u.email},
        "event_type": fe.event_type,
        "ref_id": fe.ref_id,
        "ref_hash": fe.ref_hash,
        "created_at": fe.created_at.isoformat() if fe.created_at else None,
        "reactions": counts.get(fe.id, {}),
        "my_reactions": sorted(mine.get(fe.id, set())),
        "reacted": bool(mine.get(fe.id)),
    } for fe, u in rows]

    return {"count": len(events), "events": events}


@router.post("/feed/{event_id}/react")
def react(
    event_id: int,
    body: ReactIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> dict:
    """Add a reaction to a feed event. Idempotent on (user,event,type)."""
    rtype = body.reaction_type.strip()
    if not rtype:
        raise HTTPException(status_code=400, detail={"reason": "reaction_type_required"})

    if db.get(FeedEvent, event_id) is None:
        raise HTTPException(status_code=404, detail={"reason": "event_not_found"})

    existing = db.execute(
        select(Reaction).where(
            Reaction.user_id == user_id,
            Reaction.feed_event_id == event_id,
            Reaction.reaction_type == rtype,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"event_id": event_id, "reaction_type": rtype, "created": False}

    db.add(Reaction(user_id=user_id, feed_event_id=event_id, reaction_type=rtype))
    try:
        db.commit()
    except IntegrityError:
        # Lost a race on the unique (user,event,type) constraint — already present.
        db.rollback()
        return {"event_id": event_id, "reaction_type": rtype, "created": False}
    return {"event_id": event_id, "reaction_type": rtype, "created": True}


@router.delete("/feed/{event_id}/react/{reaction_type}")
def unreact(
    event_id: int,
    reaction_type: str,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> dict:
    """Remove the current user's reaction of the given type from a feed event."""
    existing = db.execute(
        select(Reaction).where(
            Reaction.user_id == user_id,
            Reaction.feed_event_id == event_id,
            Reaction.reaction_type == reaction_type,
        )
    ).scalar_one_or_none()
    if existing is None:
        raise HTTPException(status_code=404, detail={"reason": "reaction_not_found"})
    db.delete(existing)
    db.commit()
    return {"event_id": event_id, "reaction_type": reaction_type, "removed": True}
