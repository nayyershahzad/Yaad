"""
dossiers.py — chapter dossiers: organize a user's scanned pages by subject/chapter,
serve combined decks, generate-on-first-access AI study notes, and suggest revision.

Sync SQLAlchemy + FastAPI, mirroring billing.py/social.py exactly:
  - DB session via `db_module.get_db` (sync `Session`).
  - Auth via `auth.current_user_id` (Bearer JWT -> integer user id).

A "dossier" is a (subject, chapter) bucket of the current user's UserPage rows.
Member pages are NOT duplicated: they are derived live from UserPage joined to
PageContent. The Dossier row only caches the generated chapter notes_md so we pay
the LLM once per chapter (same cost guard as PageContent/cards). Notes generation
reuses cards.generate_notes() — the same Groq-primary / Gemini-fallback path the
deck generator uses. On LLM failure we return notes_md=null + notes_error rather
than 500, so browsing a dossier never breaks because the model is down.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import db as db_module
import cards
from auth import current_user_id
from billing import UserPage, ExtractedPage, _now
from content_models import PageContent
from dossier_models import Dossier

log = logging.getLogger(__name__)

get_db = db_module.get_db

router = APIRouter(prefix="/dossiers", tags=["dossiers"])


# --------------------------------------------------------------------------- schemas
class ChapterSummary(BaseModel):
    chapter: str
    page_count: int
    flashcard_count: int
    quiz_count: int
    last_scanned_at: str | None
    has_notes: bool


class SubjectSummary(BaseModel):
    subject: str
    chapters: list[ChapterSummary]


class DossiersOut(BaseModel):
    subjects: list[SubjectSummary]


class DossierPage(BaseModel):
    content_hash: str
    page_no: int | None
    scanned_at: str | None
    flashcard_count: int
    quiz_count: int


class DossierDetailOut(BaseModel):
    subject: str
    chapter: str
    pages: list[DossierPage]
    flashcards: list[dict]
    quiz: list[dict]
    notes_md: str | None
    notes_generated_at: str | None
    notes_error: bool = False


class RevisionSuggestionOut(BaseModel):
    subject: str
    chapter: str
    content_hashes: list[str]
    quiz_count: int
    last_scanned_at: str | None
    prompt_text: str


# --------------------------------------------------------------------------- helpers
def _chapter_pages(db: Session, user_id: int, subject: str, chapter: str):
    """The user's UserPage rows for one chapter, ordered by page_no then scanned_at.
    NULL page_no sorts last. Returns list[UserPage]."""
    return db.execute(
        select(UserPage)
        .where(
            UserPage.user_id == user_id,
            UserPage.subject == subject,
            UserPage.chapter == chapter,
        )
        .order_by(
            UserPage.page_no.is_(None),  # False(0) before True(1): numbered pages first
            UserPage.page_no.asc(),
            UserPage.created_at.asc(),
        )
    ).scalars().all()


def _get_or_create_dossier(db: Session, user_id: int, subject: str, chapter: str) -> Dossier:
    d = db.execute(
        select(Dossier).where(
            Dossier.user_id == user_id,
            Dossier.subject == subject,
            Dossier.chapter == chapter,
        )
    ).scalar_one_or_none()
    if d is not None:
        return d
    d = Dossier(user_id=user_id, subject=subject, chapter=chapter)
    db.add(d)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race on the unique (user,subject,chapter) constraint.
        db.rollback()
        d = db.execute(
            select(Dossier).where(
                Dossier.user_id == user_id,
                Dossier.subject == subject,
                Dossier.chapter == chapter,
            )
        ).scalar_one()
    return d


async def _generate_and_cache_notes(db: Session, dossier: Dossier, pages: list[UserPage]) -> bool:
    """Generate chapter notes from the concatenated ExtractedPage text of the
    chapter's pages and cache them on the Dossier. Returns True on success.
    On LLM failure leaves notes_md as-is and returns False (caller surfaces a flag)."""
    hashes = [p.content_hash for p in pages]
    if hashes:
        eps = db.execute(
            select(ExtractedPage).where(ExtractedPage.content_hash.in_(hashes))
        ).scalars().all()
        text_by_hash = {ep.content_hash: (ep.extracted or "") for ep in eps}
    else:
        text_by_hash = {}
    # Concatenate in page order so notes read top-to-bottom.
    combined = "\n\n".join(text_by_hash.get(h, "") for h in hashes).strip()

    try:
        result = await cards.generate_notes(combined)
    except Exception as e:  # all providers failed
        log.warning("[dossiers] notes generation failed for %s/%s: %s",
                    dossier.subject, dossier.chapter, str(e)[:160])
        return False

    dossier.notes_md = result["notes_md"]
    dossier.notes_generated_at = _now()
    db.commit()
    return result["notes_md"] is not None


def _combined_deck(db: Session, pages: list[UserPage]) -> tuple[list[dict], list[dict]]:
    """Combined flashcards + quiz across the chapter's pages, in page order."""
    hashes = [p.content_hash for p in pages]
    if not hashes:
        return [], []
    rows = db.execute(
        select(PageContent).where(PageContent.content_hash.in_(hashes))
    ).scalars().all()
    pc_by_hash = {pc.content_hash: pc for pc in rows}
    flashcards: list[dict] = []
    quiz: list[dict] = []
    for h in hashes:
        pc = pc_by_hash.get(h)
        if pc is None:
            continue
        flashcards.extend(json.loads(pc.flashcards_json or "[]"))
        quiz.extend(json.loads(pc.quiz_json or "[]"))
    return flashcards, quiz


