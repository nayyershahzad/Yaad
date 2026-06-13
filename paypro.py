"""
paypro.py — PayPro (Pakistan) API v2 client.

Reconciled against the VERIFIED Leadkar client on the same Engs_Tech account
(integrations/paypro.py, confirmed against PayPro's official v2 Postman collection
and the live demo API on 2026-06-04). Where this file's original seed guessed,
the verified contract wins. Changes from the seed are noted with `# WAS:`.

Verified v2 contract
  1. AUTH    POST {BASE}/v2/ppro/auth  {clientid, clientsecret}
             -> token in RESPONSE HEADER "token"
  2. CREATE  POST {BASE}/v2/ppro/co    header token, body [ {MerchantId}, {order} ]
             -> envelope [ {"Status":"00"}, {Click2Pay, PayProId, ...} ]
  3. STATUS  POST {BASE}/v2/ppro/ggosboi  header token, body {userName, Order_Id}
             -> envelope [ {"Status":"00"}, {OrderStatus, ...} ]

Envelope: every response is an array. Element 0 carries {"Status": "00"} meaning
the API CALL succeeded — this is NOT the payment state. The payment state lives in
element 1's "OrderStatus" and is "paid" only when actually paid.

All secrets come from the environment (.env); nothing is hardcoded.
"""
from __future__ import annotations

import os
import time
import asyncio
import datetime as dt
from dataclasses import dataclass
from typing import Any

import httpx

