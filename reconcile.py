"""
reconcile.py — PayPro payment reconciliation safety-net.

PayPro PK has no reliable server-to-server webhook, so a browser-return that never
fires would leave a paid order stuck 'pending'. This catches that: every run, take
'pending' orders older than a grace window and re-query PayPro's authoritative
status (ggosboi); activate the ones that actually paid. Run by yaad-reconcile.timer.

Safe by construction: a ggosboi error/500 (common for not-yet-paid orders) is
logged and skipped — never a false activation, never a false failure.
"""
from __future__ import annotations

import os
import asyncio
import logging
import datetime as dt

from sqlalchemy import select

import log_setup
import paypro
import billing
from db import SessionLocal

log_setup.configure()
log = logging.getLogger("yaad.reconcile")

GRACE_MINUTES = int(os.getenv("RECONCILE_GRACE_MINUTES", "10"))


async def reconcile_once() -> dict:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=GRACE_MINUTES)
    checked = activated = errors = 0
    db = SessionLocal()
    try:
        stale = db.execute(
            select(billing.PaymentOrder).where(
                billing.PaymentOrder.status == "pending",
                billing.PaymentOrder.created_at < cutoff,
            )
        ).scalars().all()

        for order in stale:
            checked += 1
            try:
                status = await paypro.query_status(order.order_number)
            except Exception as e:  # ggosboi 500 on a no-activity order is normal
                errors += 1
                log.info("reconcile: %s still unverifiable (%s)", order.order_number, str(e)[:80])
                continue
            if status["paid"] and (status.get("amount") is None or status["amount"] == order.amount):
                if billing.activate_subscription_for_paid_order(db, order):
                    activated += 1
                    log.warning("reconcile: ACTIVATED %s (user %s)", order.order_number, order.user_id)
    finally:
        db.close()

    result = {"checked": checked, "activated": activated, "errors": errors}
    log.info("reconcile run: %s", result)
    return result


if __name__ == "__main__":
    asyncio.run(reconcile_once())
