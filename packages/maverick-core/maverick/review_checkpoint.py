"""Long-horizon goal review checkpoint (roadmap: 2028 H1 safety).

A budget cap stops a runaway; a *checkpoint* does something subtler — it
pauses a long, expensive, still-progressing run at intervals so a human can
look before it spends the next tranche. "It's burned $20 and 200 tool calls
over two hours; keep going?" The autonomy story for genuinely long-horizon
work needs this human-in-the-loop heartbeat, distinct from the hard ceiling.

A checkpoint fires when ANY configured interval is crossed since the last
one: every N dollars, every M tool calls, or every T wall-seconds. Firing
means *ask* — the caller consults its consent path (dashboard approval,
killswitch, CLI prompt) and either continues (arming the next interval) or
halts. This module is the pure interval bookkeeping + decision; the asking is
the caller's existing approval seam, injected.

Opt-in via ``[safety] review_checkpoint`` (e.g. ``dollars = 10`` /
``tool_calls = 100`` / ``wall_seconds = 1800``); unset intervals don't fire.
Off by default — a run with no checkpoint config behaves exactly as today.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckpointPolicy:
    dollars: float | None = None        # fire every N dollars
    tool_calls: int | None = None       # fire every M tool calls
    wall_seconds: float | None = None   # fire every T seconds

    def is_active(self) -> bool:
        return bool(self.dollars or self.tool_calls or self.wall_seconds)


def policy_from_config() -> CheckpointPolicy:
    """Build the policy from ``[safety] review_checkpoint`` (empty = inactive)."""
    import os

    def _envf(name: str) -> float | None:
        v = os.environ.get(name, "").strip()
        try:
            return float(v) if v else None
        except ValueError:
            return None

    dollars = _envf("MAVERICK_REVIEW_CHECKPOINT_DOLLARS")
    calls = _envf("MAVERICK_REVIEW_CHECKPOINT_TOOL_CALLS")
    secs = _envf("MAVERICK_REVIEW_CHECKPOINT_WALL_SECONDS")
    if dollars is None and calls is None and secs is None:
        try:
            from .config import load_config
            cfg = ((load_config() or {}).get("safety") or {}).get("review_checkpoint") or {}
            dollars = _num(cfg.get("dollars"))
            calls = _num(cfg.get("tool_calls"))
            secs = _num(cfg.get("wall_seconds"))
        except Exception:  # pragma: no cover -- config never blocks a run
            pass
    return CheckpointPolicy(
        dollars=dollars if dollars and dollars > 0 else None,
        tool_calls=int(calls) if calls and calls > 0 else None,
        wall_seconds=secs if secs and secs > 0 else None,
    )


def _num(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if v > 0 else None


@dataclass(frozen=True)
class CheckpointEvent:
    reason: str           # "dollars" | "tool_calls" | "wall_seconds"
    value: float          # the metric value at firing
    threshold: float      # the interval that was crossed


class ReviewCheckpoint:
    """Track a run's metrics and fire a review when an interval is crossed.

    ``review`` is the caller's gate: ``review(event) -> bool`` (True = keep
    going, False = halt). It's only called when an interval is actually
    crossed; between checkpoints ``check`` is a couple of comparisons.
    """

    def __init__(self, policy: CheckpointPolicy,
                 review: Callable[[CheckpointEvent], bool] | None = None):
        self.policy = policy
        self._review = review
        self._last_dollars = 0.0
        self._last_calls = 0
        self._last_seconds = 0.0
        self.fired = 0

    def _due(self, budget) -> CheckpointEvent | None:
        if self.policy.dollars:
            spent = float(getattr(budget, "dollars", 0.0))
            if spent - self._last_dollars >= self.policy.dollars:
                self._last_dollars = spent
                return CheckpointEvent("dollars", spent, self.policy.dollars)
        if self.policy.tool_calls:
            calls = int(getattr(budget, "tool_calls", 0))
            if calls - self._last_calls >= self.policy.tool_calls:
                self._last_calls = calls
                return CheckpointEvent("tool_calls", calls, self.policy.tool_calls)
        if self.policy.wall_seconds:
            try:
                secs = float(budget.elapsed())
            except Exception:
                secs = 0.0
            if secs - self._last_seconds >= self.policy.wall_seconds:
                self._last_seconds = secs
                return CheckpointEvent("wall_seconds", secs, self.policy.wall_seconds)
        return None

    def check(self, budget) -> CheckpointEvent | None:
        """Fire a checkpoint if any interval was crossed since the last one.

        Returns the event when a checkpoint fired AND the reviewer voted to
        HALT (the caller should stop); returns None to continue. When no
        interval is crossed, or the reviewer approves, returns None. With no
        reviewer wired in, a crossed interval is logged and approved
        (heartbeat-only mode).
        """
        if not self.policy.is_active():
            return None
        event = self._due(budget)
        if event is None:
            return None
        self.fired += 1
        log.info("review checkpoint: %s reached %g (interval %g)",
                 event.reason, event.value, event.threshold)
        if self._review is None:
            return None  # heartbeat only: record + continue
        try:
            keep_going = bool(self._review(event))
        except Exception:  # a reviewer error must not crash the run
            log.exception("review checkpoint reviewer failed; continuing")
            keep_going = True
        return None if keep_going else event


def from_config(review: Callable[[CheckpointEvent], bool] | None = None) -> ReviewCheckpoint:
    return ReviewCheckpoint(policy_from_config(), review=review)


__all__ = ["CheckpointPolicy", "CheckpointEvent", "ReviewCheckpoint",
           "policy_from_config", "from_config"]
