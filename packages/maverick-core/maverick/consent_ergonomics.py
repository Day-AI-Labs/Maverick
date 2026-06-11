"""Consent ergonomics pass (roadmap: 2028 H2 Safety).

Better consent UX **without weakening the gate**. Three ergonomic wins layered on
top of :mod:`maverick.safety.consent` — never around it:

  * **Batch** related pending prompts into one grouped ask, so "delete these 8
    files" is one decision, not eight identical interruptions.
  * **Plain-language summary** of what's being requested (same friendly-verb
    style as the ``plain_language`` tool), so a non-technical operator
    understands the ask.
  * **Session memory**: remember "ask once per session for this exact
    ``(action, scope)``" in an injected, expiring session store. This is **not** a
    persistent grant — it lives only for the session, has a TTL, and is a cache
    of *a decision the human already made this session*, re-checked, never a way
    to skip a first decision.
  * **Dry-run preview**: render exactly what would be asked/auto-remembered
    without prompting anyone.

Safety invariants:
  * The real decision is always produced by ``consent.require_consent``; this
    module composes a callable around it and never returns a grant the consent
    primitive didn't make.
  * Session memory only *replays* a prior **granted** decision from this session
    (denials are never cached — a denied action is re-asked). It expires, and is
    scoped to the injected store the caller owns (clearing the store = forgetting
    everything), so it can't become a back-door persistent grant.

Deterministic and offline: the session store, clock, and the consent function are
all injectable, so grouping / summaries / expiry are unit-tested without a TTY,
the audit log, or the consent ledger.
"""
from __future__ import annotations

import time as _time
from dataclasses import dataclass, field

# Friendly phrasing for known destructive actions (mirrors the plain_language
# tool's verb map). Unknown actions fall back to a generic clause.
_ACTION_PHRASES: dict[str, str] = {
    "rm": "delete files",
    "rm-rf": "delete files and folders",
    "delete": "delete",
    "force-push": "force-push (overwrite remote history)",
    "mass-dm": "message many people at once",
    "mass-send": "send a message to many recipients",
    "mkfs": "format a filesystem (erasing it)",
    "dd": "write raw data to a disk",
    "drop-table": "drop a database table",
    "truncate": "empty a database table",
    "revoke": "revoke access",
}

# Default session-memory lifetime: short enough that a forgotten terminal doesn't
# carry a grant for hours, long enough to cover a working session.
_DEFAULT_TTL_S = 1800.0


@dataclass(frozen=True)
class PendingConsent:
    """One thing that needs consent, before any decision is made."""

    action: str
    scope: str = ""
    risk: str = "medium"
    detail: str = ""

    def key(self) -> tuple[str, str]:
        """The session-memory identity: exact (action, scope)."""
        return (self.action.strip(), self.scope.strip())


@dataclass
class ConsentGroup:
    """A set of pending prompts that share one (action, risk) and ask together."""

    action: str
    risk: str
    scopes: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.scopes)


class SessionConsentMemory:
    """An in-memory, expiring record of decisions made *this session*.

    Stores only granted (action, scope) keys with an expiry timestamp. Not
    persisted anywhere — instantiate one per session and drop it to forget. A
    caller may supply any mapping-like store and a clock for tests.
    """

    def __init__(self, *, ttl_s: float = _DEFAULT_TTL_S, clock=_time.time,
                 store: dict | None = None):
        self.ttl_s = float(ttl_s)
        self._clock = clock
        self._store: dict[tuple[str, str], float] = store if store is not None else {}

    def remember_grant(self, key: tuple[str, str]) -> None:
        self._store[key] = self._clock() + self.ttl_s

    def has_grant(self, key: tuple[str, str]) -> bool:
        """True iff a non-expired grant for ``key`` was made this session."""
        exp = self._store.get(key)
        if exp is None:
            return False
        if self._clock() >= exp:
            # Lazily drop the stale entry so the store doesn't grow unbounded.
            self._store.pop(key, None)
            return False
        return True

    def clear(self) -> None:
        self._store.clear()


def _phrase(action: str) -> str:
    return _ACTION_PHRASES.get(action.strip(), f"perform '{action.strip()}'")


