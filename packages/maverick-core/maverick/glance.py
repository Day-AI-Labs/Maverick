"""Watch-glance payload (roadmap: 2027 H1 UX — "Apple Watch glance").

The data half of a watch complication/glance: one **tiny, fixed-shape**
payload sized for a watch face — active/today counts, today's spend, and the
last terminal result — computed in one cheap pass. The watchOS client
(``apps/watch-glance/``, SwiftUI scaffold) renders exactly this shape from
``GET /api/v1/glance``; anything fancier belongs on the phone/dashboard.

Pure over an injected world (+ the usage ledger for spend); every field is
bounded so the payload stays glance-sized no matter the history.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def _today_bounds(now: float) -> tuple[float, float]:
    d = datetime.fromtimestamp(now, tz=timezone.utc)
    start = d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    return start, start + 86400.0


def build_glance(world, *, now: float | None = None, owner: str | None = None) -> dict:
    """The fixed glance shape:

    ``{active, done_today, failed_today, spend_today, last_result, as_of}``
    """
    ts = float(now if now is not None else time.time())
    day_start, day_end = _today_bounds(ts)
    active = done_today = failed_today = 0
    last: tuple[float, str] | None = None
    try:
        goals = world.list_goals(owner=owner, limit=10_000)
    except Exception:
        goals = []
    for g in goals:
        status = getattr(g, "status", "")
        updated = float(getattr(g, "updated_at", 0) or 0)
        if status in ("active", "pending", "running"):
            active += 1
        if day_start <= updated < day_end:
            if status in ("done", "succeeded", "completed"):
                done_today += 1
            elif status in ("failed", "blocked"):
                failed_today += 1
        if status in ("done", "succeeded", "completed", "failed", "blocked"):
            if last is None or updated > last[0]:
                result = (getattr(g, "result", "") or
                          getattr(g, "title", "") or "")
                last = (updated, result)
    spend = 0.0
    try:
        from .quotas import UsageLedger, _today
        data = UsageLedger()._load()
        day = _today()
        if owner is None:
            spend = sum(float((days.get(day) or {}).get("dollars", 0.0))
                        for days in data.values() if isinstance(days, dict))
        else:
            spend = float((data.get(owner) or {}).get(day, {}).get("dollars", 0.0))
    except Exception as e:
        # Don't let a ledger read error read as a real $0.00 spend with no trace.
        log.debug("glance: spend lookup failed (%s); reporting $0.00", e)
    return {
        "active": active,
        "done_today": done_today,
        "failed_today": failed_today,
        "spend_today": round(spend, 2),
        "last_result": (last[1][:60] if last else ""),
        "as_of": int(ts),
    }


__all__ = ["build_glance"]
