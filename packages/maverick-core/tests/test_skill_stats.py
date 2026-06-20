"""Unit tests for skill usage tracking + decay (skill_stats).

Stats are an optimization, never a correctness dependency: every accessor is
fail-safe and degrades to a neutral signal (1.0 weight / empty result) on any
I/O or parse error. These tests pin both the win-rate curve and that fail-safe
contract, plus the MAVERICK_SKILL_DECAY off-switch.
"""
from __future__ import annotations

import json
import os
import stat

import pytest
from maverick.skill import stats as skill_stats


@pytest.fixture
def stats_path(tmp_path):
    return tmp_path / "skill_stats.json"


def test_record_use_increments_and_persists(stats_path):
    skill_stats.record_use(["a", "b"], path=stats_path)
    skill_stats.record_use(["a"], path=stats_path)
    assert skill_stats.get("a", stats_path).uses == 2
    assert skill_stats.get("b", stats_path).uses == 1
    assert skill_stats.get("missing", stats_path) is None


def test_record_use_empty_and_disabled_are_noops(stats_path, monkeypatch):
    skill_stats.record_use([], path=stats_path)
    assert not stats_path.exists()
    monkeypatch.setenv("MAVERICK_SKILL_DECAY", "0")
    skill_stats.record_use(["a"], path=stats_path)
    assert not stats_path.exists()


def test_record_outcome_tracks_wins_losses(stats_path):
    skill_stats.record_outcome(["a"], success=True, path=stats_path)
    skill_stats.record_outcome(["a"], success=False, path=stats_path)
    skill_stats.record_outcome(["a"], success=True, path=stats_path)
    st = skill_stats.get("a", stats_path)
    assert (st.wins, st.losses) == (2, 1)


def test_decay_weight_neutral_until_min_uses(stats_path):
    # Two uses, both losses -- still under the default min_uses=3, so neutral.
    for _ in range(2):
        skill_stats.record_use(["a"], path=stats_path)
        skill_stats.record_outcome(["a"], success=False, path=stats_path)
    assert skill_stats.decay_weight("a", path=stats_path) == 1.0


def test_decay_weight_all_losses_hits_floor(stats_path):
    for _ in range(4):
        skill_stats.record_use(["a"], path=stats_path)
        skill_stats.record_outcome(["a"], success=False, path=stats_path)
    assert skill_stats.decay_weight("a", path=stats_path) == pytest.approx(0.5)


def test_decay_weight_all_wins_stays_neutral(stats_path):
    for _ in range(4):
        skill_stats.record_use(["a"], path=stats_path)
        skill_stats.record_outcome(["a"], success=True, path=stats_path)
    assert skill_stats.decay_weight("a", path=stats_path) == pytest.approx(1.0)


def test_decay_weight_half_winrate_is_midpoint(stats_path):
    for _ in range(4):
        skill_stats.record_use(["a"], path=stats_path)
    skill_stats.record_outcome(["a"], success=True, path=stats_path)
    skill_stats.record_outcome(["a"], success=True, path=stats_path)
    skill_stats.record_outcome(["a"], success=False, path=stats_path)
    skill_stats.record_outcome(["a"], success=False, path=stats_path)
    # floor + (1-floor)*0.5 = 0.5 + 0.25 = 0.75
    assert skill_stats.decay_weight("a", path=stats_path) == pytest.approx(0.75)


def test_decay_weight_unknown_is_neutral(stats_path):
    assert skill_stats.decay_weight("nope", path=stats_path) == 1.0


def test_decay_weight_disabled_is_neutral(stats_path, monkeypatch):
    for _ in range(4):
        skill_stats.record_use(["a"], path=stats_path)
        skill_stats.record_outcome(["a"], success=False, path=stats_path)
    monkeypatch.setenv("MAVERICK_SKILL_DECAY", "0")
    assert skill_stats.decay_weight("a", path=stats_path) == 1.0


def test_decay_weights_batch_matches_single(stats_path):
    for _ in range(4):
        skill_stats.record_use(["a"], path=stats_path)
        skill_stats.record_outcome(["a"], success=False, path=stats_path)
    for _ in range(4):
        skill_stats.record_use(["b"], path=stats_path)
        skill_stats.record_outcome(["b"], success=True, path=stats_path)
    batch = skill_stats.decay_weights(["a", "b", "missing"], path=stats_path)
    assert batch["a"] == pytest.approx(skill_stats.decay_weight("a", path=stats_path))
    assert batch["b"] == pytest.approx(skill_stats.decay_weight("b", path=stats_path))
    assert batch["missing"] == 1.0


def test_evictable_identifies_low_winners(stats_path):
    # 'bad': 6 uses, all losses -> evictable. 'good': 6 uses, all wins -> not.
    for _ in range(6):
        skill_stats.record_use(["bad", "good"], path=stats_path)
        skill_stats.record_outcome(["bad"], success=False, path=stats_path)
        skill_stats.record_outcome(["good"], success=True, path=stats_path)
    cands = skill_stats.evictable(path=stats_path)
    assert "bad" in cands and "good" not in cands


def test_evictable_skips_untested(stats_path):
    # Used a lot but no recorded outcome -> not a fair trial -> not evictable.
    for _ in range(10):
        skill_stats.record_use(["x"], path=stats_path)
    assert skill_stats.evictable(path=stats_path) == []


def test_corrupt_file_degrades_to_neutral(stats_path):
    stats_path.write_text("{ this is not json", encoding="utf-8")
    assert skill_stats.decay_weight("a", path=stats_path) == 1.0
    assert skill_stats.decay_weights(["a"], path=stats_path) == {"a": 1.0}
    assert skill_stats.evictable(path=stats_path) == []
    assert skill_stats.get("a", stats_path) is None
    # A subsequent write must still succeed (overwrites the garbage).
    skill_stats.record_use(["a"], path=stats_path)
    assert json.loads(stats_path.read_text())["a"]["uses"] == 1


def test_non_dict_entries_are_skipped(stats_path):
    stats_path.write_text(json.dumps({"a": "notadict", "b": {"uses": 3}}),
                          encoding="utf-8")
    assert skill_stats.get("a", stats_path) is None
    assert skill_stats.get("b", stats_path).uses == 3


@pytest.mark.skipif(os.name == "nt", reason="POSIX file mode")
def test_saved_file_is_chmod_600(stats_path):
    skill_stats.record_use(["a"], path=stats_path)
    mode = stat.S_IMODE(stats_path.stat().st_mode)
    assert mode == 0o600
