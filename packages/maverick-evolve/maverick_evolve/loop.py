"""Stage 2 wired: a continuous evolution loop with a persistent diverse archive.

Single-shot ``evolve`` improves within one call; real self-improvement is
*continuous* -- it accumulates across rounds (and process restarts) in a
persisted, diverse archive, branching from the whole population so it doesn't
collapse onto one lineage. This module is that driver.

Each round is independently **calibration-gated**: if the verifier has drifted,
the round is SKIPPED (not failed) -- evolution pauses until the judge is
trustworthy again, then resumes from the saved archive. That's the trust
thermostat applied to a long-running loop. Config-only throughout; no code
mutation. Dependency-injected ``agent_factory`` so it runs (and tests) without a
live model.
"""
from __future__ import annotations

import logging
import random
from collections.abc import Callable
from pathlib import Path

from .archive import Archive, Candidate
from .eval_harness import EvalCase
from .runner import AgentFactory, calibration_frozen, evolve_with_eval

log = logging.getLogger(__name__)


async def evolve_continuous(
    seed_config: dict,
    cases: list[EvalCase],
    agent_factory: AgentFactory,
    *,
    rounds: int = 3,
    generations_per_round: int = 10,
    archive_path: str | Path | None = None,
    scorer: Callable[[str, str], float] | None = None,
    rng: random.Random | None = None,
    space: dict[str, tuple] | None = None,
    on_round: Callable[[int, Candidate, Archive], None] | None = None,
) -> tuple[Candidate | None, list[dict]]:
    """Run ``rounds`` of evolution against a persistent, accumulating archive.

    Returns ``(best_candidate, history)`` where ``history`` has one entry per
    round (with ``skipped: true`` for rounds paused by a frozen calibration).
    The archive is loaded from ``archive_path`` if given (so a prior run's
    population continues) and saved after each productive round. Each round
    seeds the search from the running best, so progress compounds.
    """
    rng = rng or random.Random()
    archive = Archive.load(archive_path) if archive_path else Archive()
    history: list[dict] = []
    current = dict(seed_config)

    for r in range(max(0, rounds)):
        if calibration_frozen():
            history.append({"round": r, "skipped": True, "reason": "calibration frozen"})
            log.info("evolution round %d skipped: calibration frozen", r)
            continue
        best = await evolve_with_eval(
            current, cases, agent_factory,
            generations=generations_per_round, scorer=scorer, rng=rng,
            archive=archive, space=space,
        )
        current = dict(best.config)  # compound: next round branches from the best
        if archive_path:
            archive.save(archive_path)
        history.append({
            "round": r, "best_score": best.score,
            "archive_size": len(archive.candidates),
        })
        if on_round is not None:
            try:
                on_round(r, best, archive)
            except Exception:  # pragma: no cover -- callback must not break the loop
                pass

    return archive.best(), history


__all__ = ["evolve_continuous"]
