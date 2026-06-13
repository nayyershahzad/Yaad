"""
otp.py — passwordless email OTP over Resend, state in Redis.

- send_otp(email): make a 6-digit code, store it (TTL) + reset the attempt
  counter, email it via Resend.
- verify(email, code): constant-ish check with a brute-force guard — after
  OTP_MAX_ATTEMPTS wrong tries the code is invalidated.

Redis (REDIS_URL, db 5) is the same instance ratelimit.py uses. Resend is called
directly over its REST API (httpx), mirroring /opt/nexus/lib/email.ts.
"""
from __future__ import annotations

import os
import secrets
import logging

import httpx
import redis.asyncio as aioredis

log = logging.getLogger(__name__)

REDIS_URL        = os.getenv("REDIS_URL", "redis://localhost:6379/0")
OTP_TTL_SECONDS  = int(os.getenv("OTP_TTL_SECONDS", "600"))
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
RESEND_API_KEY   = os.getenv("RESEND_API_KEY", "")
RESEND_FROM      = os.getenv("RESEND_FROM", "noreply@yaad.engstech.com")

_redis = None


def _r():
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def _code_key(email: str) -> str:
    return f"otp:{email.strip().lower()}"


def _attempts_key(email: str) -> str:
    return f"otp_attempts:{email.strip().lower()}"


def generate() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


async def send_otp(email: str) -> None:
    """Create + store an OTP and email it. Raises if Resend isn't configured."""
    if not RESEND_API_KEY or RESEND_API_KEY.startswith(("XXXX", "re_placeholder")):
        raise RuntimeError("RESEND_API_KEY not configured")

    code = generate()
    r = _r()
    await r.set(_code_key(email), code, ex=OTP_TTL_SECONDS)
    await r.delete(_attempts_key(email))

    mins = OTP_TTL_SECONDS // 60
    html = (
        f"<div style='font-family:sans-serif'>"
        f"<h2>Your Yaad code</h2>"
        f"<p style='font-size:28px;letter-spacing:4px'><b>{code}</b></p>"
        f"<p>It expires in {mins} minutes. If you didn't request this, ignore it.</p></div>"
    )
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": RESEND_FROM, "to": email, "subject": "Your Yaad sign-in code", "html": html},
        )
        resp.raise_for_status()
    log.info("[otp] sent to %s (resend id ok)", email)


async def verify(email: str, code: str) -> bool:
    """True iff `code` matches the stored OTP and the attempt budget isn't blown.
    Consumes the code on success; locks the code after OTP_MAX_ATTEMPTS failures."""
    r = _r()
    attempts = await r.incr(_attempts_key(email))
    if attempts == 1:
        await r.expire(_attempts_key(email), OTP_TTL_SECONDS)
    if attempts > OTP_MAX_ATTEMPTS:
        await r.delete(_code_key(email))  # too many tries -> burn the code
        return False

    stored = await r.get(_code_key(email))
    if stored and secrets.compare_digest(stored, str(code).strip()):
        await r.delete(_code_key(email), _attempts_key(email))
        return True
    return False
