"""The persona inbox model: a domain-scoped view of what the fleet delivers.

Where ``/goals`` is one flat list of every run, this groups runs by the
*deliverable* their pack declares (a 13-week cash forecast, a CECL allowance)
and scopes them to the persona role that consumes them -- so an FP&A analyst
sees "my forecasts" and a risk officer sees "assessments awaiting my sign-off"
rather than the same undifferentiated stream.

Pure and presentation-only: the route gathers the pack contracts (specs) and
the recent runs per domain; this shapes them into the view model. A run is
"awaiting sign-off" when its pack declares a gate and the run has finished
(``done``) -- the human review the gate calls for hasn't been recorded yet.
The real approval linkage lands with the governed-handoff step; until then this
is the honest signal we can compute from a run's status.
"""
from __future__ import annotations

from typing import Any

_DONE = "done"


def persona_roles_for(principal: str | None) -> list[str]:
    """The persona consumer roles bound to a principal, from the ``[personas]``
    config table (``"user:alice" = ["fpa_analyst", "treasurer"]``), falling back
    to a ``default`` entry for single-user/no-auth deployments. ``[]`` when no
    binding exists -- the inbox then shows everything, as before.

    Distinct from the dashboard's RBAC role (admin/operator/viewer, which gates
    *actions*): this says which deliverables are *yours* to consume."""
    try:
        from maverick.config import load_config
        table = (load_config() or {}).get("personas") or {}
    except Exception:  # pragma: no cover -- config never blocks the inbox
        return []
    roles = table.get(principal) if principal else None
    if roles is None:
        roles = table.get("default")
    if isinstance(roles, str):
        roles = [roles]
    return [str(r) for r in roles] if isinstance(roles, list) else []


def _run_view(g: Any, gate: str | None, signoff: str | None) -> dict:
    """One run as the inbox shows it. ``awaiting`` = a gated deliverable that
    has finished and has no sign-off recorded yet, so it is sitting for its
    human review; once signed off (approved/rejected) it drops out."""
    status = getattr(g, "status", "") or ""
    return {
        "id": getattr(g, "id", None),
        "title": getattr(g, "title", "") or "",
        "status": status,
        "updated_at": getattr(g, "updated_at", 0) or 0,
        "signoff": signoff,
        "awaiting": bool(gate) and status == _DONE and not signoff,
    }


def build_inbox(specs: list[dict], runs_by_domain: dict[str, list],
                role: str | None = None,
                signoffs: dict[int, str] | None = None,
                mine: set[str] | None = None) -> dict:
    """Shape the persona inbox.

    ``specs`` are the packs that declare a deliverable (each a dict with
    ``domain``/``deliverable``/``consumers``/``cadence``/``gate``/``shape``/
    ``suite``); ``runs_by_domain`` maps a pack name to its recent runs (newest
    first). ``role`` scopes to deliverables that role consumes. ``signoffs``
    maps a goal id to its recorded decision, so a reviewed deliverable drops
    out of the awaiting queue. ``mine`` is the caller's own persona roles: when
    no explicit ``role`` is chosen, the inbox defaults to deliverables any of
    those roles consume (the "mine" view) -- so a logged-in analyst lands on
    their forecasts without picking a chip.

    Returns ``roles`` (every consumer role, for the filter), the selected
    ``role``, ``mine``/``showing_mine`` (the default-to-my-roles state),
    ``items`` (one per deliverable, runs attached, gated-and-finished floated to
    the top), and ``awaiting`` (the flat sign-off queue, newest first)."""
    signoffs = signoffs or {}
    roles = sorted({r for s in specs for r in s.get("consumers", [])})
    showing_mine = bool(mine) and not role
    if role:
        specs = [s for s in specs if role in s.get("consumers", [])]
    elif mine:
        specs = [s for s in specs if set(s.get("consumers", [])) & mine]

    items: list[dict] = []
    awaiting: list[dict] = []
    for s in specs:
        runs = [_run_view(g, s.get("gate"), signoffs.get(getattr(g, "id", None)))
                for g in runs_by_domain.get(s["domain"], [])]
        awaiting_count = 0
        for r in runs:
            if r["awaiting"]:
                awaiting_count += 1
                awaiting.append({**r, "deliverable": s["deliverable"],
                                 "domain": s["domain"], "gate": s.get("gate")})
        items.append({**s, "runs": runs, "latest": runs[0] if runs else None,
                      "awaiting_count": awaiting_count})

    # Deliverables that need a human float to the top; then alphabetical.
    items.sort(key=lambda it: (it["awaiting_count"] == 0, it["deliverable"].lower()))
    awaiting.sort(key=lambda r: r["updated_at"], reverse=True)
    return {"roles": roles, "role": role or "", "mine": sorted(mine or []),
            "showing_mine": showing_mine, "items": items, "awaiting": awaiting}


__all__ = ["build_inbox", "persona_roles_for"]
