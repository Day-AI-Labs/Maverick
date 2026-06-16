"""Temporal memory + Memory Guard provenance on the world-model fact store.

Temporal history is opt-in ([memory] temporal / MAVERICK_TEMPORAL_MEMORY); when
off the live-value path is unchanged. Provenance columns are written regardless,
so trust-aware retrieval governs existing facts the moment the guard turns on.
"""
from __future__ import annotations

import time

from maverick.world_model import WorldModel


def _wm(tmp_path) -> WorldModel:
    return WorldModel(tmp_path / "world.db")


def test_schema_is_v17(tmp_path):
    assert _wm(tmp_path).schema_version == 17


def test_overwrite_when_temporal_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("MAVERICK_TEMPORAL_MEMORY", raising=False)
    w = _wm(tmp_path)
    w.upsert_fact("k", "v1")
    w.upsert_fact("k", "v2")
    assert w.get_fact("k") == "v2"
    # No history is recorded when temporal is off -- behaviour is unchanged.
    assert w.fact_history("k") == []
    assert w.get_fact("k", as_of=time.time()) is None


def test_temporal_preserves_history(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_TEMPORAL_MEMORY", "1")
    w = _wm(tmp_path)
    w.upsert_fact("hq", "Boston")
    t_mid = time.time()
    time.sleep(0.01)
    w.upsert_fact("hq", "San Francisco")

    # Current value is the latest; the old value is NOT lost.
    assert w.get_fact("hq") == "San Francisco"
    # As-of the instant between the writes, we believed Boston.
    assert w.get_fact("hq", as_of=t_mid) == "Boston"

    hist = w.fact_history("hq")
    assert [h.value for h in hist] == ["San Francisco", "Boston"]
    assert hist[0].valid_to is None       # newest version still open
    assert hist[1].valid_to is not None   # prior version was closed


def test_temporal_unchanged_value_adds_no_version(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_TEMPORAL_MEMORY", "1")
    w = _wm(tmp_path)
    w.upsert_fact("k", "same")
    w.upsert_fact("k", "same")  # confirmation, not a change
    assert len(w.fact_history("k")) == 1


def test_temporal_delete_closes_window(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_TEMPORAL_MEMORY", "1")
    w = _wm(tmp_path)
    w.upsert_fact("k", "v")
    w.delete_fact("k")
    assert w.get_fact("k") is None
    hist = w.fact_history("k")
    assert len(hist) == 1 and hist[0].valid_to is not None  # history survives delete


def test_provenance_stored_and_trust_filter(tmp_path):
    w = _wm(tmp_path)
    w.upsert_fact("trusted", "ok")  # default = first-party trust (3)
    w.upsert_fact("agentnote", "maybe", source="agent:kv_memory", trust_tier=1)
    assert set(w.get_facts()) == {"trusted", "agentnote"}
    # Trust-aware retrieval drops the low-trust fact at floor=2.
    assert set(w.get_facts(min_trust=2)) == {"trusted"}


def test_provenance_recorded_even_without_temporal(tmp_path, monkeypatch):
    # Provenance populates regardless of the temporal toggle, so enabling the
    # guard later governs already-stored memory immediately.
    monkeypatch.delenv("MAVERICK_TEMPORAL_MEMORY", raising=False)
    w = _wm(tmp_path)
    w.upsert_fact("a", "x", trust_tier=0)
    assert w.get_facts(min_trust=1) == {}
    assert w.get_facts() == {"a": "x"}
