"""Provider-level cost caps across all runs (roadmap: 2028 H1 safety).

:class:`maverick.budget.Budget` caps **one run**; :mod:`maverick.quotas` caps
a **principal** per day. Neither bounds what the deployment as a whole may
spend at a given *provider* — fifty perfectly-budgeted runs are still a
$250 Anthropic day nobody approved. This module is the third axis: a ceiling
per provider per UTC period (day or month), enforced at the LLM dispatch
path via :func:`enforce`.

Config (opt-in; nothing configured = no caps = behavior unchanged)::

    [budget]
    provider_caps_period = "day"        # "day" (default) | "month"

    [budget.provider_caps]
    anthropic = 50.0                    # dollars per period
    openai    = 20.0

``MAVERICK_PROVIDER_CAPS_PERIOD`` overrides the period knob (env wins, the
house convention). Config readers are fail-soft: an unreadable config means
no caps, never a crash.

The ledger (``data_dir("provider_spend.json")``) maps
``{period_key: {provider: dollars}}`` — period keys are ``YYYY-MM-DD`` (day)
or ``YYYY-MM`` (month), always UTC so the window doesn't shift with host
timezone/DST. Writes are atomic (unique temp file + ``os.replace``, 0600)
and the whole read-modify-write is serialized by an in-process lock **plus a
cross-process advisory flock** on a ``.lock`` sidecar, mirroring
:mod:`maverick.quotas`; the ledger reloads per call rather than caching, so
concurrent processes don't clobber each other's totals (without the flock two
processes both load the same total, both add, and the second ``os.replace``
wins -- dollars vanish from a *spend-cap* ledger and the deployment overspends
past the configured ceiling). Recording is fail-soft (accounting must not
take down the agent loop) — but :func:`enforce` itself is the cap, and a cap
that is configured and exceeded *raises*.

Clock is injectable everywhere (``now=`` epoch seconds) so rollover tests
are deterministic. Stdlib-only, pure library, nothing imports it by default.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .file_lock import cross_process_lock
from .paths import data_dir

log = logging.getLogger(__name__)

PERIOD_DAY = "day"
PERIOD_MONTH = "month"

_LEDGER_LOCK = threading.Lock()


class ProviderCapExceeded(Exception):
    """A provider's per-period spend ceiling has been reached."""

    def __init__(self, provider: str, spent: float, cap: float, period_key: str):
        super().__init__(
            f"provider {provider!r} has spent ${spent:.2f} of its "
            f"${cap:.2f} cap for {period_key}; refusing further calls. "
            f"Raise [budget.provider_caps] {provider} or wait for the next period."
        )
        self.provider = provider
        self.spent = spent
        self.cap = cap
        self.period_key = period_key


@dataclass(frozen=True)
class CapStatus:
    """One provider's standing against its cap. ``cap``/``remaining`` are
    ``None`` when no cap is configured (always allowed)."""

    allowed: bool
    spent: float
    cap: float | None
    remaining: float | None


def _canon(provider: str) -> str:
    return str(provider or "").strip().lower()


def _budget_cfg() -> dict:
    try:
        from .config import load_config
        return (load_config() or {}).get("budget") or {}
    except Exception:  # config must never crash the call path
        return {}


def caps_from_config() -> dict[str, float]:
    """``[budget.provider_caps]`` as ``{provider: dollars}``; fail-soft.

    Non-numeric and non-positive values are dropped (a zero/negative cap is
    a misconfiguration, not a "block everything" switch — that's what the
    killswitch is for).
    """
    raw = _budget_cfg().get("provider_caps")
    if not isinstance(raw, dict):
        return {}
    caps: dict[str, float] = {}
    for name, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if float(value) > 0:
            caps[_canon(name)] = float(value)
    return caps


def period_from_config() -> str:
    """``"day"`` (default) or ``"month"``; env wins; unrecognized -> day."""
    env = os.environ.get("MAVERICK_PROVIDER_CAPS_PERIOD", "").strip().lower()
    if env in (PERIOD_DAY, PERIOD_MONTH):
        return env
    val = str(_budget_cfg().get("provider_caps_period", PERIOD_DAY)).strip().lower()
    return val if val in (PERIOD_DAY, PERIOD_MONTH) else PERIOD_DAY


def period_key(now: float | None = None, period: str | None = None) -> str:
    """The UTC ledger key for ``now``: ``YYYY-MM-DD`` (day) or ``YYYY-MM``."""
    period = period or period_from_config()
    dt = datetime.fromtimestamp(time.time() if now is None else float(now),
                                tz=timezone.utc)
    return dt.strftime("%Y-%m-%d") if period == PERIOD_DAY else dt.strftime("%Y-%m")


