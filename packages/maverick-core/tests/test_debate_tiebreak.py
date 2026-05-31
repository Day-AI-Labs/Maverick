"""Debate-driven tie-break among score-tied best-of-N candidates.

Off by default; enabled with MAVERICK_BON_DEBATE=1. When the top
candidates are tied on score, two sub-agents argue which patch is the
better fix and a judge picks the winner, overriding the heuristic
selection from select_best_candidate.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from maverick.budget import Budget
from maverick.coding_mode import Candidate
from maverick.llm import LLMResponse
from maverick.orchestrator import _maybe_debate_tiebreak
from maverick.world_model import WorldModel


def _cand(index: int, patch_marker: str) -> Candidate:
    patch = (
        f"diff --git a/f{index}.py b/f{index}.py\n"
        f"--- a/f{index}.py\n+++ b/f{index}.py\n@@ -1 +1 @@\n+{patch_marker}\n"
    )
    return Candidate(index=index, patch=patch, score=0.0, apply_check_passed=True)


class _ScriptedLLM:
    """Returns queued responses; falls back to a draw-ish judge reply."""

    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []
        self.model = "fake:test"

    def complete(self, system, messages, tools=None, budget=None,
                 max_tokens=4096, thinking_budget=None, model=None, on_delta=None):
        self.calls.append({"system": system})
        if self.scripted:
            return self.scripted.pop(0)
        return LLMResponse(text="(no more)", thinking=None,
                           stop_reason="end_turn", tool_calls=[])


@pytest.fixture
def world(tmp_path: Path) -> WorldModel:
    w = WorldModel(path=tmp_path / "world.db")
    w.create_goal("fix the bug", "make tests pass")
    return w


@pytest.mark.asyncio
async def test_disabled_by_default(monkeypatch, world):
    monkeypatch.delenv("MAVERICK_BON_DEBATE", raising=False)
    cands = [_cand(0, "a"), _cand(1, "b")]
    out = await _maybe_debate_tiebreak(
        _ScriptedLLM([]), 1, world, cands, cands[0], Budget(max_dollars=1.0),
    )
    assert out is None


@pytest.mark.asyncio
async def test_no_tie_returns_none(monkeypatch, world):
    monkeypatch.setenv("MAVERICK_BON_DEBATE", "1")
    a = _cand(0, "a")
    b = _cand(1, "b")
    b.score = 0.9  # only one candidate at the top score -> no tie
    out = await _maybe_debate_tiebreak(
        _ScriptedLLM([]), 1, world, [a, b], b, Budget(max_dollars=1.0),
    )
    assert out is None


@pytest.mark.asyncio
async def test_judge_picks_winner(monkeypatch, world):
    monkeypatch.setenv("MAVERICK_BON_DEBATE", "1")
    a = _cand(0, "alpha")
    b = _cand(1, "beta")
    # rounds=1, 2 participants -> 2 debate turns + 1 judge call.
    llm = _ScriptedLLM([
        LLMResponse(text="candidate-0 is correct because alpha", thinking=None,
                    stop_reason="end_turn", tool_calls=[]),
        LLMResponse(text="candidate-1 is correct because beta", thinking=None,
                    stop_reason="end_turn", tool_calls=[]),
        LLMResponse(
            text='{"winner": "candidate-1", "reason": "beta handles edge case", '
                 '"key_argument": "x"}',
            thinking=None, stop_reason="end_turn", tool_calls=[],
        ),
    ])
    out = await _maybe_debate_tiebreak(
        llm, 1, world, [a, b], a, Budget(max_dollars=1.0),
    )
    assert out is b
    assert out.index == 1


@pytest.mark.asyncio
async def test_draw_keeps_heuristic(monkeypatch, world):
    monkeypatch.setenv("MAVERICK_BON_DEBATE", "1")
    a = _cand(0, "alpha")
    b = _cand(1, "beta")
    llm = _ScriptedLLM([
        LLMResponse(text="alpha argument", thinking=None,
                    stop_reason="end_turn", tool_calls=[]),
        LLMResponse(text="beta argument", thinking=None,
                    stop_reason="end_turn", tool_calls=[]),
        LLMResponse(text='{"winner": "draw", "reason": "even", "key_argument": ""}',
                    thinking=None, stop_reason="end_turn", tool_calls=[]),
    ])
    out = await _maybe_debate_tiebreak(
        llm, 1, world, [a, b], a, Budget(max_dollars=1.0),
    )
    assert out is None  # draw -> caller keeps its heuristic pick


@pytest.mark.asyncio
async def test_budget_exhausted_skips(monkeypatch, world):
    monkeypatch.setenv("MAVERICK_BON_DEBATE", "1")
    a = _cand(0, "a")
    b = _cand(1, "b")
    spent = Budget(max_dollars=1.0)
    spent.dollars = 0.99  # >= 98% spent
    out = await _maybe_debate_tiebreak(
        _ScriptedLLM([]), 1, world, [a, b], a, spent,
    )
    assert out is None