# --------------------------------------------------------------------------- routes
@router.get("", response_model=DossiersOut)
@router.get("/", response_model=DossiersOut, include_in_schema=False)
def list_dossiers(
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> DossiersOut:
    """The current user's tagged pages grouped subject -> chapter, with per-chapter
    page/flashcard/quiz counts, last scan time, and whether notes exist."""
    rows = db.execute(
        select(UserPage, PageContent)
        .join(PageContent, PageContent.content_hash == UserPage.content_hash, isouter=True)
        .where(
            UserPage.user_id == user_id,
            UserPage.subject.is_not(None),
            UserPage.chapter.is_not(None),
        )
    ).all()

    # Which (subject,chapter) dossiers already have notes.
    notes_rows = db.execute(
        select(Dossier.subject, Dossier.chapter).where(
            Dossier.user_id == user_id,
            Dossier.notes_md.is_not(None),
        )
    ).all()
    has_notes = {(s, c) for s, c in notes_rows}

    # Aggregate per (subject, chapter).
    agg: dict[tuple[str, str], dict] = {}
    for up, pc in rows:
        key = (up.subject, up.chapter)
        bucket = agg.setdefault(key, {
            "page_count": 0, "flashcard_count": 0, "quiz_count": 0, "last_scanned_at": None,
        })
        bucket["page_count"] += 1
        if pc is not None:
            bucket["flashcard_count"] += len(json.loads(pc.flashcards_json or "[]"))
            bucket["quiz_count"] += len(json.loads(pc.quiz_json or "[]"))
        if up.created_at is not None:
            cur = bucket["last_scanned_at"]
            if cur is None or up.created_at > cur:
                bucket["last_scanned_at"] = up.created_at

    # Group into subjects, sorted by subject then chapter.
    by_subject: dict[str, list[ChapterSummary]] = {}
    for (subject, chapter), b in agg.items():
        by_subject.setdefault(subject, []).append(ChapterSummary(
            chapter=chapter,
            page_count=b["page_count"],
            flashcard_count=b["flashcard_count"],
            quiz_count=b["quiz_count"],
            last_scanned_at=b["last_scanned_at"].isoformat() if b["last_scanned_at"] else None,
            has_notes=(subject, chapter) in has_notes,
        ))

    subjects = [
        SubjectSummary(subject=s, chapters=sorted(chs, key=lambda c: c.chapter.lower()))
        for s, chs in sorted(by_subject.items(), key=lambda kv: kv[0].lower())
    ]
    return DossiersOut(subjects=subjects)


@router.get("/revision-suggestion", response_model=RevisionSuggestionOut | None)
def revision_suggestion(
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> RevisionSuggestionOut | None:
    """Suggest a chapter to re-test: the one with the OLDEST last-scan that has a
    quiz. Returns null if the user has fewer than 2 tagged chapters."""
    rows = db.execute(
        select(UserPage, PageContent)
        .join(PageContent, PageContent.content_hash == UserPage.content_hash, isouter=True)
        .where(
            UserPage.user_id == user_id,
            UserPage.subject.is_not(None),
            UserPage.chapter.is_not(None),
        )
    ).all()

    agg: dict[tuple[str, str], dict] = {}
    for up, pc in rows:
        key = (up.subject, up.chapter)
        bucket = agg.setdefault(key, {"quiz_count": 0, "last_scanned_at": None, "hashes": []})
        bucket["hashes"].append(up.content_hash)
        if pc is not None:
            bucket["quiz_count"] += len(json.loads(pc.quiz_json or "[]"))
        if up.created_at is not None:
            cur = bucket["last_scanned_at"]
            if cur is None or up.created_at > cur:
                bucket["last_scanned_at"] = up.created_at

    if len(agg) < 2:
        return None

    # Candidates: chapters that have at least one quiz question.
    candidates = [(k, v) for k, v in agg.items() if v["quiz_count"] > 0]
    if not candidates:
        return None

    # Oldest last-scan first (None sorts as very old / front).
    def _sort_key(item):
        ts = item[1]["last_scanned_at"]
        # None -> treat as oldest so an unscanned-yet-tagged chapter surfaces first
        return (ts is not None, ts)

    (subject, chapter), v = sorted(candidates, key=_sort_key)[0]
    return RevisionSuggestionOut(
        subject=subject,
        chapter=chapter,
        content_hashes=v["hashes"],
        quiz_count=v["quiz_count"],
        last_scanned_at=v["last_scanned_at"].isoformat() if v["last_scanned_at"] else None,
        prompt_text=f"Time to revise {chapter} of {subject}!",
    )


@router.get("/{subject}/{chapter}", response_model=DossierDetailOut)
async def get_dossier(
    subject: str,
    chapter: str,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> DossierDetailOut:
    """Dossier detail: member pages (ordered), the combined deck across the chapter,
    and the cached chapter notes. Generates notes on first access if missing."""
    pages = _chapter_pages(db, user_id, subject, chapter)
    if not pages:
        raise HTTPException(status_code=404, detail={"reason": "dossier_not_found"})

    flashcards, quiz = _combined_deck(db, pages)

    dossier = _get_or_create_dossier(db, user_id, subject, chapter)
    notes_error = False
    if dossier.notes_md is None:
        ok = await _generate_and_cache_notes(db, dossier, pages)
        notes_error = not ok

    page_hashes = {p.content_hash for p in pages}
    pc_rows = db.execute(
        select(PageContent).where(PageContent.content_hash.in_(list(page_hashes)))
    ).scalars().all() if page_hashes else []
    counts = {
        pc.content_hash: (len(json.loads(pc.flashcards_json or "[]")),
                          len(json.loads(pc.quiz_json or "[]")))
        for pc in pc_rows
    }

    out_pages = [
        DossierPage(
            content_hash=p.content_hash,
            page_no=p.page_no,
            scanned_at=p.created_at.isoformat() if p.created_at else None,
            flashcard_count=counts.get(p.content_hash, (0, 0))[0],
            quiz_count=counts.get(p.content_hash, (0, 0))[1],
        )
        for p in pages
    ]

    return DossierDetailOut(
        subject=subject,
        chapter=chapter,
        pages=out_pages,
        flashcards=flashcards,
        quiz=quiz,
        notes_md=dossier.notes_md,
        notes_generated_at=dossier.notes_generated_at.isoformat() if dossier.notes_generated_at else None,
        notes_error=notes_error,
    )


@router.post("/{subject}/{chapter}/notes/regenerate", response_model=DossierDetailOut)
async def regenerate_notes(
    subject: str,
    chapter: str,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> DossierDetailOut:
    """Force-regenerate the chapter notes, then return the full dossier detail."""
    pages = _chapter_pages(db, user_id, subject, chapter)
    if not pages:
        raise HTTPException(status_code=404, detail={"reason": "dossier_not_found"})

    dossier = _get_or_create_dossier(db, user_id, subject, chapter)
    dossier.notes_md = None  # force regeneration even if cached
    dossier.notes_generated_at = None
    db.commit()

    ok = await _generate_and_cache_notes(db, dossier, pages)
    notes_error = not ok

    flashcards, quiz = _combined_deck(db, pages)

    page_hashes = {p.content_hash for p in pages}
    pc_rows = db.execute(
        select(PageContent).where(PageContent.content_hash.in_(list(page_hashes)))
    ).scalars().all() if page_hashes else []
    counts = {
        pc.content_hash: (len(json.loads(pc.flashcards_json or "[]")),
                          len(json.loads(pc.quiz_json or "[]")))
        for pc in pc_rows
    }

    out_pages = [
        DossierPage(
            content_hash=p.content_hash,
            page_no=p.page_no,
            scanned_at=p.created_at.isoformat() if p.created_at else None,
            flashcard_count=counts.get(p.content_hash, (0, 0))[0],
            quiz_count=counts.get(p.content_hash, (0, 0))[1],
        )
        for p in pages
    ]

    return DossierDetailOut(
        subject=subject,
        chapter=chapter,
        pages=out_pages,
        flashcards=flashcards,
        quiz=quiz,
        notes_md=dossier.notes_md,
        notes_generated_at=dossier.notes_generated_at.isoformat() if dossier.notes_generated_at else None,
        notes_error=notes_error,
    )
