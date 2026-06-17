"""Per-principal usage quotas — the P2 "cost as a managed resource" primitive.

:class:`Budget` caps a *single run*. Quotas cap a *principal* across runs over
a rolling time-window (a calendar day), so an operator can do chargeback /
rate-limit spend by user or team — the cost-governance layer the canonical
agent-OS leaves unowned.

A small persistent :class:`UsageLedger` records cumulative spend (dollars +
input/output tokens) per ``(principal, UTC day)`` under the tenant-aware data
dir (``<data>/usage/ledger.json``), so it is already tenant-isolated. Every
write is atomic-ish (temp file + ``os.replace``) and the whole module is
**fail-soft**: a ledger error logs a warning and never crashes a run — cost
accounting must not be able to take down the agent loop.

Default-off and opt-in, exactly like :func:`maverick.capability.capability_enforced`
and :func:`maverick.agent._risk_proportional_verify_enabled`: with nothing
configured :func:`over_quota` returns ``None`` and behaviour is unchanged. Turn
it on with ``[quotas] enforce = true`` (plus ``max_dollars_per_day`` /
``max_tokens_per_day``) or the ``MAVERICK_QUOTA_*`` env vars.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from .paths import data_dir

log = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}

# Serializes the ledger read-modify-write across threads in this process; the
# flock below extends that across processes (dashboard + serve sharing a tenant
# ledger). Without it, two concurrent record()s load the same totals and the
# second save clobbers the first -- spend is undercounted and a principal slips
# past its quota.
_RECORD_LOCK = threading.Lock()


@contextmanager
def _cross_process_lock(target):
    """Advisory exclusive lock over the ledger's read-modify-write, keyed on a
    stable sidecar file (never the ledger itself -- os.replace swaps its inode).
    POSIX-only; degrades to a no-op where fcntl/flock is unavailable."""
    lock_path = target.parent / (target.name + ".lock")
    fd = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        yield  # cannot create the lock file -> proceed best-effort
        return
    try:
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass  # non-POSIX / exotic FS -> in-process lock still applies
        yield
    finally:
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        os.close(fd)


def _ledger_path():
    """Tenant-scoped ledger location: ``<data>/usage/ledger.json``."""
    return data_dir("usage", "ledger.json")


def _today() -> str:
    """UTC calendar day key (``YYYY-MM-DD``). UTC so the window doesn't shift
    with the host timezone or DST."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class UsageLedger:
    """A persistent ``(principal, day) -> {dollars, in_tokens, out_tokens}`` tally.

    Not a hot path (written once per run, read once per goal start), so each
    call reloads from disk rather than holding shared mutable state — that keeps
    concurrent runs / processes from clobbering each other's totals on the
    last-writer-wins of an in-memory cache. All I/O is fail-soft.
    """

    def __init__(self, path=None) -> None:
        self.path = path if path is not None else _ledger_path()

    def _load(self) -> dict:
        try:
            with open(self.path, "rb") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            log.warning("quotas: cannot read ledger %s: %s", self.path, e)
            return {}

    def _save(self, data: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # A UNIQUE temp file: a fixed ".json.tmp" name collides under
            # concurrent saves (one os.replace moves it out from under another,
            # dropping the write). mkstemp keeps each writer's temp private.
            fd, tmp = tempfile.mkstemp(
                dir=str(self.path.parent), prefix=".ledger-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                os.chmod(tmp, 0o600)
                os.replace(tmp, self.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError as e:
            log.warning("quotas: cannot write ledger %s: %s", self.path, e)

    def record(
        self,
        principal: str,
        dollars: float,
        in_tokens: int,
        out_tokens: int,
        *,
        day: str | None = None,
    ) -> None:
        """Add one run's spend to ``(principal, day)``. Negative inputs are
        clamped to zero; a blank principal is ignored. Never raises."""
        if not principal:
            return
        day = day or _today()
        # Serialize the whole load-modify-save so concurrent records accumulate
        # instead of clobbering each other (in-process lock + cross-process
        # flock on a sidecar file).
        with _RECORD_LOCK, _cross_process_lock(self.path):
            data = self._load()
            bucket = data.setdefault(principal, {})
            cell = bucket.setdefault(day, {"dollars": 0.0, "in_tokens": 0, "out_tokens": 0})
            cell["dollars"] = float(cell.get("dollars", 0.0)) + max(0.0, float(dollars or 0.0))
            cell["in_tokens"] = int(cell.get("in_tokens", 0)) + max(0, int(in_tokens or 0))
            cell["out_tokens"] = int(cell.get("out_tokens", 0)) + max(0, int(out_tokens or 0))
            self._save(data)

    def usage(self, principal: str, *, day: str | None = None) -> dict:
        """Return ``{dollars, in_tokens, out_tokens}`` for ``(principal, day)``;
        zeros when nothing is recorded."""
        day = day or _today()
        cell = (self._load().get(principal) or {}).get(day) or {}
        return {
            "dollars": float(cell.get("dollars", 0.0)),
            "in_tokens": int(cell.get("in_tokens", 0)),
            "out_tokens": int(cell.get("out_tokens", 0)),
        }

    def prune(self, keep_days: int, *, now: float | None = None,
              dry_run: bool = False) -> dict:
        """Drop ``(principal, day)`` buckets older than ``keep_days`` days.

        The ledger accrues a row per ``(principal, UTC day)`` forever; this is
        the retention valve. A day is expired when it is on or before the cutoff
        (``now - keep_days*86400``), matching the audit-file window. Principals
        left with no days are dropped. ``keep_days <= 0`` is a no-op (retention
        disabled). Returns a report; never raises.
        """
        if not keep_days or int(keep_days) <= 0:
            return {"removed_buckets": 0, "removed_principals": 0, "reason": "disabled"}
        now_ts = now if now is not None else datetime.now(timezone.utc).timestamp()
        cutoff_ts = now_ts - max(1, int(keep_days)) * 86400.0
        # YYYY-MM-DD sorts lexicographically == chronologically, so a string
        # compare against the cutoff day is the same window the SQL purges use.
        cutoff_day = datetime.fromtimestamp(cutoff_ts, timezone.utc).strftime("%Y-%m-%d")
        removed_buckets = 0
        removed_principals = 0
        with _RECORD_LOCK, _cross_process_lock(self.path):
            data = self._load()
            for principal in list(data.keys()):
                days = data.get(principal) or {}
                expired = [d for d in days if isinstance(d, str) and d <= cutoff_day]
                remaining = len(days) - len(expired)
                for day in expired:
                    removed_buckets += 1
                    if not dry_run:
                        del days[day]
                # A principal is dropped when no day-buckets would remain after
                # the purge. Decide from the pre-purge counts so the dry-run
                # report matches what a real run removes.
                if remaining <= 0:
                    removed_principals += 1
                    if not dry_run:
                        del data[principal]
            if not dry_run and removed_buckets:
                self._save(data)
        return {"removed_buckets": removed_buckets,
                "removed_principals": removed_principals,
                "cutoff_day": cutoff_day}


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _quota_config() -> dict:
    """Merge ``[quotas]`` config under the ``MAVERICK_QUOTA_*`` env vars.

    Env wins over config (same precedence the rest of the kernel uses for
    opt-in toggles). Returns ``enforce`` plus the two caps; ``0``/unset cap
    means "no limit on this dimension". Fail-soft -> all-off on any error.
    """
    cfg: dict = {}
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("quotas") or {}
    except Exception:
        cfg = {}

    enforce = bool(cfg.get("enforce", False))
    if os.environ.get("MAVERICK_QUOTA_ENFORCE", "").strip().lower() in _TRUE:
        enforce = True

    def _cap(env_name: str, cfg_key: str) -> float:
        env_val = _env_float(env_name)
        if env_val is not None:
            return max(0.0, env_val)
        try:
            return max(0.0, float(cfg.get(cfg_key, 0) or 0))
        except (TypeError, ValueError):
            return 0.0

    return {
        "enforce": enforce,
        "max_dollars_per_day": _cap("MAVERICK_QUOTA_MAX_DOLLARS_PER_DAY", "max_dollars_per_day"),
        "max_tokens_per_day": _cap("MAVERICK_QUOTA_MAX_TOKENS_PER_DAY", "max_tokens_per_day"),
    }


def quotas_enforced() -> bool:
    """Opt-in, off by default. ``MAVERICK_QUOTA_ENFORCE=1`` or ``[quotas]
    enforce = true`` turns on the per-principal daily quota check."""
    return _quota_config()["enforce"]


def record_usage(
    principal: str,
    dollars: float,
    in_tokens: int = 0,
    out_tokens: int = 0,
) -> None:
    """Record a finished run's spend against ``principal`` for today's window.

    Always safe to call (even when enforcement is off — recording is how the
    ledger accrues chargeback data); fail-soft on any ledger error.
    """
    try:
        UsageLedger().record(principal, dollars, in_tokens, out_tokens)
    except Exception as e:  # pragma: no cover - ledger is fully fail-soft
        log.warning("quotas: failed to record usage for %r: %s", principal, e)


def over_quota(principal: str) -> str | None:
    """Return a human-readable reason if ``principal`` is over its daily quota,
    else ``None``.

    Returns ``None`` (allow) when enforcement is off, no caps are configured,
    the principal is blank, or anything goes wrong reading the ledger — quotas
    only ever *refuse*; they never crash a run.
    """
    cfg = _quota_config()
    if not cfg["enforce"] or not principal:
        return None
    max_dollars = cfg["max_dollars_per_day"]
    max_tokens = cfg["max_tokens_per_day"]
    if max_dollars <= 0 and max_tokens <= 0:
        return None
    try:
        used = UsageLedger().usage(principal)
    except Exception as e:  # pragma: no cover - ledger is fully fail-soft
        log.warning("quotas: failed to read usage for %r: %s", principal, e)
        return None
    if max_dollars > 0 and used["dollars"] >= max_dollars:
        return (
            f"principal {principal!r} is over its daily spend quota "
            f"(${used['dollars']:.2f} >= ${max_dollars:.2f})"
        )
    total_tokens = used["in_tokens"] + used["out_tokens"]
    if max_tokens > 0 and total_tokens >= max_tokens:
        return (
            f"principal {principal!r} is over its daily token quota "
            f"({total_tokens} >= {int(max_tokens)} tokens)"
        )
    return None


__all__ = [
    "UsageLedger",
    "quotas_enforced",
    "record_usage",
    "over_quota",
]
