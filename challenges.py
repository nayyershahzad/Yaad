"""
challenges.py — quiz Challenges API: create from a deck, join, attempt, leaderboard.

A Challenge wraps one of the creator's existing decks (referenced by the same
content_hash as content_models.PageContent) and opens it for competition. Each
ChallengeAttempt is one user's run; the leaderboard orders a challenge's attempts
by score desc (tie-break duration asc, then completed_at asc) via the
(challenge_id, score) composite index.

Sync SQLAlchemy + JWT bearer auth, mirroring main.py's /capture and /decks:
  - DB session via db.get_db (Depends)
  - auth via auth.current_user_id (Depends) — 401 on missing/invalid token

main.py registers this router (do NOT register here).
"""
from __future__ import annotations

import json
import logging
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session

import db as db_module
from auth import current_user_id
from billing import _now
from content_models import PageContent
from challenge_models import Challenge, ChallengeAttempt
from social_models import FeedEvent

log = logging.getLogger("yaad.challenges")

DEFAULT_SCORING_RULE: dict = {"points_per_correct": 10, "time_bonus": False}

router = APIRouter(prefix="/challenges", tags=["challenges"])


# --------------------------------------------------------------------------- schemas
class CreateChallengeIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    source_content_hash: str = Field(min_length=1, max_length=64)
    scoring_rule: dict | None = None
    starts_at: dt.datetime | None = None
    ends_at: dt.datetime | None = None


class ChallengeOut(BaseModel):
    id: int
    creator_user_id: int
    title: str
    description: str | None
    source_content_hash: str
    scoring_rule: dict
    status: str
    starts_at: dt.datetime | None
    ends_at: dt.datetime | None
    created_at: dt.datetime | None
    attempt_count: int


class AttemptIn(BaseModel):
    score: int | None = None
    num_correct: int = Field(ge=0)
    total_questions: int = Field(ge=0)
    duration_seconds: int | None = Field(default=None, ge=0)


class AttemptOut(BaseModel):
    id: int
    challenge_id: int
    user_id: int
    score: int
    num_correct: int
    total_questions: int
    duration_seconds: int | None
    completed_at: dt.datetime | None
    rank: int


class LeaderboardRow(BaseModel):
    rank: int
    user_id: int
    score: int
    num_correct: int
    duration_seconds: int | None
    completed_at: dt.datetime | None


# --------------------------------------------------------------------------- helpers
def _parse_scoring_rule(raw: str | None) -> dict:
    """Parse the stored scoring_rule_json, falling back to the default rule."""
    if not raw:
        return dict(DEFAULT_SCORING_RULE)
    try:
        rule = json.loads(raw)
        return rule if isinstance(rule, dict) else dict(DEFAULT_SCORING_RULE)
    except json.JSONDecodeError:
        return dict(DEFAULT_SCORING_RULE)


def _compute_score(rule: dict, num_correct: int, duration_seconds: int | None) -> int:
    """Server-side score from the challenge's rule.

    points_per_correct * num_correct, plus a simple time bonus when enabled: the
    faster the run, the larger the bonus (capped, never negative)."""
    ppc = int(rule.get("points_per_correct", DEFAULT_SCORING_RULE["points_per_correct"]))
    score = ppc * max(0, num_correct)
    if rule.get("time_bonus") and duration_seconds is not None:
        # Reward speed: full bonus at 0s, decaying to 0 by 5 min. Simple + bounded.
        bonus = max(0, 300 - int(duration_seconds))
        score += bonus
    return score


def _attempt_count(db: Session, challenge_id: int) -> int:
    return int(
        db.execute(
            select(func.count(ChallengeAttempt.id)).where(
                ChallengeAttempt.challenge_id == challenge_id
            )
        ).scalar_one()
    )


def _to_challenge_out(db: Session, ch: Challenge) -> ChallengeOut:
    return ChallengeOut(
        id=ch.id,
        creator_user_id=ch.creator_user_id,
        title=ch.title,
        description=ch.description,
        source_content_hash=ch.source_content_hash,
        scoring_rule=_parse_scoring_rule(ch.scoring_rule_json),
        status=ch.status,
        starts_at=ch.starts_at,
        ends_at=ch.ends_at,
        created_at=ch.created_at,
        attempt_count=_attempt_count(db, ch.id),
    )


# Leaderboard ordering: score desc, then fastest run, then earliest completion.
# Built once so the rank query (below) and the per-attempt rank stay consistent.
def _leaderboard_query(challenge_id: int):
    return (
        select(ChallengeAttempt)
        .where(ChallengeAttempt.challenge_id == challenge_id)
        .order_by(
            ChallengeAttempt.score.desc(),
            ChallengeAttempt.duration_seconds.asc(),
            ChallengeAttempt.completed_at.asc(),
        )
    )


