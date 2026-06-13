"""
content_models.py — page-level generated-deck cache.

PageContent stores the flashcards + quiz for a unique page, keyed by the same
content_hash as billing.ExtractedPage. A page is OCR'd once (ExtractedPage) AND
card-generated once (PageContent), then served to every user who scans it — the
cost guard against re-paying for identical pages.

Registered on billing.Base so db.create_all() picks it up.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from billing import Base, _now


class PageContent(Base):
    __tablename__ = "page_content"
    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    flashcards_json: Mapped[str] = mapped_column(Text, default="[]")
    quiz_json: Mapped[str] = mapped_column(Text, default="[]")
    model_used: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
