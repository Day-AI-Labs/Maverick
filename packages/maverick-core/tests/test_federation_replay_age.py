"""The federation replay cache prunes by AGE, not a count cap, so a still-fresh
nonce is never evicted early (which would reopen the replay hole under load)."""
from __future__ import annotations

import pytest
from maverick import federation


@pytest.fixture(autouse=True)
def _clear():
    federation._seen_sigs.clear()
    yield
    federation._seen_sigs.clear()


def test_detects_replay():
    assert federation._replay_seen("sig-a", now=1000.0) is False
    assert federation._replay_seen("sig-a", now=1001.0) is True  # replay


def test_old_entries_pruned_by_age():
    w = federation._SIGN_FRESHNESS_S
    federation._replay_seen("old", now=1000.0)
    # Far past the freshness window: "old" is pruned, so it's no longer "seen".
    assert federation._replay_seen("new", now=1000.0 + w + 10) is False
    assert "old" not in federation._seen_sigs


def test_fresh_nonces_survive_high_volume():
    # Under the OLD count-only eviction (cap 4096), a fresh nonce was dropped
    # once the cap was exceeded — reopening replay above ~13.6 sigs/sec. With
    # age-pruning, every in-window nonce is kept regardless of volume.
    base = 1000.0
    sigs = [f"sig-{i}" for i in range(5000)]  # well past the old 4096 cap
    for i, s in enumerate(sigs):
        assert federation._replay_seen(s, now=base + i * 0.001) is False
    # All 5000 are still within the freshness window, so every replay is caught.
    for i, s in enumerate(sigs):
        assert federation._replay_seen(s, now=base + 1.0 + i * 0.001) is True
