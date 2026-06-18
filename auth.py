"""
auth.py — passwordless email-OTP auth: JWT issuance, the real current_user_id
dependency (replaces auth_stub), and the /auth routes.

Flow: request-otp (email) -> verify-otp (email+code) -> JWT. The JWT's `sub` is
the integer user id every M1/M2 table already keys on. Signup and login are the
same path: verify-otp get-or-creates the User.
"""
from __future__ import annotations

import os
import datetime as dt
import logging

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

import otp
import ratelimit
import db as db_module
from auth_models import User

log = logging.getLogger(__name__)

SECRET_KEY            = os.getenv("SECRET_KEY", "")
ALGORITHM             = "HS256"
ACCESS_TOKEN_TTL_DAYS = int(os.getenv("ACCESS_TOKEN_TTL_DAYS", "30"))
OTP_REQ_PER_EMAIL     = 5       # per 10 min (beta-relaxed)
OTP_REQ_WINDOW        = 600

_bearer = HTTPBearer(auto_error=False)


# ---- JWT ------------------------------------------------------------------
def create_access_token(user_id: int) -> str:
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY not configured")
    now = dt.datetime.now(dt.timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + dt.timedelta(days=ACCESS_TOKEN_TTL_DAYS)}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def current_user_id(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> int:
    """Real auth dependency. Replaces auth_stub.current_user_id. 401 on any
    missing/invalid/expired bearer token."""
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})


# ---- schemas --------------------------------------------------------------
class RequestOtpIn(BaseModel):
    email: EmailStr


class VerifyOtpIn(BaseModel):
    email: EmailStr
    code: str


# ---- routes ---------------------------------------------------------------
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/request-otp", status_code=status.HTTP_202_ACCEPTED)
async def request_otp(body: RequestOtpIn, request: Request) -> dict:
    """Email a one-time code. Anti-Sybil: per-IP daily cap + per-email cooldown.
    Always returns the same shape (no account enumeration)."""
    ip = ratelimit.client_ip(request)
    email = body.email.lower()
    await ratelimit.enforce(f"signup_ip:{ip}", ratelimit.SIGNUP_PER_IP_PER_DAY, 86_400)
    await ratelimit.enforce(f"otp_req:{email}", OTP_REQ_PER_EMAIL, OTP_REQ_WINDOW)
    try:
        await otp.send_otp(email)
    except Exception as e:
        log.error("[auth] OTP send failed for %s: %s", email, e)
        raise HTTPException(status_code=503, detail={"reason": "otp_send_failed"},
                            headers={"Retry-After": "30"})
    return {"sent": True, "email": email}


@router.post("/verify-otp")
async def verify_otp(body: VerifyOtpIn, db: Session = Depends(db_module.get_db)) -> dict:
    """Verify the code; get-or-create the user; issue a JWT."""
    email = body.email.lower()
    if not await otp.verify(email, body.code):
        raise HTTPException(status_code=400, detail={"reason": "invalid_or_expired_code"})

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        user = User(email=email)
        db.add(user)
        db.flush()
    user.last_login_at = dt.datetime.now(dt.timezone.utc)
    db.commit()

    return {"access_token": create_access_token(user.id), "token_type": "bearer", "user_id": user.id}


@router.get("/me")
def me(db: Session = Depends(db_module.get_db), user_id: int = Depends(current_user_id)) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": user.id, "email": user.email}
