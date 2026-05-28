"""Stripe tool — payments + subscriptions.

Read-mostly access to a Stripe account so the agent can answer
"how much did we make last month?", "is customer X's subscription
active?", "draft a refund for charge Y" — without leaking the
secret key into the prompt or letting the agent run destructive
operations by default.

Auth: ``STRIPE_SECRET_KEY`` (sk_* or rk_*). Restricted keys are
recommended (read-only access to charges/customers/subscriptions).

ops:
  - customer_get(customer_id)
  - customer_search(email)
  - charges(limit, customer)
  - subscriptions(customer)
  - refund_create(charge_id, amount_cents)   — gated; only fires when
    args.confirm == True. Without confirm it returns a preview.
  - balance()                                — current available balance
"""
from __future__ import annotations

import logging
import os
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


_STRIPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": [
                "customer_get", "customer_search", "charges",
                "subscriptions", "refund_create", "balance",
            ],
        },
        "customer_id": {"type": "string"},
        "email": {"type": "string"},
        "limit": {"type": "integer"},
        "charge_id": {"type": "string"},
        "amount_cents": {"type": "integer", "description": "Refund amount (cents). Omit for full refund."},
        "reason": {"type": "string", "enum": ["duplicate", "fraudulent", "requested_by_customer"]},
        "confirm": {"type": "boolean", "description": "Required true to actually refund."},
    },
    "required": ["op"],
}


_API = "https://api.stripe.com/v1"


def _key() -> str:
    k = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not k:
        raise RuntimeError("Stripe requires STRIPE_SECRET_KEY.")
    return k


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_key()}",
        "Content-Type": "application/x-www-form-urlencoded",
    }


def _get(path: str, params: dict | None = None) -> tuple[int, Any]:
    import httpx
    r = httpx.get(f"{_API}/{path}", headers=_headers(),
                  params=params or {}, timeout=30.0)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"error": r.text[:300]}


def _post(path: str, data: dict) -> tuple[int, Any]:
    import httpx
    r = httpx.post(f"{_API}/{path}", headers=_headers(),
                   data=data, timeout=30.0)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"error": r.text[:300]}


def _money(cents: int | str | None, currency: str = "usd") -> str:
    try:
        v = int(cents or 0)
    except (TypeError, ValueError):
        return "?"
    return f"{v/100:,.2f} {currency.upper()}"


def _op_customer_get(cid: str) -> str:
    code, data = _get(f"customers/{cid}")
    if code == 404:
        return f"customer {cid!r} not found"
    if code >= 400:
        return f"ERROR: customer_get ({code}): {data.get('error', {})}"
    return (
        f"{data.get('id')}  {data.get('email', '')}  {data.get('name', '')}\n"
        f"  created:  {data.get('created')}\n"
        f"  balance:  {_money(data.get('balance'), data.get('currency') or 'usd')}\n"
        f"  livemode: {data.get('livemode')}"
    )


def _op_customer_search(email: str) -> str:
    code, data = _get("customers/search", {"query": f"email:'{email}'"})
    if code >= 400:
        return f"ERROR: customer_search ({code}): {data.get('error', {})}"
    rows = data.get("data") or []
    if not rows:
        return "no matches"
    return "\n".join(
        f"  {r.get('id')}  {r.get('email', '')}  {r.get('name', '')}"
        for r in rows
    )


def _op_charges(limit: int, customer: str) -> str:
    params: dict = {"limit": limit}
    if customer:
        params["customer"] = customer
    code, data = _get("charges", params)
    if code >= 400:
        return f"ERROR: charges ({code}): {data.get('error', {})}"
    rows = data.get("data") or []
    if not rows:
        return "no charges"
    lines = []
    for r in rows:
        status = r.get("status", "?")
        refunded = " (REFUNDED)" if r.get("refunded") else ""
        lines.append(
            f"  {r.get('id')}  {status:>9}  "
            f"{_money(r.get('amount'), r.get('currency') or 'usd')}"
            f"  {r.get('description', '') or ''}{refunded}"
        )
    return "\n".join(lines)


