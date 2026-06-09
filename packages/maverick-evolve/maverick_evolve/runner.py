"""Stage 1 wiring: evolve a config against the eval harness, gated by calibration.

Ties the three foundations together into a runnable loop:

  - **fitness** comes from ``eval_harness.evaluate`` over a held-out case set, so
    we evolve against a metric we believe;
  - **the gate** is ``maverick.calibration``: if the verifier has drifted
    (learning frozen), we REFUSE to evolve -- you cannot trust a fitness score
    produced by a miscalibrated judge, and evolving on it would amplify the
    drift. This is the trust thermostat applied to self-improvement;
  - **the search** is config-only (``config_space`` + ``search.evolve``), so a
    candidate can never escape the sandbox.

Dependency-injected: the caller supplies ``agent_factory(config) -> async agent``
(how a config becomes a runnable Maverick agent), so this is testable without a
live model and stays decoupled from how the kernel instantiates agents.
"""
from __future__ import annotations

import logging
import random
from collections.abc import Awaitable, Callable

from . import config_space
from .archive import Archive, Candidate
from .eval_harness import EvalCase, evaluate
from .search import evolve

log = logging.getLogger(__name__)

AgentFactory = Callable[[dict], Callable[[str], Awaitable[str]]]


class EvolutionFrozen(RuntimeError):
    """Raised when evolution is refused because verifier calibration is frozen."""


def calibration_frozen() -> bool:
    """Whether the verifier calibration interlock is currently frozen.

    Fail-open: if calibration can't be consulted, returns False (don't block on
    a missing optional dependency) -- the safety value comes from honoring a
    *known* freeze, not from inventing one.
    """
    try:
        from maverick.calibration import learning_frozen
        return bool(learning_frozen())
    except Exception:  # pragma: no cover -- calibration optional/unavailable
        return False


async def evolve_with_eval(
    seed_config: dict,
    cases: list[EvalCase],
    agent_factory: AgentFactory,
    *,
    generations: int = 10,
    scorer: Callable[[str, str], float] | None = None,
    mutate: Callable[[dict], dict] | None = None,
    rng: random.Random | None = None,
    archive: Archive | None = None,
    space: dict[str, tuple] | None = None,
) -> Candidate:
    """Evolve ``seed_config`` to maximize eval-harness fitness, if calibrated.

    Raises :class:`EvolutionFrozen` when the calibration interlock is frozen --
    self-improvement is gated on a trustworthy judge. Otherwise builds the
    fitness function from ``evaluate(agent_factory(config), cases)`` and runs the
    config-only evolutionary search, returning the best candidate found.
    """
    if calibration_frozen():
        raise EvolutionFrozen(
            "verifier calibration is frozen; refusing to evolve against an "
            "untrustworthy fitness signal (run `maverick calibrate`)"
        )
    rng = rng or random.Random()

    async def _score(config: dict) -> float:
        agent = agent_factory(config)
        report = await evaluate(agent, cases, scorer=scorer)
        return report.score

    def _mutate(config: dict) -> dict:
        if mutate is not None:
            return mutate(config)
        return config_space.mutate(config, rng, space=space)

    return await evolve(
        seed_config, _mutate, _score,
        generations=generations, archive=archive, rng=rng,
    )


__all__ = ["EvolutionFrozen", "calibration_frozen", "evolve_with_eval", "AgentFactory"]
