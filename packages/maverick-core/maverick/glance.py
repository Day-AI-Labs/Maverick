"""At-a-glance fleet summary — a small, bounded payload over the world.

``build_glance(world)`` answers "what is the swarm doing right now?" in one
compact dict: the active runs, headline counts, and total spend. Every list
is bounded and every string truncated, so the payload stays cheap to build,
ship to a phone/watch, and cache. Strictly read-only; no secrets — only data
already stored in the world DB (titles, statuses, counters).
"""
from __future__ import annotations

import time
from typing import Any

MAX_ACTIVE = 25
_TITLE_CHARS = 120


def build_glance(world, *, now: float | None = None, max_active: int = MAX_ACTIVE) -> dict[str, Any]:
    """Bounded read-only summary of the world for glanceable UIs."""
    as_of = float(now if now is not None else time.time())
    max_active = max(1, min(int(max_active), MAX_ACTIVE))
    active = world.list_goals(status="active", limit=max_active, order="desc")
    spend = world.total_spend()
    return {
        "as_of": as_of,
        "active": [
            {
                "id": g.id,
                "title": (g.title or "")[:_TITLE_CHARS],
                "status": g.status,
                "updated_at": g.updated_at,
            }
            for g in active
        ],
        "counts": {
            "active": len(active),
            "pending_approvals": len(world.pending_approvals()),
            "open_questions": len(world.open_questions()),
        },
        "spend": {
            "dollars": round(float(spend.get("dollars") or 0.0), 4),
            "runs": int(spend.get("runs") or 0),
        },
    }
