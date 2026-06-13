"""
ratelimit.py — small Redis fixed-window rate limiter.

Generic and app-agnostic (no auth/db imports) so it can't create import cycles.
The scan-specific dependency lives in billing.py and calls enforce() here.
"""
from __future__ import annotations

import os
import time

from fastapi import HTTPException, Request

try:
    import redis.asyncio as aioredis
except Exception:  # redis optional at import time (e.g. during syntax checks)
    aioredis = None

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# scan limits (per authenticated user)
SCAN_PER_MIN  = int(os.getenv("SCAN_PER_MIN", "8"))
SCAN_PER_HOUR = int(os.getenv("SCAN_PER_HOUR", "60"))
SCAN_PER_DAY  = int(os.getenv("SCAN_PER_DAY", "200"))   # fair-use ceiling, even for subscribers
# per-IP limit catches multi-account / Sybil bursts from one device
IP_SCAN_PER_MIN = int(os.getenv("IP_SCAN_PER_MIN", "20"))
# anti-Sybil signup cap (apply in your auth/signup route)
SIGNUP_PER_IP_PER_DAY = int(os.getenv("SIGNUP_PER_IP_PER_DAY", "5"))

_redis = None


def _r():
    global _redis
    if aioredis is None:
        raise RuntimeError("redis is not installed")
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


async def hit(key: str, limit: int, window: int) -> tuple[bool, int]:
    """Fixed-window counter. Returns (allowed, retry_after_seconds)."""
    r = _r()
    bucket = int(time.time()) // window
    rk = f"rl:{key}:{window}:{bucket}"
    n = await r.incr(rk)
    if n == 1:
        await r.expire(rk, window)
    if n > limit:
        ttl = await r.ttl(rk)
        return False, max(1, ttl)
    return True, 0


async def enforce(key: str, limit: int, window: int) -> None:
    allowed, retry = await hit(key, limit, window)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"reason": "rate_limited", "retry_after": retry},
            headers={"Retry-After": str(retry)},
        )


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
