"""The Consequence Engine: record real outcomes, resolve them, and prefer
reality over the proxy -- only when enabled (OFF by default)."""
from __future__ import annotations

from maverick import consequence as cq


def test_record_resolve_roundtrip(tmp_path):
    store = cq.ConsequenceStore(path=tmp_path / "c.ndjson")
    assert store.resolve(1, 7) is None
    store.record(1, 7, 1.0, kind="invoice_paid")
    assert store.resolve(1, 7) == 1.0


def test_latest_event_wins(tmp_path):
    store = cq.ConsequenceStore(path=tmp_path / "c.ndjson")
    store.record(1, 7, 1.0, kind="renewed", ts=10.0)
    store.record(1, 7, 0.0, kind="churned", ts=20.0)   # reality changed; newest wins
    assert store.resolve(1, 7) == 0.0


def test_value_is_clamped(tmp_path):
    store = cq.ConsequenceStore(path=tmp_path / "c.ndjson")
    store.record(1, 1, 5.0)
    store.record(1, 2, -3.0)
    assert store.resolve(1, 1) == 1.0 and store.resolve(1, 2) == 0.0


def test_persists_across_reload(tmp_path):
    p = tmp_path / "c.ndjson"
    cq.ConsequenceStore(path=p).record(2, 3, 0.7, kind="graded")
    assert cq.ConsequenceStore(path=p).resolve(2, 3) == 0.7


def test_grounded_outcome_prefers_reality_only_when_enabled(tmp_path, monkeypatch):
    store = cq.ConsequenceStore(path=tmp_path / "c.ndjson")
    store.record(1, 7, 1.0)  # reality says success...

    # disabled (default): keep the proxy
    monkeypatch.setattr("maverick.config.get_consequence", lambda: {"enable": False})
    monkeypatch.delenv("MAVERICK_CONSEQUENCE", raising=False)
    assert cq.grounded_outcome(1, 7, proxy=0.4, store=store) == 0.4

    # enabled: prefer reality where it has landed, else fall back to the proxy
    monkeypatch.setenv("MAVERICK_CONSEQUENCE", "1")
    assert cq.grounded_outcome(1, 7, proxy=0.4, store=store) == 1.0
    assert cq.grounded_outcome(9, 9, proxy=0.4, store=store) == 0.4   # no real outcome yet


def test_record_outcome_public_entry(tmp_path):
    store = cq.ConsequenceStore(path=tmp_path / "c.ndjson")
    assert cq.record_outcome(5, 5, 0.9, store=store) is True
    assert cq.resolve(5, 5, store=store) == 0.9
