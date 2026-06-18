"""
main.py — Yaad app: billing/abuse gate (M1) + capture->OCR->cards pipeline (M2).

Mounts billing.router and wires the two `# APP:` placeholders to dev
implementations (SQLite session + header-based user id).

/capture is the real product route: it runs behind the M1 gate (rate-limit ->
quota/402 -> dedup) and only spends OCR/LLM money on a page that has never been
processed before (ExtractedPage + PageContent are global per-page caches).
NOTE: /capture and /decks are NOT exposed by nginx (only /billing/* is public).
"""
from __future__ import annotations

import os
import json
import logging

import fitz  # PyMuPDF — PDF page split + render

from fastapi import Depends, FastAPI, Request, UploadFile, File, Form, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

import billing
import db as db_module
import ocr
import cards
import auth
import challenges
import social
import dossiers
import log_setup
from content_models import PageContent
from auth import current_user_id  # real JWT dependency (replaces auth_stub)

log_setup.configure()  # surface app INFO logs under uvicorn/journald

app = FastAPI(title="Yaad — Billing + Capture/OCR/Cards + Auth")

# Wire billing.py's `# APP:` placeholders to the real implementations.
app.dependency_overrides[billing.get_db] = db_module.get_db
app.dependency_overrides[billing.current_user_id] = current_user_id

app.include_router(billing.router)
app.include_router(auth.router)
app.include_router(challenges.router)
app.include_router(social.router)
app.include_router(dossiers.router)

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "8")) * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}

MAX_PDF_BYTES = int(os.getenv("MAX_PDF_MB", "20")) * 1024 * 1024
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "5"))
PDF_RENDER_DPI = int(os.getenv("PDF_RENDER_DPI", "150"))
# Born-digital vs scanned: a page whose embedded text is at least this many chars
# is treated as born-digital and used directly (no OCR cost). Mirrors the dossiers
# notes threshold so a stray header/page-number doesn't count as real text.
PDF_TEXT_MIN_CHARS = int(os.getenv("PDF_TEXT_MIN_CHARS", "40"))

log = logging.getLogger("yaad.capture")


@app.on_event("startup")
def _startup() -> None:
    db_module.create_all()  # dev only; prod uses Alembic


@app.get("/health")
def health() -> dict:
    return {"ok": True}


def _refund_scan(db: Session, user_id: int, content_hash: str, info: dict) -> None:
    """Undo what register_scan charged, so a failed OCR doesn't cost a free sheet.
    Only acts when the scan was new for this user (a re-scan charged nothing)."""
    if not info.get("new_for_user"):
        return
    up = db.get(billing.UserPage, (user_id, content_hash))
    if up is not None:
        db.delete(up)
    if not billing._sub(db, user_id).is_active():
        usage = db.get(billing.SheetUsage, user_id)
        if usage and usage.used > 0:
            usage.used -= 1
    db.commit()


