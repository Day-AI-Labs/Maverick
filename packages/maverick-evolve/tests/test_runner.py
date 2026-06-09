from __future__ import annotations

import random

import pytest
from maverick_evolve import EvalCase, EvolutionFrozen, evolve_with_eval


def _factory_threshold(knob: str, threshold: int):
    """Agent factory whose output passes only when config[knob] >= threshold."""
    def factory(config: dict):
        async def agent(prompt: str) -> str:
            return "GOOD" if config.get(knob, 0) >= threshold else "BAD"
        return agent
    return factory


@pytest.mark.asyncio
async def test_evolve_climbs_to_passing_config(monkeypatch):
    monkeypatch.setattr("maverick_evolve.runner.calibration_frozen", lambda: False)
    cases = [EvalCase(prompt="x", check=lambda o: o == "GOOD")]
    space = {"max_swarm_fanout": ("int", 1, 16)}  # single knob -> deterministic climb
    best = await evolve_with_eval(
        {"max_swarm_fanout": 8},
        cases,
        _factory_threshold("max_swarm_fanout", 12),
        generations=60,
        rng=random.Random(0),
        space=space,
    )
    assert best.score == 1.0
    assert best.config["max_swarm_fanout"] >= 12


@pytest.mark.asyncio
async def test_evolve_refused_when_calibration_frozen(monkeypatch):
    monkeypatch.setattr("maverick_evolve.runner.calibration_frozen", lambda: True)
    cases = [EvalCase(prompt="x", check=lambda o: True)]
    with pytest.raises(EvolutionFrozen):
        await evolve_with_eval(
            {"max_swarm_fanout": 8}, cases,
            _factory_threshold("max_swarm_fanout", 12),
            generations=5, rng=random.Random(0),
        )


@pytest.mark.asyncio
async def test_calibration_gate_fail_open(monkeypatch):
    # If maverick.calibration can't be consulted, we don't block (fail-open).
    import maverick_evolve.runner as runner

    def _boom():
        raise ImportError("calibration unavailable")

    monkeypatch.setattr("maverick.calibration.learning_frozen", _boom)
    assert runner.calibration_frozen() is False
