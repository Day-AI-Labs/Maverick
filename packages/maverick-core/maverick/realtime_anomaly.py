"""Real-time anomaly detection (roadmap: 2027 H2 performance).

:mod:`maverick.cross_run_anomaly` is *batch* — it profiles a finished run
against a baseline of past runs. This is the *online* companion: feed it a
metric value as it happens (a tool latency, a per-step cost) and it flags a
spike **immediately**, judged against a rolling window of recent values — so a
runaway is caught mid-run, not in a post-mortem.

A value is anomalous when it sits more than ``z_threshold`` standard deviations
from the recent mean (a robust-enough online z-score over a bounded window).
Deterministic and dependency-free; :class:`StreamMonitor` keeps one detector
per named stream so cost / latency / tokens are watched independently.
"""
from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass

DEFAULT_WINDOW = 50
DEFAULT_Z = 3.0
DEFAULT_MIN_SAMPLES = 10


@dataclass(frozen=True)
class AnomalyResult:
    value: float
    is_anomaly: bool
    z_score: float
    mean: float
    stdev: float


class RollingAnomalyDetector:
    """Online z-score spike detector over a bounded sliding window."""

    def __init__(self, *, window: int = DEFAULT_WINDOW, z_threshold: float = DEFAULT_Z,
                 min_samples: int = DEFAULT_MIN_SAMPLES):
        self._w: deque[float] = deque(maxlen=max(2, window))
        self._z = z_threshold
        self._min = max(2, min_samples)

    def update(self, value: float) -> AnomalyResult:
        """Judge ``value`` against the window, then add it to the window."""
        v = float(value)
        hist = list(self._w)
        if len(hist) < self._min:
            result = AnomalyResult(v, False, 0.0,
                                   round(statistics.fmean(hist), 4) if hist else v, 0.0)
        else:
            m = statistics.fmean(hist)
            sd = statistics.pstdev(hist)
            if sd > 0:
                z = (v - m) / sd
                result = AnomalyResult(v, abs(z) >= self._z, round(z, 3),
                                       round(m, 4), round(sd, 4))
            else:
                # A perfectly flat history: any deviation is an anomaly.
                result = AnomalyResult(v, v != m, 0.0, round(m, 4), 0.0)
        self._w.append(v)
        return result

    def reset(self) -> None:
        self._w.clear()


class StreamMonitor:
    """One :class:`RollingAnomalyDetector` per named metric stream."""

    def __init__(self, *, window: int = DEFAULT_WINDOW, z_threshold: float = DEFAULT_Z,
                 min_samples: int = DEFAULT_MIN_SAMPLES):
        self._kw = {"window": window, "z_threshold": z_threshold,
                    "min_samples": min_samples}
        self._streams: dict[str, RollingAnomalyDetector] = {}

    def update(self, stream: str, value: float) -> AnomalyResult:
        det = self._streams.get(stream)
        if det is None:
            det = RollingAnomalyDetector(**self._kw)
            self._streams[stream] = det
        return det.update(value)

    def streams(self) -> list[str]:
        return sorted(self._streams)


__all__ = ["AnomalyResult", "RollingAnomalyDetector", "StreamMonitor",
           "DEFAULT_WINDOW", "DEFAULT_Z", "DEFAULT_MIN_SAMPLES"]
