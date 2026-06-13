"""
auth_models.py — the User identity table.

Passwordless: a user is just a verified email + an integer id. The id is what
every M1/M2 table already references as user_id, so real auth slots in without
touching the billing / page / deck schema.

Registered on billing.Base so db.create_all() picks it up.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from billing import Base, _now


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
