from __future__ import annotations

import random

import pytest
from maverick_evolve import EvalCase
from maverick_evolve.archive import Archive, Candidate
from maverick_evolve.loop import evolve_continuous


# ---- archive persistence (Stage 2: accumulate across rounds/runs) ----
def test_archive_save_load_roundtrip(tmp_path):
    a = Archive(capacity=10)
    a.add(Candidate(config={"k": 1}, score=0.5))
    a.add(Candidate(config={"k": 2}, score=0.9))
    p = tmp_path / "arch.json"
    a.save(p)
    b = Archive.load(p)
    assert b.capacity == 10
    assert b.best().config == {"k": 2}
    assert len(b.candidates) == 2


def test_archive_load_missing_returns_empty(tmp_path):
    a = Archive.load(tmp_path / "nope.json")
    assert a.candidates == []


def test_archive_load_corrupt_returns_empty(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert Archive.load(p).candidates == []


# ---- continuous loop ----
# Graded landscape: one case per threshold so fitness rises smoothly with the
# knob and evolution has a gradient to climb (realistic, not a flat step).
_THRESHOLDS = [2, 4, 6, 8, 10, 12, 14]


def _graded_cases():
    return [EvalCase(prompt=str(t), check=lambda o: o == "GOOD") for t in _THRESHOLDS]


def _graded_factory():
    def factory(config: dict):
        async def agent(prompt: str) -> str:
            return "GOOD" if config.get("n", 0) >= int(prompt) else "BAD"
        return agent
    return factory


@pytest.mark.asyncio
async def test_continuous_accumulates_and_climbs(tmp_path, monkeypatch):
    monkeypatch.setattr("maverick_evolve.loop.calibration_frozen", lambda: False)
    space = {"n": ("int", 1, 16)}
    archive_path = tmp_path / "arch.json"
    best, history = await evolve_continuous(
        {"n": 4}, _graded_cases(), _graded_factory(),
        rounds=3, generations_per_round=40,
        archive_path=archive_path, space=space, rng=random.Random(0),
    )
    assert len(history) == 3
    assert all("best_score" in h for h in history)
    # climbed substantially above the seed (n=4 passes 2/7 thresholds ~= 0.29)
    assert best.config["n"] >= 12 and best.score >= 6 / 7 - 1e-9
    # archive was persisted and accumulated
    assert archive_path.exists()
    assert Archive.load(archive_path).best().config["n"] >= 12


@pytest.mark.asyncio
async def test_continuous_resumes_from_saved_archive(tmp_path, monkeypatch):
    monkeypatch.setattr("maverick_evolve.loop.calibration_frozen", lambda: False)
    space = {"n": ("int", 1, 16)}
    p = tmp_path / "arch.json"
    # seed a prior run's archive with a strong candidate
    seeded = Archive()
    seeded.add(Candidate(config={"n": 15}, score=1.0))
    seeded.save(p)
    best, _ = await evolve_continuous(
        {"n": 4}, _graded_cases(), _graded_factory(),
        rounds=1, generations_per_round=1, archive_path=p,
        space=space, rng=random.Random(0),
    )
    assert best.score == 1.0  # inherited the prior population's winner


@pytest.mark.asyncio
async def test_continuous_skips_rounds_when_frozen(monkeypatch):
    monkeypatch.setattr("maverick_evolve.loop.calibration_frozen", lambda: True)
    best, history = await evolve_continuous(
        {"n": 4}, _graded_cases(), _graded_factory(),
        rounds=3, generations_per_round=10, rng=random.Random(0),
    )
    assert len(history) == 3
    assert all(h.get("skipped") for h in history)
    # Nothing evolved while the judge was frozen, but the seed is still a valid
    # returnable candidate (the archive is seeded up front) -- best() must not
    # be None, so callers always get a usable config back.
    assert best is not None
    assert best.config == {"n": 4}


# ---- demo CLI ----
def test_cli_demo_runs(capsys):
    from maverick_evolve.cli import main
    rc = main(["--demo", "--rounds", "2", "--generations", "25"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "BEST:" in out


def test_cli_no_args_prints_help(capsys):
    from maverick_evolve.cli import main
    rc = main([])
    assert rc == 0
    assert "maverick-evolve" in capsys.readouterr().out