@app.post("/capture")
async def capture(
    request: Request,
    file: UploadFile = File(...),
    subject: str | None = Form(None),
    chapter: str | None = Form(None),
    page_no: int | None = Form(None),
    _rl: None = Depends(billing.scan_rate_limit),     # 429 on velocity abuse
    db: Session = Depends(db_module.get_db),
    user_id: int = Depends(current_user_id),
) -> dict:
    """Photo of a textbook page -> a deck of flashcards + quiz.

    Flow: rate-limit -> validate -> hash -> register_scan (402 quota gate + dedup)
    -> OCR (only if page not cached) -> card-gen (only if deck not cached)."""
    # ---- validate upload (closes M1 TODO: enforce size/type on capture) ----
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"reason": "unsupported_type", "allowed": sorted(ALLOWED_IMAGE_TYPES)},
        )
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"reason": "file_too_large", "max_mb": MAX_UPLOAD_BYTES // (1024 * 1024)},
        )
    if not data:
        raise HTTPException(status_code=400, detail={"reason": "empty_file"})

    content_hash = billing.compute_content_hash(data)

    # 402 here if free quota is spent; no-ops quota for re-scans (dedup).
    info = billing.register_scan(db, user_id, content_hash)

    # ---- dossier tagging (per-user) ----
    # register_scan has created/found this user's UserPage row; tag it with any
    # supplied subject/chapter/page_no so /dossiers can group it. Re-scanning a
    # page with new tags re-files it (last write wins). Only set provided fields.
    if subject is not None or chapter is not None or page_no is not None:
        up = db.get(billing.UserPage, (user_id, content_hash))
        if up is not None:
            if subject is not None:
                up.subject = subject.strip() or None
            if chapter is not None:
                up.chapter = chapter.strip() or None
            if page_no is not None:
                up.page_no = page_no
            db.commit()

    # ---- OCR (cached per unique page) ----
    ep = db.get(billing.ExtractedPage, content_hash)
    ocr_cached = ep is not None
    if ep is None:
        try:
            text = await ocr.ocr_image(data, file.content_type)
        except ocr.OCRError as e:
            # All engines failed (e.g. Gemini quota + Tesseract error). The page
            # was NOT cached and quota WAS consumed by register_scan — refund it
            # so the user can retry without losing a free sheet.
            _refund_scan(db, user_id, content_hash, info)
            raise HTTPException(status_code=503, detail={"reason": "ocr_unavailable", "error": str(e)[:160]},
                                headers={"Retry-After": "60"}) from e
        db.merge(billing.ExtractedPage(content_hash=content_hash, extracted=text))
        db.commit()
    else:
        text = ep.extracted or ""

    # ---- cards (cached per unique page) ----
    pc = db.get(PageContent, content_hash)
    deck_cached = pc is not None
    if pc is None:
        try:
            deck = await cards.generate_cards(text)
        except Exception as e:
            raise HTTPException(status_code=503, detail={"reason": "cards_unavailable", "error": str(e)[:160]},
                                headers={"Retry-After": "60"}) from e
        db.merge(PageContent(
            content_hash=content_hash,
            flashcards_json=json.dumps(deck["flashcards"]),
            quiz_json=json.dumps(deck["quiz"]),
            model_used=deck.get("model_used"),
        ))
        db.commit()
        flashcards, quiz = deck["flashcards"], deck["quiz"]
    else:
        flashcards = json.loads(pc.flashcards_json)
        quiz = json.loads(pc.quiz_json)

    return {
        "content_hash": content_hash,
        "new_for_user": info["new_for_user"],
        "ocr_cached": ocr_cached,     # True => no OCR $ spent this call
        "deck_cached": deck_cached,   # True => no LLM $ spent this call
        "flashcards": flashcards,
        "quiz": quiz,
    }


