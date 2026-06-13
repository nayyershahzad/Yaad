"""
billing.py — subscription gating + PayPro checkout + IPN, on FastAPI + SQLAlchemy.

Pricing:
  * First FREE_SHEETS (10) processed pages are free, forever.
  * After that: PLAN_PRICE_PKR (200) per PLAN_PERIOD_DAYS (30) days.

Wire-in points for your app are marked `# APP:`.
"""
from __future__ import annotations

import os
import json
import time
import hashlib
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import String, Integer, DateTime, Text, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

import paypro
import ratelimit

FREE_SHEETS      = int(os.getenv("FREE_SHEETS", "10"))
PLAN_PRICE_PKR   = int(os.getenv("PLAN_PRICE_PKR", "200"))
PLAN_PERIOD_DAYS = int(os.getenv("PLAN_PERIOD_DAYS", "30"))
STRICT_VERIFY    = os.getenv("PAYPRO_STRICT_VERIFY", "true").lower() == "true"
ALLOWED_IPS = {ip.strip() for ip in os.getenv("PAYPRO_IPN_ALLOWED_IPS", "").split(",") if ip.strip()}


# --------------------------------------------------------------------------- models
class Base(DeclarativeBase):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Subscription(Base):
    __tablename__ = "subscriptions"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="free")  # free | active | expired
    current_period_end: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    def is_active(self) -> bool:
        return self.status == "active" and self.current_period_end is not None and self.current_period_end > _now()


class SheetUsage(Base):
    __tablename__ = "sheet_usage"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    used: Mapped[int] = mapped_column(Integer, default=0)


class PaymentOrder(Base):
    __tablename__ = "payment_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    order_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | paid | failed | expired
    paypro_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    paid_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserPage(Base):
    """One row per (user, unique page). Makes the free quota count UNIQUE pages,
    so re-reading a page the kid already scanned is free and doesn't burn a sheet."""
    __tablename__ = "user_pages"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ExtractedPage(Base):
    """Global OCR cache keyed by image hash. If a page was ever extracted, we
    never pay to OCR it again — the single biggest cost guard against scan abuse."""
    __tablename__ = "extracted_pages"
    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    extracted: Mapped[str | None] = mapped_column(Text, nullable=True)  # markdown/JSON
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


# --------------------------------------------------------------------------- app glue
# APP: replace these two with your real DB-session and auth dependencies.
def get_db() -> Session:  # pragma: no cover - placeholder
    raise NotImplementedError("Wire get_db() to your SQLAlchemy session factory")


def current_user_id() -> int:  # pragma: no cover - placeholder
    raise NotImplementedError("Wire current_user_id() to your auth dependency")


router = APIRouter(prefix="/billing", tags=["billing"])


# --------------------------------------------------------------------------- quota gate
def _sub(db: Session, user_id: int) -> Subscription:
    sub = db.get(Subscription, user_id)
    if sub is None:
        sub = Subscription(user_id=user_id, status="free")
        db.add(sub)
        db.flush()
    return sub


def sheets_remaining(db: Session, user_id: int) -> int | None:
    """None means unlimited (active subscriber)."""
    if _sub(db, user_id).is_active():
        return None
    usage = db.get(SheetUsage, user_id)
    used = usage.used if usage else 0
    return max(0, FREE_SHEETS - used)


def consume_sheet(db: Session, user_id: int) -> None:
    """Call once per processed page. Raises 402 when the free quota is spent."""
    if _sub(db, user_id).is_active():
        return
    usage = db.get(SheetUsage, user_id)
    if usage is None:
        usage = SheetUsage(user_id=user_id, used=0)
        db.add(usage)
        db.flush()
    if usage.used >= FREE_SHEETS:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "reason": "free_quota_exhausted",
                "free_sheets": FREE_SHEETS,
                "price_pkr": PLAN_PRICE_PKR,
                "period_days": PLAN_PERIOD_DAYS,
                "subscribe": "/billing/subscribe",
            },
        )
    usage.used += 1
    db.commit()


def compute_content_hash(image_bytes: bytes) -> str:
    """Exact-dup hash. Upgrade to a perceptual hash (imagehash.phash) later to also
    catch near-identical re-photos of the same page."""
    return hashlib.sha256(image_bytes).hexdigest()


def register_scan(db: Session, user_id: int, content_hash: str) -> dict:
    """Call once per scan, AFTER rate-limiting and hashing, BEFORE running OCR.

    - Re-scan of a page this user already did  -> free, consumes no quota, no OCR.
    - New page for this user                   -> enforce free-tier quota (402 if spent).
    - OCR only needed when the page isn't in the global cache.
    Returns {new_for_user, ocr_needed, cached}.
    """
    already = db.get(UserPage, (user_id, content_hash))
    cached = db.get(ExtractedPage, content_hash) is not None
    if already:
        return {"new_for_user": False, "ocr_needed": False, "cached": cached}

    consume_sheet(db, user_id)              # raises 402 when free quota is exhausted
    db.add(UserPage(user_id=user_id, content_hash=content_hash))
    db.commit()
    return {"new_for_user": True, "ocr_needed": not cached, "cached": cached}