def _op_subscriptions(customer: str) -> str:
    if not customer:
        return "ERROR: subscriptions requires customer"
    code, data = _get("subscriptions", {"customer": customer, "limit": 25})
    if code >= 400:
        return f"ERROR: subscriptions ({code}): {data.get('error', {})}"
    rows = data.get("data") or []
    if not rows:
        return f"no subscriptions for {customer}"
    lines = []
    for r in rows:
        items = ((r.get("items") or {}).get("data")) or []
        plan = ""
        if items:
            plan = (items[0].get("price") or {}).get("id", "")
        lines.append(
            f"  {r.get('id')}  status={r.get('status', '?')}  "
            f"plan={plan}  cancel_at_period_end={r.get('cancel_at_period_end')}"
        )
    return "\n".join(lines)


def _op_refund_create(charge_id: str, amount_cents: int, reason: str,
                      confirm: bool) -> str:
    if not charge_id:
        return "ERROR: refund_create requires charge_id"
    if not confirm:
        amt = f"${amount_cents/100:.2f}" if amount_cents else "FULL amount"
        return (
            f"DRY RUN: would refund {amt} on {charge_id}"
            f"{' reason=' + reason if reason else ''}. "
            "Re-run with confirm=true to actually issue the refund."
        )
    body: dict = {"charge": charge_id}
    if amount_cents:
        body["amount"] = amount_cents
    if reason:
        body["reason"] = reason
    code, data = _post("refunds", body)
    if code >= 400:
        return f"ERROR: refund_create ({code}): {data.get('error', {})}"
    return (
        f"refunded {data.get('id')}: "
        f"{_money(data.get('amount'), data.get('currency') or 'usd')} "
        f"on {data.get('charge')}"
    )


def _op_balance() -> str:
    code, data = _get("balance")
    if code >= 400:
        return f"ERROR: balance ({code}): {data.get('error', {})}"
    avail = data.get("available") or []
    pending = data.get("pending") or []
    out = ["available:"]
    for a in avail:
        out.append(f"  {_money(a.get('amount'), a.get('currency'))}")
    out.append("pending:")
    for p in pending:
        out.append(f"  {_money(p.get('amount'), p.get('currency'))}")
    return "\n".join(out)


def _run(args: dict[str, Any]) -> str:
    op = args.get("op")
    if not op:
        return "ERROR: op is required"
    try:
        import httpx  # noqa: F401
    except ImportError:
        return "ERROR: httpx not installed. Run: pip install 'maverick-agent[issue-trackers]'"
    try:
        if op == "customer_get":
            cid = (args.get("customer_id") or "").strip()
            if not cid:
                return "ERROR: customer_get requires customer_id"
            return _op_customer_get(cid)
        if op == "customer_search":
            email = (args.get("email") or "").strip()
            if not email:
                return "ERROR: customer_search requires email"
            return _op_customer_search(email)
        if op == "charges":
            return _op_charges(
                max(1, min(int(args.get("limit") or 25), 100)),
                (args.get("customer_id") or "").strip(),
            )
        if op == "subscriptions":
            return _op_subscriptions((args.get("customer_id") or "").strip())
        if op == "refund_create":
            return _op_refund_create(
                (args.get("charge_id") or "").strip(),
                int(args.get("amount_cents") or 0),
                (args.get("reason") or "").strip(),
                bool(args.get("confirm")),
            )
        if op == "balance":
            return _op_balance()
    except RuntimeError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: Stripe request failed: {type(e).__name__}: {e}"
    return f"ERROR: unknown op {op!r}"


def stripe_tool() -> Tool:
    return Tool(
        name="stripe",
        description=(
            "Stripe payments + subscriptions (mostly read-only). "
            "ops: customer_get, customer_search (by email), charges "
            "(optionally per-customer), subscriptions (per-customer), "
            "refund_create (DRY RUN unless confirm=true), balance. "
            "Auth: STRIPE_SECRET_KEY (use a restricted key)."
        ),
        input_schema=_STRIPE_SCHEMA,
        fn=_run,
    )
