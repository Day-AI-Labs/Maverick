"""Per-goal rate limit on shield scans (roadmap: 2027 H2 safety).

A prompt-injected loop can make an agent call the shield on every iteration —
thousands of scans for one goal. When the Agent Shield SDK is remote that is
real latency and real money; even locally it starves the loop. This module
puts a sliding-window cap on *scans per goal* so one runaway goal can't
hammer the chokepoint, while other goals' scans proceed untouched.

IMPORTANT — fail-open direction
===============================
When :meth:`ShieldRateLimiter.allow` returns ``False``, the caller must
**skip the shield scan and let the text through with a warning** — never
block the agent and never fail the tool call. The shield itself is a
fail-open chokepoint, not a hard dependency (CLAUDE.md rule 1); a rate
limiter wrapped around it inherits that direction. Throttling trades a
window of *unscanned* traffic for keeping the agent alive — the warning
log / ``on_throttle`` callback is what tells the operator that trade
happened. Do not invert this: a limiter that blocks turns a cost-control
knob into a denial-of-service of our own agent.

Usage shape::

    limiter = shield_rate_limit.shared()
    if limiter is None or limiter.allow(goal_id):
        verdict = shield.scan(text)          # normal path
    else:
        log.warning("shield scan skipped (rate limit) goal=%s", goal_id)
        verdict = None                       # treat as allowed

Throttle observability: ``on_throttle(goal_id, suppressed)`` fires on the
*first* suppressed call of a window (``suppressed == 1``, timely signal) and
then at most once per ``per_seconds`` per goal while the hammering continues,
each time carrying the number of calls suppressed since the previous alert —
so every suppressed call is reported in exactly one alert and a hot loop
can't turn the alert channel itself into spam. Callback exceptions are
swallowed (observers must never break the agent path).

Default OFF. Opt in via config (env wins over the ``[safety]`` table)::

    [safety]
    shield_rate_limit = "100/60"   # 100 scans per 60s sliding window, per goal

    # env override: MAVERICK_SHIELD_RATE_LIMIT="100/60" (or "off" to disable)

:func:`shared` returns the process-wide limiter built from that config (or
``None`` when unconfigured — the common case); :func:`reset_shared` drops it
for tests/config reload. A bad spec disables the limiter with a warning
(fail-open), it never raises into the agent loop. Stdlib-only, thread-safe,
clock injectable for deterministic tests.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable

log = logging.getLogger(__name__)

_ENV_VAR = "MAVERICK_SHIELD_RATE_LIMIT"
_OFF_WORDS = frozenset({"", "0", "off", "false", "no", "none", "disabled"})

_RATE_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+(?:\.\d+)?)\s*s?\s*$")


def parse_rate(spec: str) -> tuple[int, float]:
    """Parse ``"N/T"`` (or ``"N/Ts"``) into ``(max_calls, per_seconds)``.

    ``parse_rate("100/60") == (100, 60.0)``. Raises ``ValueError`` on
    anything else (non-string, zero/negative parts, junk) — the *config*
    path catches that and disables the limiter; direct callers get a
    loud, early failure.
    """
    if not isinstance(spec, str):
        raise ValueError(f"rate spec must be a string, got {type(spec).__name__}")
    m = _RATE_RE.match(spec)
    if not m:
        raise ValueError(f"invalid rate spec {spec!r} (expected 'N/T', e.g. '100/60')")
    n, t = int(m.group(1)), float(m.group(2))
    if n <= 0 or t <= 0:
        raise ValueError(f"rate spec {spec!r} must have positive calls and seconds")
    return n, t


class ShieldRateLimiter:
    """Sliding-window scan budget, counted independently per goal.

    ``allow(goal_id)`` is True while the goal has used fewer than
    ``max_calls`` scans in the trailing ``per_seconds``; hits exactly one
    window old have expired. Goals never affect each other. Thread-safe;
    ``clock`` defaults to ``time.monotonic`` and is injectable.
    """

    def __init__(self, max_calls: int, per_seconds: float, *,
                 clock: Callable[[], float] = time.monotonic,
                 on_throttle: Callable[[str, int], None] | None = None):
        if max_calls <= 0:
            raise ValueError("max_calls must be > 0")
        if per_seconds <= 0:
            raise ValueError("per_seconds must be > 0")
        self.max_calls = int(max_calls)
        self.per_seconds = float(per_seconds)
        self._clock = clock
        self._on_throttle = on_throttle
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}
        self._suppressed: dict[str, int] = {}    # since the last alert
        self._last_alert: dict[str, float] = {}

    def allow(self, goal_id: str | int) -> bool:
        """True = scan; False = SKIP the scan and pass the text through.

        The False branch is the fail-open path documented at module top:
        callers log a warning and continue, they do not block.
        """
        gid = str(goal_id)
        now = self._clock()
        fire: int | None = None
        with self._lock:
            window = self._hits.setdefault(gid, deque())
            cutoff = now - self.per_seconds
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) < self.max_calls:
                window.append(now)
                return True
            count = self._suppressed.get(gid, 0) + 1
            last = self._last_alert.get(gid)
            if last is None or now - last >= self.per_seconds:
                self._last_alert[gid] = now
                self._suppressed[gid] = 0
                fire = count
            else:
                self._suppressed[gid] = count
        if fire is not None:
            log.warning(
                "shield rate limit: goal %s exceeded %d/%.0fs; %d scan(s) "
                "suppressed (text passes through UNSCANNED)",
                gid, self.max_calls, self.per_seconds, fire,
            )
            if self._on_throttle is not None:
                try:
                    self._on_throttle(gid, fire)
                except Exception:  # observers must never break the agent path
                    log.exception("shield rate limit: on_throttle callback failed")
        return False


# --- process-wide instance from config ----------------------------------------

def configured_rate() -> tuple[int, float] | None:
    """``(max_calls, per_seconds)`` from env/config, or None (the default: OFF).

    ``MAVERICK_SHIELD_RATE_LIMIT`` wins over ``[safety] shield_rate_limit``;
    either may say "off". Unparseable specs disable with a warning —
    misconfiguration must not block scans OR the agent.
    """
    raw: object = os.environ.get(_ENV_VAR)
    if raw is None:
        try:
            from ..config import load_config
            raw = ((load_config() or {}).get("safety") or {}).get("shield_rate_limit")
        except Exception:  # pragma: no cover -- config never blocks the agent
            return None
    if raw is None:
        return None
    if str(raw).strip().lower() in _OFF_WORDS:
        return None
    try:
        return parse_rate(str(raw))
    except ValueError as e:
        log.warning("shield_rate_limit: ignoring bad spec %r (%s); limiter OFF", raw, e)
        return None


_shared: ShieldRateLimiter | None = None
_shared_built = False
_shared_lock = threading.Lock()


def shared() -> ShieldRateLimiter | None:
    """Process-wide limiter from config; None when the feature is off."""
    global _shared, _shared_built
    with _shared_lock:
        if not _shared_built:
            rate = configured_rate()
            if rate is not None:
                _shared = ShieldRateLimiter(rate[0], rate[1])
            _shared_built = True
        return _shared


def reset_shared() -> None:
    """Drop the process limiter (tests / config reload)."""
    global _shared, _shared_built
    with _shared_lock:
        _shared = None
        _shared_built = False


__all__ = [
    "ShieldRateLimiter", "parse_rate", "configured_rate",
    "shared", "reset_shared",
]