# --- config from env -------------------------------------------------------
# WAS: https://demo.paypro.com.pk  -> verified demo base is demoapi.paypro.com.pk
BASE_URL      = os.getenv("PAYPRO_BASE_URL", "https://demoapi.paypro.com.pk").rstrip("/")
MERCHANT_ID   = os.getenv("PAYPRO_MERCHANT_ID", "Engs_Tech")     # MerchantId for /co
USERNAME      = os.getenv("PAYPRO_USERNAME", MERCHANT_ID)        # userName for /ggosboi
CLIENT_ID     = os.getenv("PAYPRO_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("PAYPRO_CLIENT_SECRET", "")

AUTH_PATH         = "/v2/ppro/auth"
CREATE_ORDER_PATH = "/v2/ppro/co"
# WAS: /v2/ppro/cm  -> verified status endpoint is /v2/ppro/ggosboi
STATUS_PATH       = os.getenv("PAYPRO_STATUS_PATH", "/v2/ppro/ggosboi")

TOKEN_HEADER = "token"          # response header carrying the auth token

# Envelope (element 0).
F_ENVELOPE_STATUS = "Status"
OK_STATUS = "00"                # API call OK — NOT payment paid

# Create-order data fields (element 1).
F_CLICK2PAY = "Click2Pay"       # hosted checkout URL
F_PAYPRO_ID = "PayProId"        # PayPro's order id

# Status (ggosboi) data field + vocabulary (element 1).
F_ORDER_STATUS = "OrderStatus"
PAID_STATUSES   = {"paid"}
FAILED_STATUSES = {"blocked", "expired", "cancelled", "canceled"}

_TOKEN_TTL = int(os.getenv("PAYPRO_TOKEN_TTL_SECONDS", "1500"))  # no documented expiry; refresh-on-401 too


class PayProError(RuntimeError):
    pass


@dataclass
class _CachedToken:
    value: str
    expires_at: float


_token: _CachedToken | None = None
_lock = asyncio.Lock()


def _fmt(d: dt.date) -> str:
    return d.strftime("%d/%m/%Y")


def _envelope(payload: Any) -> tuple[bool, dict]:
    """PayPro responses are arrays: [{"Status":"00"}, {data...}].

    Returns (api_ok, data_dict). api_ok means the *call* succeeded (Status=="00");
    it says nothing about whether a payment is paid.
    """
    if isinstance(payload, list) and payload:
        head = payload[0] if isinstance(payload[0], dict) else {}
        api_ok = str(head.get(F_ENVELOPE_STATUS, "")) == OK_STATUS
        data = payload[1] if len(payload) > 1 and isinstance(payload[1], dict) else {}
        return api_ok, data
    if isinstance(payload, dict):
        return str(payload.get(F_ENVELOPE_STATUS, "")) == OK_STATUS, payload
    return False, {}


def classify_status(order_status: str | None) -> tuple[bool, bool]:
    """Map a PayPro OrderStatus to (is_paid, is_failed)."""
    s = (order_status or "").strip().lower()
    return (s in PAID_STATUSES, s in FAILED_STATUSES)


async def _authenticate(client: httpx.AsyncClient) -> str:
    """Get a fresh token. PayPro v2 returns it in the response header `token`."""
    if not CLIENT_ID or not CLIENT_SECRET:
        raise PayProError("PAYPRO_CLIENT_ID / PAYPRO_CLIENT_SECRET are not set")

    resp = await client.post(
        BASE_URL + AUTH_PATH,
        json={"clientid": CLIENT_ID, "clientsecret": CLIENT_SECRET},
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()

    token = resp.headers.get(TOKEN_HEADER) or resp.headers.get(TOKEN_HEADER.title())
    if not token:
        raise PayProError(f"No '{TOKEN_HEADER}' header in PayPro auth response (HTTP {resp.status_code})")
    return token


async def _get_token(client: httpx.AsyncClient, force: bool = False) -> str:
    global _token
    async with _lock:
        now = time.time()
        if not force and _token and _token.expires_at > now:
            return _token.value
        value = await _authenticate(client)
        _token = _CachedToken(value=value, expires_at=now + _TOKEN_TTL)
        return value


async def _authed_post(path: str, body: Any) -> Any:
    """Token-authenticated POST that refreshes the token once on 401/403."""
    async with httpx.AsyncClient(timeout=int(os.getenv("PAYPRO_TIMEOUT_SECONDS", "30"))) as client:
        token = await _get_token(client)
        resp = await client.post(
            BASE_URL + path,
            json=body,
            headers={"Content-Type": "application/json", TOKEN_HEADER: token},
        )
        if resp.status_code in (401, 403):
            token = await _get_token(client, force=True)
            resp = await client.post(
                BASE_URL + path,
                json=body,
                headers={"Content-Type": "application/json", TOKEN_HEADER: token},
            )
        resp.raise_for_status()
        return resp.json()


async def create_order(
    *,
    order_number: str,
    amount: int,
    customer_name: str,
    customer_email: str = "",
    customer_mobile: str = "",
    description: str = "Yaad subscription",
    due_in_days: int = 1,
    expire_after_seconds: int = 86_400,  # 24h checkout window
) -> dict:
    """Create a PayPro invoice. Returns {payment_url, paypro_id, status, raw}."""
    issue = dt.date.today()
    due = issue + dt.timedelta(days=due_in_days)

    order = {
        "OrderNumber": order_number,
        "OrderDueDate": _fmt(due),
        "OrderAmount": str(amount),         # verified: flat OrderAmount in PKR
        "OrderType": "Service",
        "IssueDate": _fmt(issue),
        "OrderExpireAfterSeconds": str(expire_after_seconds),
        "CustomerName": customer_name or "Customer",
        "CustomerMobile": customer_mobile or "",
        "CustomerEmail": customer_email or "",
        "CustomerAddress": "",
        "Description": description,
    }
    body = [{"MerchantId": MERCHANT_ID}, order]

    data = await _authed_post(CREATE_ORDER_PATH, body)
    api_ok, fields = _envelope(data)
    if not api_ok:
        raise PayProError(f"PayPro create-order call failed (Status != {OK_STATUS}): {data}")

    payment_url = fields.get(F_CLICK2PAY)
    paypro_id = fields.get(F_PAYPRO_ID)
    if not payment_url:
        raise PayProError(f"No {F_CLICK2PAY} in PayPro create-order response: {fields}")
    return {
        "payment_url": payment_url,
        "paypro_id": paypro_id,
        "status": fields.get(F_ORDER_STATUS),
        "raw": fields,
    }


def _amount_from(fields: dict) -> int | None:
    for k in ("OrderAmount", "Amount", "PaidAmount", "amount"):
        if k in fields and fields[k] is not None:
            try:
                return int(float(str(fields[k])))
            except (TypeError, ValueError):
                pass
    return None


async def query_status(order_number: str) -> dict:
    """Authoritative server-to-server payment check via /v2/ppro/ggosboi.

    PayPro keys this by the merchant OrderNumber (our order_number), passed as
    Order_Id, with userName = PAYPRO_USERNAME. Returns {paid, status, amount, raw}.
    `paid` is True ONLY when OrderStatus == "paid". Element 0's "00" envelope means
    the call succeeded, never that the payment is paid.

    Use this from the IPN handler — never trust the callback body alone.

    Observed sandbox behaviour (demoapi, 2026-06-13, matches Leadkar): ggosboi
    returns HTTP 500 for an order that has had no payment activity yet. We let that
    raise — the IPN handler treats a raised query_status as UNVERIFIED (does not
    activate, does not mark failed) under STRICT_VERIFY, which is the safe outcome.
    A genuinely settled order returns 200 with OrderStatus == "paid".
    """
    body = {"userName": USERNAME, "Order_Id": order_number}  # verified ggosboi shape

    data = await _authed_post(STATUS_PATH, body)
    api_ok, fields = _envelope(data)
    status_val = fields.get(F_ORDER_STATUS) if api_ok else None
    is_paid, _is_failed = classify_status(status_val)
    return {
        "paid": is_paid,
        "status": str(status_val) if status_val is not None else None,
        "amount": _amount_from(fields),
        "raw": fields,
    }