def _rank_of(db: Session, attempt: ChallengeAttempt) -> int:
    """1-based rank of this attempt among the challenge's attempts, using the same
    ordering as the leaderboard (score desc, duration asc, completed_at asc).
    Counts attempts that strictly outrank it, +1.

    duration_seconds is nullable; a NULL duration sorts last among equal scores
    (treated as +inf) so it never spuriously outranks a timed run."""
    dur = attempt.duration_seconds
    same_score = ChallengeAttempt.score == attempt.score
    if dur is None:
        # This run is untimed (sorts last among equal scores): any timed run is
        # faster, and only other untimed runs tie on duration.
        faster = ChallengeAttempt.duration_seconds.isnot(None)
        same_dur = ChallengeAttempt.duration_seconds.is_(None)
    else:
        faster = (
            ChallengeAttempt.duration_seconds.isnot(None)
            & (ChallengeAttempt.duration_seconds < dur)
        )
        same_dur = ChallengeAttempt.duration_seconds == dur
    better = db.execute(
        select(func.count(ChallengeAttempt.id)).where(
            ChallengeAttempt.challenge_id == attempt.challenge_id,
            (
                (ChallengeAttempt.score > attempt.score)
                | (same_score & faster)
                | (same_score & same_dur & (ChallengeAttempt.completed_at < attempt.completed_at))
            ),
        )
    ).scalar_one()
    return int(better) + 1


# --------------------------------------------------------------------------- routes
@router.post("", response_model=ChallengeOut, status_code=status.HTTP_201_CREATED)
def create_challenge(
    body: CreateChallengeIn,
    db: Session = Depends(db_module.get_db),
    user_id: int = Depends(current_user_id),
) -> ChallengeOut:
    """Create an open challenge from a deck the current user has a generated quiz for.

    404 unless the referenced deck exists (PageContent keyed by content_hash)."""
    if db.get(PageContent, body.source_content_hash) is None:
        raise HTTPException(status_code=404, detail="Deck not found for that content_hash")

    rule = body.scoring_rule if body.scoring_rule is not None else dict(DEFAULT_SCORING_RULE)
    ch = Challenge(
        creator_user_id=user_id,
        title=body.title,
        description=body.description,
        source_content_hash=body.source_content_hash,
        scoring_rule_json=json.dumps(rule),
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        status="open",
    )
    db.add(ch)
    db.commit()
    log.info("[challenges] user %s created challenge %s", user_id, ch.id)
    return _to_challenge_out(db, ch)


@router.get("", response_model=list[ChallengeOut])
def list_challenges(
    db: Session = Depends(db_module.get_db),
    user_id: int = Depends(current_user_id),
) -> list[ChallengeOut]:
    """Joinable challenges: status 'open' and not past ends_at, newest first."""
    now = _now()
    rows = db.execute(
        select(Challenge)
        .where(
            Challenge.status == "open",
            (Challenge.ends_at.is_(None)) | (Challenge.ends_at > now),
        )
        .order_by(Challenge.created_at.desc())
    ).scalars().all()
    return [_to_challenge_out(db, ch) for ch in rows]


@router.get("/{challenge_id}", response_model=ChallengeOut)
def get_challenge(
    challenge_id: int,
    db: Session = Depends(db_module.get_db),
    user_id: int = Depends(current_user_id),
) -> ChallengeOut:
    ch = db.get(Challenge, challenge_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Challenge not found")
    return _to_challenge_out(db, ch)


@router.post("/{challenge_id}/attempt", response_model=AttemptOut, status_code=status.HTTP_201_CREATED)
def submit_attempt(
    challenge_id: int,
    body: AttemptIn,
    db: Session = Depends(db_module.get_db),
    user_id: int = Depends(current_user_id),
) -> AttemptOut:
    """Record the current user's run. Scores server-side from the challenge's rule
    when the client omits `score`, then emits a `completed_challenge` feed event."""
    ch = db.get(Challenge, challenge_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Challenge not found")

    rule = _parse_scoring_rule(ch.scoring_rule_json)
    score = body.score if body.score is not None else _compute_score(
        rule, body.num_correct, body.duration_seconds
    )

    attempt = ChallengeAttempt(
        challenge_id=challenge_id,
        user_id=user_id,
        score=score,
        num_correct=body.num_correct,
        total_questions=body.total_questions,
        duration_seconds=body.duration_seconds,
    )
    db.add(attempt)
    # Surface the completion in the social feed (ref_id = challenge id).
    db.add(FeedEvent(
        actor_user_id=user_id,
        event_type="completed_challenge",
        ref_id=challenge_id,
    ))
    db.commit()

    rank = _rank_of(db, attempt)
    log.info("[challenges] user %s attempted challenge %s score=%s rank=%s",
             user_id, challenge_id, score, rank)
    return AttemptOut(
        id=attempt.id,
        challenge_id=attempt.challenge_id,
        user_id=attempt.user_id,
        score=attempt.score,
        num_correct=attempt.num_correct,
        total_questions=attempt.total_questions,
        duration_seconds=attempt.duration_seconds,
        completed_at=attempt.completed_at,
        rank=rank,
    )


@router.get("/{challenge_id}/leaderboard", response_model=list[LeaderboardRow])
def leaderboard(
    challenge_id: int,
    db: Session = Depends(db_module.get_db),
    user_id: int = Depends(current_user_id),
) -> list[LeaderboardRow]:
    """Top ~50 attempts, ranked. 404 if the challenge doesn't exist."""
    if db.get(Challenge, challenge_id) is None:
        raise HTTPException(status_code=404, detail="Challenge not found")

    rows = db.execute(_leaderboard_query(challenge_id).limit(50)).scalars().all()
    return [
        LeaderboardRow(
            rank=i + 1,
            user_id=a.user_id,
            score=a.score,
            num_correct=a.num_correct,
            duration_seconds=a.duration_seconds,
            completed_at=a.completed_at,
        )
        for i, a in enumerate(rows)
    ]