async def _process_page(
    db: Session,
    user_id: int,
    png: bytes,
    txt: str,
    subject: str | None,
    chapter: str | None,
    page_no: int,
) -> dict:
    """Process one rendered PDF page through the same gate/OCR/cards path as
    /capture, then file it into the user's chapter. `txt` is the page's embedded
    (born-digital) text already extracted by the caller; when it's long enough we
    skip OCR entirely. Returns the per-page result dict, or raises to the caller
    which collects it as an error (the scan is refunded before re-raising).

    Commits once at the end (per-page commit, per the PDF route contract)."""
    content_hash = billing.compute_content_hash(png)

    # 402 gate + dedup (no-op quota while BETA_FREE). Creates this user's UserPage.
    info = billing.register_scan(db, user_id, content_hash)

    # ---- OCR (cached per unique page) ----
    ep = db.get(billing.ExtractedPage, content_hash)
    ocr_cached = ep is not None
    if ep is not None:
        text = ep.extracted or ""
    elif len(txt) >= PDF_TEXT_MIN_CHARS:
        # Born-digital page: use the embedded text directly, no OCR cost.
        text = txt
        db.merge(billing.ExtractedPage(content_hash=content_hash, extracted=text))
    else:
        # Scanned/image page: OCR the rendered PNG. On total OCR failure, refund
        # the scan and signal the caller to skip this page.
        try:
            text = await ocr.ocr_image(png, "image/png")
        except ocr.OCRError as e:
            _refund_scan(db, user_id, content_hash, info)
            raise _PageError("ocr_unavailable") from e
        db.merge(billing.ExtractedPage(content_hash=content_hash, extracted=text))

    # ---- cards (cached per unique page) ----
    pc = db.get(PageContent, content_hash)
    deck_cached = pc is not None
    if pc is not None:
        flashcards = json.loads(pc.flashcards_json)
        quiz = json.loads(pc.quiz_json)
    else:
        try:
            deck = await cards.generate_cards(text)
        except Exception as e:
            log.warning("[capture/pdf] card-gen failed for page_no=%s: %s", page_no, e)
            raise _PageError("cards_unavailable") from e
        db.merge(PageContent(
            content_hash=content_hash,
            flashcards_json=json.dumps(deck["flashcards"]),
            quiz_json=json.dumps(deck["quiz"]),
            model_used=deck.get("model_used"),
        ))
        flashcards, quiz = deck["flashcards"], deck["quiz"]

    # ---- tag this user's page into the named chapter ----
    up = db.get(billing.UserPage, (user_id, content_hash))
    if up is not None:
        up.subject = (subject.strip() or None) if subject is not None else None
        up.chapter = (chapter.strip() or None) if chapter is not None else None
        up.page_no = page_no

    db.commit()
    return {
        "content_hash": content_hash,
        "page_no": page_no,
        "flashcards": flashcards,
        "quiz": quiz,
        "ocr_cached": ocr_cached,
        "deck_cached": deck_cached,
    }


class _PageError(Exception):
    """A single PDF page failed (OCR or card-gen). Other pages still process."""
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@app.post("/capture/pdf")
async def capture_pdf(
    request: Request,
    file: UploadFile = File(...),
    subject: str | None = Form(None),
    chapter: str | None = Form(None),
    page_no: int = Form(1),
    _rl: None = Depends(billing.scan_rate_limit),     # 429 on velocity abuse
    db: Session = Depends(db_module.get_db),
    user_id: int = Depends(current_user_id),
) -> dict:
    """Upload a small PDF (<=MAX_PDF_PAGES pages); each page becomes a study deck
    filed into the named subject/chapter.

    Mirrors /capture per page: rate-limit -> validate -> render page to PNG ->
    hash -> register_scan (402 gate + dedup) -> text (born-digital embedded text
    if long enough, else OCR the PNG) -> card-gen (cached) -> tag into chapter.
    Pages are numbered page_no, page_no+1, ... A page whose OCR or card-gen fails
    is skipped and reported in `errors`; the rest still process. Commit per page."""
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"reason": "unsupported_type", "allowed": ["application/pdf"]},
        )
    data = await file.read()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"reason": "file_too_large", "max_mb": MAX_PDF_BYTES // (1024 * 1024)},
        )
    if not data:
        raise HTTPException(status_code=400, detail={"reason": "empty_file"})

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        raise HTTPException(status_code=400, detail={"reason": "bad_pdf", "error": str(e)[:160]}) from e

    try:
        n = doc.page_count
        if n > MAX_PDF_PAGES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"reason": "pdf_too_many_pages", "max": MAX_PDF_PAGES, "got": n},
            )
        if n == 0:
            raise HTTPException(status_code=400, detail={"reason": "empty_pdf"})

        start_page = page_no
        pages: list[dict] = []
        errors: list[dict] = []
        for i in range(n):
            this_page_no = start_page + i
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=PDF_RENDER_DPI)
            png = pix.tobytes("png")
            txt = (page.get_text() or "").strip()
            try:
                result = await _process_page(
                    db, user_id, png, txt, subject, chapter, this_page_no
                )
            except _PageError as pe:
                errors.append({"page_no": this_page_no, "reason": pe.reason})
                continue
            pages.append(result)
    finally:
        doc.close()

    return {
        "pdf": True,
        "count": n,
        "subject": subject,
        "chapter": chapter,
        "pages": pages,
        "errors": errors,
    }


