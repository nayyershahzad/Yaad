# CLAUDE.md — Milestone: Monetization & Abuse Controls

> One focused milestone. Wire PayPro (Pakistan) v2 billing into Yaad, enforce the
> free-tier paywall, and harden the scan pipeline against cost-draining abuse.
> Deterministic-first, secrets in `.env`, every external contract verifiable.

## Product context (one line)
Yaad turns a snapshot of a printed textbook page into a swipeable deck of
flashcards/quizzes. OCR + card generation cost money per *unique* page, so the
business and the abuse surface both live at the "scan a page" boundary.

## This milestone — goal
A logged-in student can use **10 free sheets**, then is paywalled to a **200 PKR /
30-day** plan paid via PayPro. Payments are confirmed by re-querying PayPro (not by
trusting the callback). The scan endpoint cannot be used to run up OCR spend.

## Scope (build this)
- PayPro v2 client: `auth` (token caching) → `co` (create order) → `cm` (status).
- Free-tier quota that counts **unique** pages per user.
- Global OCR cache by image hash (pay to OCR each unique page once, ever).
- Per-user + per-IP rate limiting on scans (Redis fixed-window).
- `/billing/subscribe`, `/billing/status`, `/billing/paypro/ipn`.

## Non-goals (explicitly out)
- True silent card-on-file auto-debit (needs separate PayPro recurring onboarding;
  we use **renewal invoices** per cycle).
- The capture UI, OCR call, and card generation themselves (separate milestones;
  this milestone only gates them).
- Refunds / proration / coupons.

## Files
| File | Responsibility |
|---|---|
| `paypro.py` | v2 client: auth+token cache, `create_order`, `query_status` |
| `ratelimit.py` | generic Redis fixed-window limiter (no app imports) |
| `billing.py` | models, quota + dedup, rate-limit dep, subscribe/status/IPN routes |
| `.env.example` | every secret + every tunable (copy to `.env`, never commit `.env`) |

## Data model
- `subscriptions(user_id pk, status, current_period_end)` — `active` while period valid.
- `sheet_usage(user_id pk, used)` — free sheets consumed.
- `user_pages(user_id, content_hash)` — unique pages a user has scanned (quota basis).
- `extracted_pages(content_hash pk, extracted)` — global OCR cache.
- `payment_orders(order_number unique, user_id, amount, status, payment_url, ...)`.

## Pricing rules
- `FREE_SHEETS=10`, `PLAN_PRICE_PKR=200`, `PLAN_PERIOD_DAYS=30`.
- A "sheet" = a **unique** page for that user. Re-reading a scanned page is free.
- Active subscriber → unlimited (subject to the daily fair-use cap below).

## Abuse model → mitigation (the part that protects your wallet)
| Vector | Mitigation (in code) |
|---|---|
| Machine-gun the scan endpoint to burn OCR $ | `scan_rate_limit`: 8/min, 60/hr, 200/day per user |
| Many accounts from one device → 10 free each | per-IP 20/min cap + `SIGNUP_PER_IP_PER_DAY` (apply in signup); require WhatsApp/phone OTP at signup |
| Re-upload same page repeatedly | `user_pages` dedup → no quota burn, no OCR |
| Different users scanning the same page | `extracted_pages` cache → OCR cost paid once globally |
| Spoofed IPN granting free Pro | `PAYPRO_IPN_ALLOWED_IPS` allowlist **+** re-query `query_status` + amount match |
| Garbage/huge image uploads | enforce max upload size & content-type at the capture route |

## PayPro integration contract — VERIFY against Postman before prod
Postman: https://documenter.getpostman.com/view/14543555/2s847FutTd
1. **Auth** `POST /v2/ppro/auth` `{clientid, clientsecret}` → token in **response header** `token`.
2. **Create order** `POST /v2/ppro/co` header `token`, body `[{MerchantId}, {order...}]` → Click2Pay URL.
3. **Status** `POST /v2/ppro/cm` (path assumed) → order status for re-verification.
4. Field names that may differ per tenant are flagged `# VERIFY` in code:
   token location, checkout-URL field, IPN order-number/status fields, status path.
5. Sandbox `https://demo.paypro.com.pk` (amount = 1). Production base from PayPro at
   go-live (commonly `https://api.paypro.com.pk`) → set `PAYPRO_BASE_URL`, amount = 200.
6. Set the IPN/return URL in the PayPro portal = `PAYPRO_RETURN_URL`.

## Env (see `.env.example`)
Secrets: `PAYPRO_CLIENT_ID/SECRET/PASSWORD`, `*_API_KEY`, `DATABASE_URL`.
Tunables: `FREE_SHEETS`, `PLAN_PRICE_PKR`, `PLAN_PERIOD_DAYS`, `SCAN_PER_*`,
`PAYPRO_STRICT_VERIFY`, `PAYPRO_IPN_ALLOWED_IPS`.

## Run & test
```bash
cp .env.example .env          # fill the XXXX values
pip install fastapi httpx sqlalchemy "psycopg[binary]" redis uvicorn
python -m py_compile paypro.py billing.py ratelimit.py   # syntax gate

# create tables (dev): Base.metadata.create_all(engine)  — use Alembic for prod
# sandbox happy path:
#  1) exhaust 10 sheets -> /capture returns 402
#  2) POST /billing/subscribe -> open payment_url, pay 1 PKR in sandbox
#  3) PayPro IPN -> query_status confirms -> /billing/status shows active
```

## Definition of done
- 11th unique scan returns **402** with subscribe info; re-scans never 402.
- `subscribe` returns a live Click2Pay URL; order stored `pending`.
- IPN activates **only** after `query_status` confirms paid AND amount matches.
- Rapid scans return **429** with `Retry-After`; per-IP cap trips across accounts.
- No secret appears in source; all read from `.env`.
- `STRICT_VERIFY=true` never activates on an unverified callback.

## Wire-in TODOs (`# APP:` in code)
- Replace `get_db()` and `current_user_id()` with your real session/auth deps.
- Add `Depends(scan_rate_limit)` to the capture route; call `register_scan` after hashing.
- Enforce upload size/type on capture; apply `SIGNUP_PER_IP_PER_DAY` in signup; add OTP.

## Execution mode (autonomy)
- Within this milestone's Scope, build end-to-end without asking for confirmation.
- Precedence on any conflict: verified contract (LeadKar/Engs_Tech client)
  > CLAUDE.md seed values > model guesses. Silently correct `# VERIFY` placeholders
  to the verified values and note what changed.
- Stop and ask ONLY before: exposing/committing a real secret, switching
  PAYPRO_BASE_URL to production, real-money actions beyond the 1 PKR sandbox test,
  or anything outside Scope/Non-goals.
- Otherwise: build, run, self-check against Definition of Done, report.
