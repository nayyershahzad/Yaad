"""
main.py — Yaad billing/abuse milestone, runnable FastAPI app.

Mounts billing.router and wires the two `# APP:` placeholders to dev
implementations (SQLite session + header-based user id). The /scan route is a
DEV HARNESS that exercises ONLY the gate (rate-limit + quota + OCR-cache decision)
— it performs NO OCR and generates NO cards (those are out of scope per CLAUDE.md);
it exists so the Definition-of-Done checks (402 / 429 / re-scan-free) are testable.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, Request, UploadFile, File
from sqlalchemy.orm import Session

import billing
import db as db_module
from auth_stub import current_user_id

app = FastAPI(title="Yaad — Billing & Abuse Controls")

# Wire the `# APP:` placeholders without editing billing.py: override its
# get_db()/current_user_id() deps with the dev implementations.
app.dependency_overrides[billing.get_db] = db_module.get_db
app.dependency_overrides[billing.current_user_id] = current_user_id

app.include_router(billing.router)


@app.on_event("startup")
def _startup() -> None:
    db_module.create_all()  # dev only; prod uses Alembic


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/scan")
async def scan(
    request: Request,
    file: UploadFile = File(...),
    _rl: None = Depends(billing.scan_rate_limit),       # 429 on velocity abuse
    db: Session = Depends(db_module.get_db),
    user_id: int = Depends(current_user_id),
) -> dict:
    """DEV HARNESS gate only — no OCR, no cards. Mirrors the capture wiring in
    billing.py: rate-limit -> hash -> register_scan (402 when free quota spent)."""
    data = await file.read()
    content_hash = billing.compute_content_hash(data)
    info = billing.register_scan(db, user_id, content_hash)  # raises 402 if quota spent
    # Real capture route would run OCR here only when info["ocr_needed"], then gen cards.
    return {"content_hash": content_hash, **info}