def group_pending(pending: list[PendingConsent]) -> list[ConsentGroup]:
    """Batch pending prompts by ``(action, risk)``, preserving first-seen order."""
    groups: dict[tuple[str, str], ConsentGroup] = {}
    for p in pending or []:
        gk = (p.action.strip(), p.risk.strip() or "medium")
        g = groups.get(gk)
        if g is None:
            g = ConsentGroup(action=gk[0], risk=gk[1])
            groups[gk] = g
        if p.scope:
            g.scopes.append(p.scope.strip())
        if p.detail:
            g.details.append(p.detail.strip())
    return list(groups.values())


def summarize_group(group: ConsentGroup, *, max_scopes: int = 8) -> str:
    """A plain-language sentence describing one grouped ask."""
    verb = _phrase(group.action)
    n = group.count
    if n == 0:
        return f"Allow the agent to {verb}? (risk: {group.risk})"
    if n == 1:
        return f"Allow the agent to {verb}: {group.scopes[0]}? (risk: {group.risk})"
    shown = group.scopes[:max_scopes]
    more = f", and {n - len(shown)} more" if n > len(shown) else ""
    targets = ", ".join(shown) + more
    return (f"Allow the agent to {verb} on {n} item(s): {targets}? "
            f"(risk: {group.risk})")


def summarize_pending(pending: list[PendingConsent], *, max_scopes: int = 8) -> str:
    """Plain-language summary of *all* pending prompts, grouped."""
    groups = group_pending(pending)
    if not groups:
        return "No pending consent requests."
    lines = [f"{len(pending)} pending consent request(s) in {len(groups)} group(s):"]
    for g in groups:
        lines.append(f"  - {summarize_group(g, max_scopes=max_scopes)}")
    return "\n".join(lines)


def dry_run(pending: list[PendingConsent], memory: SessionConsentMemory) -> dict:
    """Preview what a real run would do — *without* prompting anyone.

    Splits the pending prompts into the ones already granted this session (would
    be auto-remembered, no prompt) and the ones that would actually ask, and
    renders the grouped plain-language summary for the latter. No consent call is
    made, nothing is decided.
    """
    remembered: list[PendingConsent] = []
    would_ask: list[PendingConsent] = []
    for p in pending or []:
        (remembered if memory.has_grant(p.key()) else would_ask).append(p)
    groups = group_pending(would_ask)
    return {
        "remembered_this_session": [
            {"action": p.action, "scope": p.scope} for p in remembered
        ],
        "would_ask": [
            {"action": g.action, "risk": g.risk, "count": g.count, "scopes": g.scopes}
            for g in groups
        ],
        "summary": summarize_pending(would_ask),
    }


def ask(
    pending: list[PendingConsent],
    memory: SessionConsentMemory,
    *,
    consent_fn=None,
    **consent_kwargs,
) -> dict:
    """Resolve pending prompts, composing with the consent primitive.

    For each prompt: if this session already granted its exact ``(action,
    scope)`` (a non-expired memory), the grant is replayed (no re-prompt).
    Otherwise the real ``consent_fn`` (default ``consent.require_consent``)
    decides; a granted decision is remembered for the session, a denial is not
    (so it will be asked again).

    Returns ``{"results": [...], "granted": [...], "denied": [...]}``. This never
    fabricates a grant — every non-replayed result comes straight from
    ``consent_fn``.
    """
    if consent_fn is None:
        from .safety.consent import require_consent as consent_fn  # noqa: N806

    results: list[dict] = []
    granted: list[tuple[str, str]] = []
    denied: list[tuple[str, str]] = []
    for p in pending or []:
        key = p.key()
        if memory.has_grant(key):
            results.append({"action": p.action, "scope": p.scope,
                            "granted": True, "source": "session-memory"})
            granted.append(key)
            continue
        decision = consent_fn(
            p.action, risk=p.risk, scope=p.scope or None,
            detail=p.detail or None, **consent_kwargs,
        )
        ok = bool(getattr(decision, "granted", False))
        results.append({
            "action": p.action, "scope": p.scope, "granted": ok,
            "source": getattr(decision, "source", "consent"),
        })
        if ok:
            memory.remember_grant(key)
            granted.append(key)
        else:
            denied.append(key)
    return {"results": results, "granted": granted, "denied": denied}


__all__ = [
    "PendingConsent",
    "ConsentGroup",
    "SessionConsentMemory",
    "group_pending",
    "summarize_group",
    "summarize_pending",
    "dry_run",
    "ask",
]
