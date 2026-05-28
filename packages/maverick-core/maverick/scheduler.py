"""Cron-style scheduler helper for the job queue.

Computes the next run time for a 5-field cron expression
(``minute hour day-of-month month day-of-week``) without dragging in
a cron dependency. Supports ``*``, ``*/n`` steps, ``a-b`` ranges,
``a,b,c`` lists, and named months/weekdays.

Pairs with :mod:`maverick.job_queue`: ``schedule_cron`` enqueues a
job at the next matching time; a worker that re-schedules after each
run gives you a recurring task.

This is intentionally minimal — no seconds field, no ``@reboot``, no
timezone math beyond the caller's ``now`` (pass a UTC timestamp for
UTC scheduling). Good enough for "every weekday at 9am" without a
dep.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Optional

log = logging.getLogger(__name__)


_MONTHS = {
    m: i for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"], start=1)
}
_DOW = {
    d: i for i, d in enumerate(
        ["sun", "mon", "tue", "wed", "thu", "fri", "sat"])
}


class CronError(ValueError):
    """Raised on a malformed cron expression."""


def _parse_field(field: str, lo: int, hi: int, names: dict | None = None) -> set[int]:
    out: set[int] = set()
    for part in field.split(","):
        part = part.strip().lower()
        if not part:
            continue
        step = 1
        has_step = False
        if "/" in part:
            base, _, step_s = part.partition("/")
            try:
                step = int(step_s)
            except ValueError as e:
                raise CronError(f"bad step in {field!r}") from e
            if step <= 0:
                raise CronError(f"step must be > 0 in {field!r}")
            has_step = True
            part = base or "*"
        if part == "*":
            rng = range(lo, hi + 1)
        elif "-" in part:
            a_s, _, b_s = part.partition("-")
            a = _resolve(a_s, names)
            b = _resolve(b_s, names)
            if a > b:
                raise CronError(f"range {part!r} reversed")
            rng = range(a, b + 1)
        else:
            v = _resolve(part, names)
            # `N/step` (single start + step) runs from N up to the field
            # max, matching cron: '5/15' on minutes -> 5,20,35,50. Without
            # a step, a bare N is just that single value.
            rng = range(v, hi + 1) if has_step else range(v, v + 1)
        for i, val in enumerate(rng):
            if i % step == 0:
                if not (lo <= val <= hi):
                    raise CronError(f"value {val} out of [{lo},{hi}] in {field!r}")
                out.add(val)
    if not out:
        raise CronError(f"empty field {field!r}")
    return out


def _resolve(token: str, names: dict | None) -> int:
    token = token.strip().lower()
    if names and token in names:
        return names[token]
    try:
        return int(token)
    except ValueError as e:
        raise CronError(f"bad token {token!r}") from e


def parse_cron(expr: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    fields = expr.split()
    if len(fields) != 5:
        raise CronError(
            f"cron needs 5 fields (min hour dom mon dow), got {len(fields)}"
        )
    minute = _parse_field(fields[0], 0, 59)
    hour = _parse_field(fields[1], 0, 23)
    dom = _parse_field(fields[2], 1, 31)
    mon = _parse_field(fields[3], 1, 12, _MONTHS)
    # Allow 7 as a synonym for Sunday (both 0 and 7 are standard cron):
    # parse with hi=7 so '7' and ranges like '5-7' don't trip the bound
    # check, THEN fold 7 -> 0.
    dow = _parse_field(fields[4], 0, 7, _DOW)
    if 7 in dow:
        dow.discard(7)
        dow.add(0)
    return minute, hour, dom, mon, dow


def next_run(expr: str, *, after: Optional[float] = None) -> float:
    """Return the next epoch timestamp matching ``expr`` strictly after
    ``after`` (default: now). Searches up to ~4 years forward.

    Cron fields are matched in **UTC** — ``0 0 * * *`` fires at 00:00
    UTC, not host-local midnight. Pass a UTC epoch for ``after`` (the
    default uses the current UTC time). Day-of-month and day-of-week
    follow Vixie cron semantics: if BOTH are restricted (not ``*``), a
    match on EITHER fires.
    """
    minute, hour, dom, mon, dow = parse_cron(expr)
    # Match cron fields in UTC. Using timezone-aware UTC datetimes makes
    # the "pass a UTC timestamp for UTC scheduling" contract literally
    # true AND removes DST hazards: there is no spring-forward/fall-back
    # in UTC, so the minute-by-minute walk below never lands on a
    # non-existent or doubled wall-clock minute.
    after_ts = (
        after if after is not None
        else _dt.datetime.now(_dt.timezone.utc).timestamp()
    )
    base = _dt.datetime.fromtimestamp(after_ts, tz=_dt.timezone.utc)
    # Round up to the next whole minute.
    t = base.replace(second=0, microsecond=0) + _dt.timedelta(minutes=1)

    dom_restricted = dom != set(range(1, 32))
    dow_restricted = dow != set(range(0, 7))

    def _day_matches(d: _dt.datetime) -> bool:
        if d.month not in mon:
            return False
        # cron weekday: Mon=0..Sun=6 in python; we use Sun=0..Sat=6.
        py_dow = (d.weekday() + 1) % 7  # Mon(0)->1 ... Sun(6)->0
        dom_ok = d.day in dom
        dow_ok = py_dow in dow
        if dom_restricted and dow_restricted:
            return dom_ok or dow_ok
        if dom_restricted:
            return dom_ok
        if dow_restricted:
            return dow_ok
        return True

    # Bound the search to ~4 years. Skip whole non-matching days in one
    # jump instead of walking 1440 dead minutes each — so an impossible
    # schedule ('0 0 30 2 *', Feb 30) costs ~1.5k day-steps, not ~2M
    # minute-steps.
    deadline = base + _dt.timedelta(days=366 * 4)
    while t <= deadline:
        if not _day_matches(t):
            t = (t + _dt.timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0)
            continue
        if t.hour in hour and t.minute in minute:
            return t.timestamp()
        t += _dt.timedelta(minutes=1)
    raise CronError(f"no match for {expr!r} within 4 years")


def schedule_cron(queue, expr: str, kind: str, payload: dict | None = None,
                  *, after: Optional[float] = None) -> tuple[int, float]:
    """Enqueue ``kind`` at the next time matching ``expr``.

    Returns ``(job_id, run_at)``. Pair with a worker that calls
    ``schedule_cron`` again after each run to make it recurring.
    """
    run_at = next_run(expr, after=after)
    job_id = queue.enqueue(kind, payload or {}, run_at=run_at)
    return job_id, run_at


__all__ = ["parse_cron", "next_run", "schedule_cron", "CronError"]
