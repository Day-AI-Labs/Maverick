"""Speculative best-of-N with early pruning (roadmap: 2028 H1 performance).

Best-of-N runs N attempts and keeps the best — but paying for all N to
completion is wasteful when several are visibly going nowhere early. This
prunes at the **first reasoning checkpoint**: each attempt emits a partial
(its plan / first reasoning step) early, a cheap scorer ranks the partials,
and the bottom attempts are **cancelled before they finish** — so the budget
concentrates on the candidates that look strongest, not on N full runs.

Distinct from ``latency_best_of_n`` (which races on *latency* — first success
wins) and ``speculative`` (fire-and-forget speculation): here the kill signal
is **early quality**, not time. The scorer is injected (a heuristic, a small
classifier, or a judge) and only sees the cheap partials, never a full run.

Shape: ``run(attempts, checkpoint, score, keep=...)`` where each attempt is
``(emit_checkpoint, finish)`` — ``emit_checkpoint()`` awaits the cheap partial,
``finish()`` awaits the full result. All N checkpoints run; the top ``keep``
by score run ``finish()`` concurrently and the best (or first) is returned;
the rest are cancelled. Pure asyncio + injected seams, deterministic in tests.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from .best_of_n import AllAttemptsFailed  # re-export: single shared definition

log = logging.getLogger(__name__)

T = TypeVar("T")
C = TypeVar("C")


@dataclass
class Attempt(Generic[C, T]):
    """One candidate: a cheap checkpoint, then the full finish.

    ``checkpoint()`` awaits the early partial (plan / first reasoning step);
    ``finish()`` awaits the full result. ``name`` is for logs/telemetry.
    """

    checkpoint: Callable[[], Awaitable[C]]
    finish: Callable[[], Awaitable[T]]
    name: str = ""


@dataclass
class _Scored(Generic[C]):
    index: int
    name: str
    partial: C
    score: float


async def run(
    attempts: list[Attempt[C, T]],
    *,
    score: Callable[[C], float],
    keep: int = 1,
    pick_final: Callable[[list[T]], T] | None = None,
) -> T:
    """Run N attempts, prune at the checkpoint, finish only the top ``keep``.

    1. Run every attempt's ``checkpoint()`` concurrently (cheap partials).
    2. Score each partial with ``score`` (an attempt whose checkpoint *raised*
       is dropped with a ``-inf`` score — it never reaches finish).
    3. Run ``finish()`` for the top ``keep`` by score concurrently; cancel the
       rest (they're already known to be weaker, and never started finishing).
    4. Return ``pick_final(results)`` (default: the highest-scored survivor's
       result, or the first to finish when only one is kept).

    Raises ``ValueError`` for empty ``attempts`` and ``AllAttemptsFailed`` when
    every survivor's ``finish()`` raised.
    """
    if not attempts:
        raise ValueError("run needs at least one attempt")
    keep = max(1, min(keep, len(attempts)))

    # -- stage 1: all checkpoints concurrently --
    cp_tasks = [asyncio.ensure_future(a.checkpoint()) for a in attempts]
    partials = await asyncio.gather(*cp_tasks, return_exceptions=True)

    scored: list[_Scored[C]] = []
    for i, (a, partial) in enumerate(zip(attempts, partials, strict=False)):
        if isinstance(partial, BaseException):
            log.debug("attempt %s checkpoint failed: %s", a.name or i, partial)
            continue
        try:
            s = float(score(partial))
        except Exception:  # a scorer error drops the attempt, never crashes the run
            log.debug("scorer raised for attempt %s; dropping", a.name or i)
            continue
        scored.append(_Scored(index=i, name=a.name or str(i), partial=partial, score=s))

    if not scored:
        raise AllAttemptsFailed("every attempt failed at the checkpoint")

    # -- stage 2: keep the top-`keep`, prune the rest (they never finish) --
    scored.sort(key=lambda s: (-s.score, s.index))
    survivors = scored[:keep]
    pruned = scored[keep:]
    if pruned:
        log.info("speculative best-of-N: pruned %d/%d at checkpoint (kept %s)",
                 len(pruned), len(scored), [s.name for s in survivors])

    # -- stage 3: finish survivors concurrently; cancel any laggards if a final
    #    is chosen by ranking (we still await all to pick the best) --
    fin_tasks = {
        s.index: asyncio.ensure_future(attempts[s.index].finish())
        for s in survivors
    }
    results: list[tuple[float, T]] = []
    errors: list[BaseException] = []
    done = await asyncio.gather(*fin_tasks.values(), return_exceptions=True)
    by_index = dict(zip(fin_tasks.keys(), done, strict=False))
    for s in survivors:
        r = by_index[s.index]
        if isinstance(r, BaseException):
            errors.append(r)
        else:
            results.append((s.score, r))

    if not results:
        raise AllAttemptsFailed(
            f"all {len(survivors)} surviving attempts failed to finish: {errors}")

    if pick_final is not None:
        return pick_final([r for _s, r in results])
    # default: the result from the highest-scored survivor.
    results.sort(key=lambda sr: -sr[0])
    return results[0][1]


async def prune_at_checkpoint(
    attempts: list[Attempt[C, T]],
    *,
    score: Callable[[C], float],
) -> Any:
    """Convenience: keep exactly one (pure pruning best-of-N)."""
    return await run(attempts, score=score, keep=1)


__all__ = ["Attempt", "AllAttemptsFailed", "run", "prune_at_checkpoint"]
