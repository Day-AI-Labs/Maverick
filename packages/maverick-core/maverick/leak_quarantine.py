"""Memory-leak quarantine (roadmap: 2027 H1 performance).

Long-horizon runs die slow deaths: one component (an agent's scratch buffers,
a connector's response cache) grows a little every episode until the process
OOMs hours later. This watchdog watches per-component memory samples and, when
a component grows monotonically across enough consecutive samples by more than
a threshold, **quarantines** it: marks it leaky and fires a callback so the
orchestrator can recycle that component (drop+rebuild) instead of letting the
whole process fall over.

Detection is deliberately conservative — sawtooth usage (grow, GC, shrink) is
normal and never trips it; only sustained monotonic growth does.

Components self-report their sample (``record(component, bytes)``) — usually
``len()``-based estimates of their buffers or a tracemalloc slice — because
per-component RSS doesn't exist in-process. :func:`process_rss_bytes` gives the
whole-process figure for the common "watch the process" case. Stdlib-only,
thread-safe, deterministic (no timers — the caller decides when to sample).
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

_DEFAULT_THRESHOLD = 64 * 1024 * 1024  # 64 MiB of sustained growth
_DEFAULT_CONSECUTIVE = 5


def process_rss_bytes() -> int:
    """Best-effort resident-set size of this process in bytes (0 if unknown)."""
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports KiB; macOS reports bytes.
        import sys
        return int(rss) if sys.platform == "darwin" else int(rss) * 1024
    except Exception:  # pragma: no cover -- platform without resource
        return 0


@dataclass(frozen=True)
class LeakVerdict:
    component: str
    growth_bytes: int
    samples: int


class LeakWatchdog:
    """Track per-component memory samples; quarantine sustained growers.

    A component is quarantined when its last ``consecutive`` samples are
    strictly increasing AND the growth across that window is at least
    ``threshold_bytes``. ``on_quarantine`` (optional) fires once per component
    at the moment of quarantine; quarantine is sticky until :meth:`release`.
    """

    def __init__(
        self,
        threshold_bytes: int = _DEFAULT_THRESHOLD,
        consecutive: int = _DEFAULT_CONSECUTIVE,
        on_quarantine: Callable[[LeakVerdict], None] | None = None,
    ):
        if threshold_bytes <= 0:
            raise ValueError("threshold_bytes must be > 0")
        if consecutive < 3:
            raise ValueError("consecutive must be >= 3 (avoid flagging noise)")
        self.threshold_bytes = int(threshold_bytes)
        self.consecutive = int(consecutive)
        self._on_quarantine = on_quarantine
        self._lock = threading.Lock()
        self._windows: dict[str, deque[int]] = {}
        self._quarantined: dict[str, LeakVerdict] = {}

    def record(self, component: str, sample_bytes: int) -> bool:
        """Record one sample. Returns True iff ``component`` is (now) quarantined."""
        name = str(component)
        size = max(0, int(sample_bytes))
        verdict: LeakVerdict | None = None
        with self._lock:
            if name in self._quarantined:
                return True
            window = self._windows.setdefault(name, deque(maxlen=self.consecutive))
            window.append(size)
            if len(window) == self.consecutive:
                increasing = all(b > a for a, b in zip(list(window), list(window)[1:], strict=False))
                growth = window[-1] - window[0]
                if increasing and growth >= self.threshold_bytes:
                    verdict = LeakVerdict(name, growth, self.consecutive)
                    self._quarantined[name] = verdict
        if verdict is not None:
            log.warning(
                "leak quarantine: %s grew %d bytes over %d consecutive samples",
                verdict.component, verdict.growth_bytes, verdict.samples,
            )
            if self._on_quarantine is not None:
                try:
                    self._on_quarantine(verdict)
                except Exception:  # callback must never break sampling
                    log.exception("leak-quarantine callback failed")
            return True
        return False

    def is_quarantined(self, component: str) -> bool:
        with self._lock:
            return str(component) in self._quarantined

    def quarantined(self) -> list[LeakVerdict]:
        with self._lock:
            return list(self._quarantined.values())

    def release(self, component: str) -> bool:
        """Lift a quarantine (after the component was recycled). True if it was held."""
        name = str(component)
        with self._lock:
            self._windows.pop(name, None)
            return self._quarantined.pop(name, None) is not None


__all__ = ["LeakWatchdog", "LeakVerdict", "process_rss_bytes"]
