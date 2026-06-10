"""Speculative best-of-N: early-checkpoint scoring prunes weak attempts."""
from __future__ import annotations

import asyncio

import pytest
from maverick import speculative_best_of_n as sbn


def _attempt(name, partial, result, *, finished: list, cp_fail=False, fin_fail=False):
    async def checkpoint():
        if cp_fail:
            raise RuntimeError(f"{name} checkpoint boom")
        return partial

    async def finish():
        finished.append(name)
        if fin_fail:
            raise RuntimeError(f"{name} finish boom")
        return result

    return sbn.Attempt(checkpoint=checkpoint, finish=finish, name=name)


def test_keeps_only_top_scored_and_prunes_rest():
    finished: list = []
    attempts = [
        _attempt("weak", {"score": 1}, "weak-result", finished=finished),
        _attempt("strong", {"score": 9}, "strong-result", finished=finished),
        _attempt("mid", {"score": 5}, "mid-result", finished=finished),
    ]
    out = asyncio.run(sbn.run(attempts, score=lambda p: p["score"], keep=1))
    assert out == "strong-result"
    # ONLY the strong attempt finished; weak + mid were pruned at the checkpoint
    assert finished == ["strong"]


def test_keep_n_finishes_only_survivors():
    finished: list = []
    attempts = [
        _attempt("a", {"q": 1}, "ra", finished=finished),
        _attempt("b", {"q": 8}, "rb", finished=finished),
        _attempt("c", {"q": 6}, "rc", finished=finished),
        _attempt("d", {"q": 2}, "rd", finished=finished),
    ]
    out = asyncio.run(sbn.run(attempts, score=lambda p: p["q"], keep=2))
    assert out == "rb"  # highest-scored survivor
    assert sorted(finished) == ["b", "c"]  # only the top-2 ran finish()


def test_checkpoint_failure_drops_attempt():
    finished: list = []
    attempts = [
        _attempt("broken", None, "x", finished=finished, cp_fail=True),
        _attempt("ok", {"s": 3}, "ok-result", finished=finished),
    ]
    out = asyncio.run(sbn.run(attempts, score=lambda p: p["s"], keep=1))
    assert out == "ok-result"
    assert finished == ["ok"]


def test_all_checkpoints_fail_raises():
    finished: list = []
    attempts = [
        _attempt("a", None, "x", finished=finished, cp_fail=True),
        _attempt("b", None, "y", finished=finished, cp_fail=True),
    ]
    with pytest.raises(sbn.AllAttemptsFailed):
        asyncio.run(sbn.run(attempts, score=lambda p: 0, keep=1))
    assert finished == []  # nothing finished


def test_scorer_error_drops_that_attempt():
    finished: list = []

    def score(p):
        if p["bad"]:
            raise ValueError("unscoreable")
        return p["v"]

    attempts = [
        _attempt("bad", {"bad": True, "v": 99}, "bad-r", finished=finished),
        _attempt("good", {"bad": False, "v": 1}, "good-r", finished=finished),
    ]
    out = asyncio.run(sbn.run(attempts, score=score, keep=1))
    assert out == "good-r" and finished == ["good"]


def test_survivor_finish_failure_falls_to_next():
    finished: list = []
    attempts = [
        _attempt("top", {"s": 9}, "top-r", finished=finished, fin_fail=True),
        _attempt("second", {"s": 5}, "second-r", finished=finished),
    ]
    out = asyncio.run(sbn.run(attempts, score=lambda p: p["s"], keep=2))
    assert out == "second-r"  # top finished-failed, second wins


def test_all_survivors_fail_finish_raises():
    finished: list = []
    attempts = [
        _attempt("a", {"s": 1}, "x", finished=finished, fin_fail=True),
    ]
    with pytest.raises(sbn.AllAttemptsFailed):
        asyncio.run(sbn.run(attempts, score=lambda p: p["s"], keep=1))


def test_pick_final_custom_selector():
    finished: list = []
    attempts = [
        _attempt("a", {"s": 9}, "ra", finished=finished),
        _attempt("b", {"s": 8}, "rb", finished=finished),
    ]
    out = asyncio.run(sbn.run(
        attempts, score=lambda p: p["s"], keep=2,
        pick_final=lambda results: "+".join(sorted(results))))
    assert out == "ra+rb"


def test_empty_raises():
    with pytest.raises(ValueError):
        asyncio.run(sbn.run([], score=lambda p: 0))


def test_prune_at_checkpoint_keeps_one():
    finished: list = []
    attempts = [
        _attempt("a", {"s": 2}, "ra", finished=finished),
        _attempt("b", {"s": 7}, "rb", finished=finished),
    ]
    out = asyncio.run(sbn.prune_at_checkpoint(attempts, score=lambda p: p["s"]))
    assert out == "rb" and finished == ["b"]
