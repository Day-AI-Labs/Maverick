"""Cost-aware routing v3 — contextual bandit (roadmap: 2028 H1 performance).

v2 (``cost_router``) picks the cheapest *viable* provider by a static tier +
health table. v3 *learns*: which provider actually delivers the best
reward-per-dollar **for this kind of task**, adapting as quality and prices
drift. It's a contextual multi-armed bandit — arms are provider:model specs,
the context is a coarse task class (role + tier), the reward is operator-
defined (default: success ÷ dollars).

Deterministic and dependency-free: a per-(context, arm) running mean with an
epsilon-greedy policy over an injectable PRNG, so a test pins exactly what it
explores. Persists the learned table to ``data_dir("router_bandit.json")``
(atomic 0600) so learning survives restarts.

Opt-in and layered ON TOP of v2: v3 only chooses among the arms v2 already
deems viable+healthy (it never routes to a down or unaffordable provider),
and it falls back to v2's pick on a cold context. ``[routing] bandit = true``
(env ``MAVERICK_ROUTING_BANDIT``); off by default — v2 behavior unchanged.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from random import Random

log = logging.getLogger(__name__)

DEFAULT_EPSILON = 0.1   # explore 10% of the time
_MIN_PULLS = 2          # try each arm at least twice before exploiting


def enabled() -> bool:
    if os.environ.get("MAVERICK_ROUTING_BANDIT", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    try:
        from .config import load_config
        return bool(((load_config() or {}).get("routing") or {}).get("bandit", False))
    except Exception:  # pragma: no cover -- config never blocks routing
        return False


@dataclass
class _Arm:
    pulls: int = 0
    total_reward: float = 0.0

    @property
    def mean(self) -> float:
        return self.total_reward / self.pulls if self.pulls else 0.0


@dataclass
class ContextualBandit:
    """Per-(context, arm) running-mean reward with an epsilon-greedy policy."""

    epsilon: float = DEFAULT_EPSILON
    rng: Random = field(default_factory=lambda: Random(0))
    path: Path | None = None
    _table: dict[str, dict[str, _Arm]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self):
        if self.path is not None:
            self._load()

    # -- learning ---------------------------------------------------------

    def record(self, context: str, arm: str, reward: float) -> None:
        with self._lock:
            a = self._table.setdefault(context, {}).setdefault(arm, _Arm())
            a.pulls += 1
            a.total_reward += float(reward)
            self._save()

    def record_outcome(self, context: str, arm: str, *, success: bool, dollars: float) -> None:
        """Convenience reward: success per dollar (free successes score high;
        failures score zero regardless of cost)."""
        reward = 0.0 if not success else 1.0 / max(dollars, 1e-4)
        self.record(context, arm, reward)

    # -- policy -----------------------------------------------------------

    def choose(self, context: str, arms: list[str]) -> str | None:
        """Epsilon-greedy choice among ``arms`` for ``context``.

        Returns None when ``arms`` is empty (caller keeps its default). Any arm
        pulled fewer than ``_MIN_PULLS`` times is explored first (cold-start
        coverage); otherwise exploit the best mean with ``epsilon`` random
        exploration.
        """
        if not arms:
            return None
        if len(arms) == 1:
            return arms[0]
        with self._lock:
            ctx = self._table.get(context, {})
            under = [a for a in arms if ctx.get(a, _Arm()).pulls < _MIN_PULLS]
        if under:
            return self.rng.choice(under)
        if self.rng.random() < self.epsilon:
            return self.rng.choice(arms)
        with self._lock:
            ctx = self._table.get(context, {})
            # Highest mean reward; ties broken by arm name for determinism.
            return max(arms, key=lambda a: (ctx.get(a, _Arm()).mean, a == arms[0], a))

    def stats(self, context: str) -> dict[str, dict[str, float]]:
        with self._lock:
            ctx = self._table.get(context, {})
            return {a: {"pulls": v.pulls, "mean_reward": round(v.mean, 6)}
                    for a, v in sorted(ctx.items())}

    # -- persistence ------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = json.loads(Path(self.path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for ctx, arms in (raw or {}).items():
            self._table[ctx] = {
                a: _Arm(pulls=int(d.get("pulls", 0)), total_reward=float(d.get("total_reward", 0.0)))
                for a, d in arms.items()
            }

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            p = Path(self.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            data = {ctx: {a: {"pulls": v.pulls, "total_reward": v.total_reward}
                          for a, v in arms.items()}
                    for ctx, arms in self._table.items()}
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
            os.replace(tmp, p)
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
        except Exception:  # pragma: no cover -- persistence is best-effort
            log.debug("bandit save failed", exc_info=True)


def context_key(role: str, tier: int) -> str:
    return f"{role or 'default'}:t{int(tier)}"


_shared: ContextualBandit | None = None
_shared_lock = threading.Lock()


def shared() -> ContextualBandit:
    global _shared
    with _shared_lock:
        if _shared is None:
            from .paths import data_dir
            _shared = ContextualBandit(path=data_dir("router_bandit.json"))
        return _shared


def reset_shared() -> None:
    global _shared
    with _shared_lock:
        _shared = None


def pick(role: str, tier: int, viable_arms: list[str],
         *, bandit: ContextualBandit | None = None,
         fallback: Callable[[], str | None] | None = None) -> str | None:
    """v3 entry point: learn-and-choose among v2's viable arms.

    ``viable_arms`` MUST already be the healthy/affordable set v2 produced —
    v3 only reorders *within* it, never routes somewhere v2 rejected. On a
    cold context (or empty arms) it defers to ``fallback`` (v2's pick).
    """
    if not enabled() or not viable_arms:
        return fallback() if fallback else None
    b = bandit or shared()
    chosen = b.choose(context_key(role, tier), viable_arms)
    return chosen or (fallback() if fallback else None)


__all__ = ["ContextualBandit", "context_key", "pick", "enabled",
           "shared", "reset_shared", "DEFAULT_EPSILON"]
