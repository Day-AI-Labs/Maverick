from __future__ import annotations

import pytest
from maverick_evolve.eval_harness import EvalCase, evaluate


@pytest.mark.asyncio
async def test_ground_truth_check_scores():
    async def agent(prompt: str) -> str:
        return "42" if "answer" in prompt else "?"

    cases = [
        EvalCase(prompt="the answer", check=lambda o: o == "42"),
        EvalCase(prompt="nope", check=lambda o: o == "42"),
    ]
    rep = await evaluate(agent, cases)
    assert rep.n == 2
    assert rep.score == 0.5


@pytest.mark.asyncio
async def test_reference_contains_scorer():
    async def agent(prompt: str) -> str:
        return "the capital is Paris."

    cases = [EvalCase(prompt="capital of France?", reference="Paris")]
    rep = await evaluate(agent, cases)
    assert rep.score == 1.0


@pytest.mark.asyncio
async def test_agent_exception_scores_zero():
    async def agent(prompt: str) -> str:
        raise RuntimeError("boom")

    cases = [EvalCase(prompt="x", check=lambda o: o == "ok")]
    rep = await evaluate(agent, cases)
    assert rep.score == 0.0  # raised -> "" -> check fails, harness doesn't crash


@pytest.mark.asyncio
async def test_weighting():
    async def agent(prompt: str) -> str:
        return "good" if prompt == "easy" else "bad"

    cases = [
        EvalCase(prompt="easy", check=lambda o: o == "good", weight=1.0),
        EvalCase(prompt="hard", check=lambda o: o == "good", weight=3.0),
    ]
    rep = await evaluate(agent, cases)
    # only the weight-1 case passes -> 1/4
    assert rep.score == 0.25