def _ledger_path() -> Path:
    return data_dir("provider_spend.json")


def _load(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("provider_cost_cap: cannot read ledger %s: %s", path, e)
        return {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                               prefix=".provider-spend-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record(provider: str, dollars: float, *, now: float | None = None,
           path: Path | None = None) -> None:
    """Add one call's spend to ``(current period, provider)``.

    Fail-soft and clamped: negative/blank input is ignored, a ledger I/O
    error logs a warning — accounting never crashes the run that produced
    the spend (the *next* :func:`enforce` is where a busted cap stops calls).
    """
    name = _canon(provider)
    amount = max(0.0, float(dollars or 0.0))
    if not name or amount == 0.0:
        return
    key = period_key(now)
    ledger = path if path is not None else _ledger_path()
    try:
        # In-process lock + cross-process flock: serialize the whole
        # load-modify-save so two processes can't both load the same total and
        # have the second save clobber the first -- which would under-record
        # spend and let the deployment slip past its provider cap.
        with _LEDGER_LOCK, cross_process_lock(ledger):
            data = _load(ledger)
            bucket = data.setdefault(key, {})
            bucket[name] = float(bucket.get(name, 0.0)) + amount
            _save(ledger, data)
    except OSError as e:
        log.warning("provider_cost_cap: failed to record $%.4f for %r: %s",
                    amount, name, e)


def check(provider: str, *, now: float | None = None,
          path: Path | None = None) -> CapStatus:
    """Where ``provider`` stands against its cap for the current period.

    No cap configured -> always allowed (``cap``/``remaining`` are None).
    """
    name = _canon(provider)
    cap = caps_from_config().get(name)
    ledger = path if path is not None else _ledger_path()
    spent = float((_load(ledger).get(period_key(now)) or {}).get(name, 0.0))
    if cap is None:
        return CapStatus(allowed=True, spent=spent, cap=None, remaining=None)
    remaining = max(0.0, cap - spent)
    return CapStatus(allowed=spent < cap, spent=spent, cap=cap,
                     remaining=remaining)


def would_exceed(provider: str, projected_dollars: float, *,
                 now: float | None = None, path: Path | None = None) -> bool:
    """Would spending ``projected_dollars`` more push ``provider`` over its
    cap? Always False with no cap configured."""
    st = check(provider, now=now, path=path)
    if st.cap is None:
        return False
    return st.spent + max(0.0, float(projected_dollars or 0.0)) > st.cap


# (provider, period) pairs we've already paged the operator about, so a blown
# cap alerts ONCE per period instead of on every subsequently-blocked dispatch.
_alerted: set[tuple[str, str]] = set()


def enforce(provider: str, *, now: float | None = None,
            path: Path | None = None) -> CapStatus:
    """The LLM dispatch gate: raise :class:`ProviderCapExceeded` when the
    provider's period spend has reached its cap; otherwise return the status
    (so the caller can log remaining headroom). No cap -> no-op."""
    st = check(provider, now=now, path=path)
    if not st.allowed:
        period = period_key(now)
        canon = _canon(provider)
        if (canon, period) not in _alerted:
            _alerted.add((canon, period))
            try:  # page the operator once: deployment-wide spend is exhausted
                from .ops_alert import alert
                alert("provider_cost_cap_exhausted",
                      f"{canon} spend ${st.spent:.2f} reached the ${st.cap:.2f} "
                      f"cap for period {period}; LLM calls are now blocked",
                      severity="critical")
            except Exception:  # pragma: no cover - alerting never blocks the gate
                pass
        raise ProviderCapExceeded(canon, st.spent, float(st.cap or 0.0), period)
    return st


def prune(*, now: float | None = None, path: Path | None = None) -> int:
    """Drop every ledger period except the current one; returns how many
    period buckets were removed.

    Old periods are dead weight once their window closes (and a stale key
    from a period-knob change would otherwise linger forever). Call it
    opportunistically — e.g. after recording at period rollover.
    """
    current = period_key(now)
    ledger = path if path is not None else _ledger_path()
    with _LEDGER_LOCK, cross_process_lock(ledger):
        data = _load(ledger)
        stale = [k for k in data if k != current]
        if not stale:
            return 0
        for k in stale:
            del data[k]
        try:
            _save(ledger, data)
        except OSError as e:
            log.warning("provider_cost_cap: prune failed for %s: %s", ledger, e)
            return 0
    return len(stale)


__all__ = [
    "ProviderCapExceeded",
    "CapStatus",
    "PERIOD_DAY",
    "PERIOD_MONTH",
    "caps_from_config",
    "period_from_config",
    "period_key",
    "record",
    "check",
    "would_exceed",
    "enforce",
    "prune",
]