async def scan_rate_limit(request: Request, user_id: int = Depends(current_user_id)) -> None:
    """Dependency for the capture/scan route. Throttles per-user and per-IP velocity
    so nobody can machine-gun the OCR pipeline. Raises 429 with Retry-After."""
    ip = ratelimit.client_ip(request)
    await ratelimit.enforce(f"user:{user_id}:m", ratelimit.SCAN_PER_MIN, 60)
    await ratelimit.enforce(f"user:{user_id}:h", ratelimit.SCAN_PER_HOUR, 3600)
    await ratelimit.enforce(f"user:{user_id}:d", ratelimit.SCAN_PER_DAY, 86_400)
    await ratelimit.enforce(f"ip:{ip}:m", ratelimit.IP_SCAN_PER_MIN, 60)


# Example wiring of the capture route (in your app):
#
#   @app.post("/capture")
#   async def capture(file: UploadFile,
#                     _rl=Depends(billing.scan_rate_limit),
#                     db=Depends(get_db),
#                     user_id=Depends(current_user_id)):
#       data = await file.read()
#       h = billing.compute_content_hash(data)
#       info = billing.register_scan(db, user_id, h)        # 402 if free quota spent
#       if info["ocr_needed"]:
#           text = await run_ocr(data)                      # Mistral/Gemini (costs money)
#           db.merge(ExtractedPage(content_hash=h, extracted=text)); db.commit()
#       else:
#           text = db.get(ExtractedPage, h).extracted       # cache hit, free
#       return await generate_cards(text)


# Use as a FastAPI dependency on your capture/process route:
#   @app.post("/capture")
#   def capture(_=Depends(quota_gate), ...):
def quota_gate(db: Session = Depends(get_db), user_id: int = Depends(current_user_id)) -> None:
    consume_sheet(db, user_id)


# --------------------------------------------------------------------------- routes
@router.get("/status")
def billing_status(db: Session = Depends(get_db), user_id: int = Depends(current_user_id)) -> dict:
    sub = _sub(db, user_id)
    remaining = sheets_remaining(db, user_id)
    return {
        "plan": "pro" if sub.is_active() else "free",
        "active": sub.is_active(),
        "period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "free_sheets_remaining": remaining,  # null = unlimited
        "price_pkr": PLAN_PRICE_PKR,
        "period_days": PLAN_PERIOD_DAYS,
    }


@router.post("/subscribe")
async def subscribe(
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> dict:
    """Create a PayPro invoice for one billing period and return the checkout URL."""
    order_number = f"YAAD-{user_id}-{int(time.time())}"

    # APP: pull real name/email/mobile from your user record.
    # PayPro validates CustomerName as alphabets-only, so the dev stub uses a
    # plain alphabetic name; the per-user identity lives in OrderNumber.
    result = await paypro.create_order(
        order_number=order_number,
        amount=PLAN_PRICE_PKR,
        customer_name="Yaad User",
        customer_email="",
        customer_mobile="",
        description=f"Yaad Pro — {PLAN_PERIOD_DAYS} days",
    )

    db.add(PaymentOrder(
        user_id=user_id,
        order_number=order_number,
        amount=PLAN_PRICE_PKR,
        status="pending",
        paypro_id=str(result.get("paypro_id") or ""),
        payment_url=result["payment_url"],
        raw=json.dumps(result.get("raw")),
    ))
    db.commit()

    return {"order_number": order_number, "payment_url": result["payment_url"], "amount": PLAN_PRICE_PKR}


@router.post("/paypro/ipn")
async def paypro_ipn(request: Request, db: Session = Depends(get_db)) -> dict:
    """PayPro posts here when a payment status changes. Configure this URL in the portal."""
    # 1) lock to PayPro's IPs if we know them
    if ALLOWED_IPS:
        client_ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                     or (request.client.host if request.client else ""))
        if client_ip not in ALLOWED_IPS:
            raise HTTPException(status_code=403, detail="IP not allowed")

    payload = await request.json()
    record = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(record, dict):
        raise HTTPException(status_code=400, detail="Bad IPN payload")

    # VERIFY field names against a real PayPro IPN sample.
    order_number = (record.get("OrderNumber") or record.get("order_number")
                    or record.get("OrderNo") or record.get("InvoiceNumber"))
    raw_status = str(record.get("Status") or record.get("OrderStatus")
                     or record.get("PaymentStatus") or "").strip().lower()

    if not order_number:
        raise HTTPException(status_code=400, detail="No order number in IPN")

    order = db.execute(
        select(PaymentOrder).where(PaymentOrder.order_number == str(order_number))
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Unknown order")

    paid = raw_status in {"paid", "completed", "success", "00", "1", "true"}

    # Don't trust the IPN body. Re-query PayPro for the authoritative status and
    # confirm the amount matches before granting anything.
    try:
        verified = await paypro.query_status(str(order_number))
        paid = verified["paid"]
        if verified.get("amount") is not None and verified["amount"] != order.amount:
            paid = False  # amount tampering / mismatch
    except Exception:
        # Status endpoint not confirmed yet, or PayPro unreachable.
        if STRICT_VERIFY:
            # Fail safe: acknowledge receipt but do NOT activate on an unverified IPN.
            return {"received": True, "order_number": order_number, "status": "unverified"}
        # Non-strict (bring-up only): fall back to the IPN-reported status.

    if paid and order.status != "paid":
        order.status = "paid"
        order.paid_at = _now()
        sub = _sub(db, order.user_id)
        base = sub.current_period_end if (sub.current_period_end and sub.current_period_end > _now()) else _now()
        sub.current_period_end = base + dt.timedelta(days=PLAN_PERIOD_DAYS)
        sub.status = "active"
        db.commit()
    elif not paid and raw_status:
        order.status = "failed"
        db.commit()

    return {"received": True, "order_number": order_number, "status": order.status}
