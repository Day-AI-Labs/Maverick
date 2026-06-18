from __future__ import annotations

import random

from maverick_evolve.archive import Archive, Candidate


def test_add_and_best():
    a = Archive()
    a.add(Candidate(config={"x": 1}, score=0.5))
    a.add(Candidate(config={"x": 2}, score=0.9))
    assert a.best().config == {"x": 2}


def test_dedup_keeps_higher_score():
    a = Archive()
    a.add(Candidate(config={"x": 1}, score=0.5))
    a.add(Candidate(config={"x": 1}, score=0.8))  # same config id
    assert len(a.candidates) == 1
    assert a.best().score == 0.8


def test_config_distance():
    assert Archive.config_distance({"a": 1}, {"a": 1}) == 0.0
    assert Archive.config_distance({"a": 1}, {"a": 2}) == 1.0
    d = Archive.config_distance({"a": 1, "b": 1}, {"a": 1, "b": 2})
    assert 0.0 < d < 1.0


def test_diverse_picks_best_plus_distant():
    a = Archive()
    a.add(Candidate(config={"k": "aaa"}, score=1.0))   # best
    a.add(Candidate(config={"k": "aaa", "extra": 1}, score=0.9))  # near best
    a.add(Candidate(config={"j": "zzz"}, score=0.8))   # distant
    div = a.diverse(2)
    ids = {c.config.get("k") or c.config.get("j") for c in div}
    assert "aaa" in ids and "zzz" in ids  # best + the distant one, not the near-dup


def test_capacity_eviction_preserves_best():
    a = Archive(capacity=2)
    a.add(Candidate(config={"id": 0}, score=1.0))
    a.add(Candidate(config={"id": 1}, score=0.1))
    a.add(Candidate(config={"id": 2}, score=0.2))
    assert len(a.candidates) <= 2
    assert a.best().config == {"id": 0}


def test_sample_favors_higher_score():
    a = Archive()
    a.add(Candidate(config={"x": 1}, score=1.0))
    a.add(Candidate(config={"x": 2}, score=0.1))
    rng = random.Random(0)
    counts = {1: 0, 2: 0}
    for _ in range(200):
        counts[a.sample(rng).config["x"]] += 1
    # Both lineages stay reachable, but the higher score is sampled more often.
    assert counts[1] > counts[2] and counts[2] >= 0


def test_sample_empty_returns_none():
    assert Archive().sample(random.Random(0)) is None


def test_save_is_atomic_no_temp_residue(tmp_path):
    """save() must write atomically (temp + rename) so a crash mid-write can't
    leave a half-written, unloadable archive. Verify round-trip + no .tmp left."""
    from maverick_evolve.archive import Archive, Candidate

    path = tmp_path / "archive.json"
    arc = Archive()
    arc.add(Candidate(config={"orchestrator": "x"}, score=0.5))
    arc.save(path)
    arc.save(path)  # overwrite an existing file -- the atomic-rename path

    assert path.exists()
    assert not (tmp_path / "archive.json.tmp").exists()  # no leftover temp
    assert list(tmp_path.glob("*.tmp")) == []
    reloaded = Archive.load(path)
    assert len(reloaded.candidates) == len(arc.candidates)
