"""Metering → billing & entitlements.

:mod:`maverick.quotas` *meters* usage (per-principal, per-UTC-day dollars +
tokens in a tenant-scoped ledger). This module turns that meter into money and
gates features by plan:

  - **Rating + invoicing** — aggregate a tenant's ledger over a period into an
    :class:`Invoice` of :class:`LineItem`, rated by a :class:`RateCard`
    (pass-through provider cost + markup, or token-priced).
  - **Entitlements** — a plan → :class:`Entitlements` map (feature flags + soft
    limits) with :func:`entitled` / :func:`tenant_entitled` gating.

Pure and offline: rating is arithmetic over the ledger, so it unit-tests with an
in-memory ledger. Plans are config-overridable via ``[billing.plans]``; the
built-in defaults are the last-resort fallback.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .quotas import UsageLedger

_MILLION = 1_000_000.0


@dataclass(frozen=True)
class RateCard:
    """How recorded usage becomes a charge.

    If either token price is set, charge from tokens; otherwise pass the recorded
    provider dollars through with ``markup_pct`` applied. ``minimum_charge`` is a
    floor on the invoice total.
    """

    markup_pct: float = 0.0
    usd_per_million_input_tokens: float = 0.0
    usd_per_million_output_tokens: float = 0.0
    minimum_charge: float = 0.0
    currency: str = "USD"

    @property
    def token_priced(self) -> bool:
        return bool(self.usd_per_million_input_tokens or self.usd_per_million_output_tokens)

    def rate(self, dollars: float, in_tokens: int, out_tokens: int) -> float:
        if self.token_priced:
            charge = (
                (in_tokens / _MILLION) * self.usd_per_million_input_tokens
                + (out_tokens / _MILLION) * self.usd_per_million_output_tokens
            )
        else:
            charge = float(dollars) * (1.0 + self.markup_pct / 100.0)
        return round(max(0.0, charge), 6)


@dataclass(frozen=True)
class LineItem:
    principal: str
    day: str
    dollars: float
    in_tokens: int
    out_tokens: int
    charge: float

    def to_dict(self) -> dict:
        return {
            "principal": self.principal, "day": self.day, "dollars": self.dollars,
            "in_tokens": self.in_tokens, "out_tokens": self.out_tokens,
            "charge": self.charge,
        }


@dataclass(frozen=True)
class Invoice:
    tenant: str | None
    period_start: str
    period_end: str
    line_items: list[LineItem] = field(default_factory=list)
    subtotal: float = 0.0
    total: float = 0.0
    currency: str = "USD"

    def to_dict(self) -> dict:
        return {
            "tenant": self.tenant,
            "period_start": self.period_start, "period_end": self.period_end,
            "currency": self.currency,
            "subtotal": self.subtotal, "total": self.total,
            "line_items": [li.to_dict() for li in self.line_items],
        }


def _in_period(day: str, since: str | None, until: str | None) -> bool:
    # YYYY-MM-DD strings compare lexically the same as chronologically.
    if since and day < since:
        return False
    return not (until and day > until)


def ledger_for_tenant(tenant_id: str | None) -> UsageLedger:
    """A UsageLedger pointed at ``tenant_id``'s tenant-scoped ledger file."""
    from .paths import data_dir
    return UsageLedger(path=data_dir("usage", "ledger.json", tenant=tenant_id))


def rate_ledger(
    ledger: UsageLedger, card: RateCard, *,
    tenant: str | None = None, since: str | None = None, until: str | None = None,
) -> Invoice:
    """Aggregate a ledger over ``[since, until]`` (inclusive, YYYY-MM-DD) into an
    invoice. Both bounds optional (open-ended). Line items are sorted by
    ``(principal, day)`` for a stable statement."""
    data = ledger._load()  # noqa: SLF001 -- intentional read of the persisted tally
    items: list[LineItem] = []
    for principal in sorted(data):
        days = data.get(principal) or {}
        for day in sorted(days):
            if not _in_period(day, since, until):
                continue
            cell = days[day] or {}
            dollars = float(cell.get("dollars", 0.0))
            in_tok = int(cell.get("in_tokens", 0))
            out_tok = int(cell.get("out_tokens", 0))
            if dollars == 0 and in_tok == 0 and out_tok == 0:
                continue
            items.append(LineItem(
                principal=principal, day=day, dollars=round(dollars, 6),
                in_tokens=in_tok, out_tokens=out_tok,
                charge=card.rate(dollars, in_tok, out_tok),
            ))
    subtotal = round(sum(li.charge for li in items), 6)
    total = round(max(subtotal, card.minimum_charge), 6)
    return Invoice(
        tenant=tenant, period_start=since or "", period_end=until or "",
        line_items=items, subtotal=subtotal, total=total, currency=card.currency,
    )


def generate_invoice(
    tenant_id: str | None, card: RateCard, *,
    since: str | None = None, until: str | None = None,
) -> Invoice:
    """Rate a tenant's own ledger into an invoice for the period."""
    return rate_ledger(
        ledger_for_tenant(tenant_id), card, tenant=tenant_id, since=since, until=until,
    )


# --- Entitlements ------------------------------------------------------------

@dataclass(frozen=True)
class Entitlements:
    plan: str
    features: frozenset[str]
    max_daily_dollars: float = 0.0   # 0 = unlimited
    max_concurrent_goals: int = 0    # 0 = unlimited


# Last-resort defaults; operators override via ``[billing.plans]`` in config.
DEFAULT_PLANS: dict[str, Entitlements] = {
    "free": Entitlements("free", frozenset({"core"}), 5.0, 1),
    "pro": Entitlements("pro", frozenset({"core", "grpc", "channels"}), 100.0, 5),
    "enterprise": Entitlements(
        "enterprise",
        frozenset({"core", "grpc", "channels", "sso", "audit_export", "self_host"}),
        0.0, 0,
    ),
}


def entitlements_for(plan: str) -> Entitlements:
    """The entitlements for ``plan`` (config override or built-in default;
    unknown plans fall back to ``free``)."""
    try:
        from .config import load_config
        plans = (load_config() or {}).get("billing", {}).get("plans") or {}
        spec = plans.get(plan)
        if isinstance(spec, dict):
            return Entitlements(
                plan=plan,
                features=frozenset(str(f) for f in (spec.get("features") or [])),
                max_daily_dollars=float(spec.get("max_daily_dollars", 0) or 0),
                max_concurrent_goals=int(spec.get("max_concurrent_goals", 0) or 0),
            )
    except Exception:  # pragma: no cover -- config never blocks gating
        pass
    return DEFAULT_PLANS.get(plan, DEFAULT_PLANS["free"])


def entitled(plan: str, feature: str) -> bool:
    """Whether ``plan`` includes ``feature``."""
    return feature in entitlements_for(plan).features


def tenant_entitled(tenant_id: str, feature: str) -> bool:
    """Whether the tenant's registered plan includes ``feature``. Unknown
    tenants get the ``free`` entitlements."""
    from .tenant_registry import get_tenant
    rec = get_tenant(tenant_id)
    return entitled(rec.plan if rec else "free", feature)


__all__ = [
    "RateCard", "LineItem", "Invoice",
    "rate_ledger", "generate_invoice", "ledger_for_tenant",
    "Entitlements", "DEFAULT_PLANS", "entitlements_for", "entitled", "tenant_entitled",
]
