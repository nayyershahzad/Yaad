"""
auth_stub.py — DEV-ONLY stand-in for the real auth dependency (`# APP:`).

current_user_id() reads an X-User-Id header (default 1) so the Run & test happy
path can act as different users without a real login. Replace with Yaad's actual
auth dependency in production — this milestone only *gates* behind it.
"""
from __future__ import annotations

from fastapi import Header


def current_user_id(x_user_id: int | None = Header(default=1)) -> int:
    return x_user_id if x_user_id is not None else 1