@app.get("/decks")
def list_decks(
    db: Session = Depends(db_module.get_db),
    user_id: int = Depends(current_user_id),
) -> dict:
    """Summaries of the decks for pages THIS user has scanned (UserPage ⋈ PageContent).

    Empty pages (no flashcards and no quiz — blank/failed scans) are excluded so
    they don't clutter the library. Each deck carries a friendly `title` derived
    from its content plus the user's subject/chapter/page_no tags (null if untagged)."""
    rows = (
        db.query(billing.UserPage, PageContent)
        .join(PageContent, PageContent.content_hash == billing.UserPage.content_hash)
        .filter(billing.UserPage.user_id == user_id)
        .all()
    )
    decks = []
    for up, pc in rows:
        fc = json.loads(pc.flashcards_json or "[]")
        qz = json.loads(pc.quiz_json or "[]")
        if not fc and not qz:
            continue  # skip blank/failed scans — no study value
        title = (fc[0].get("front") if fc else None) or (qz[0].get("question") if qz else None) or "Untitled page"
        decks.append({
            "content_hash": up.content_hash,
            "title": title,
            "subject": up.subject,
            "chapter": up.chapter,
            "page_no": up.page_no,
            "scanned_at": up.created_at.isoformat() if up.created_at else None,
            "flashcards": len(fc),
            "quiz": len(qz),
        })
    return {"count": len(decks), "decks": decks}


class TagIn(BaseModel):
    subject: str | None = None
    chapter: str | None = None
    page_no: int | None = None


@app.post("/decks/{content_hash}/tag")
def tag_deck(
    content_hash: str,
    body: TagIn,
    db: Session = Depends(db_module.get_db),
    user_id: int = Depends(current_user_id),
) -> dict:
    """File a loose page into a subject/chapter (or re-file it) without re-uploading.
    Sets the provided tags on this user's UserPage; the page then groups under /dossiers."""
    up = db.get(billing.UserPage, (user_id, content_hash))
    if up is None:
        raise HTTPException(status_code=404, detail="Page not found for this user")
    if body.subject is not None:
        up.subject = body.subject.strip() or None
    if body.chapter is not None:
        up.chapter = body.chapter.strip() or None
    if body.page_no is not None:
        up.page_no = body.page_no
    db.commit()
    return {"content_hash": content_hash, "subject": up.subject, "chapter": up.chapter, "page_no": up.page_no}


@app.delete("/decks/{content_hash}")
def delete_deck(
    content_hash: str,
    db: Session = Depends(db_module.get_db),
    user_id: int = Depends(current_user_id),
) -> dict:
    """Remove a page from this user's library (housekeeping for junk/blank scans).
    Drops only the user's UserPage row; the global cached page content is untouched."""
    up = db.get(billing.UserPage, (user_id, content_hash))
    if up is not None:
        db.delete(up)
        db.commit()
    return {"deleted": True, "content_hash": content_hash}


@app.get("/decks/{content_hash}")
def get_deck(
    content_hash: str,
    db: Session = Depends(db_module.get_db),
    user_id: int = Depends(current_user_id),
) -> dict:
    """Full deck for one page. 404 unless this user has scanned it (don't leak
    other users' content by guessing a hash)."""
    if db.get(billing.UserPage, (user_id, content_hash)) is None:
        raise HTTPException(status_code=404, detail="Deck not found for this user")
    pc = db.get(PageContent, content_hash)
    if pc is None:
        raise HTTPException(status_code=404, detail="Deck not generated yet")
    return {
        "content_hash": content_hash,
        "flashcards": json.loads(pc.flashcards_json),
        "quiz": json.loads(pc.quiz_json),
        "model_used": pc.model_used,
    }
