"""BackgroundCompactor: the precompute pending-queue stays bounded under a burst."""
from __future__ import annotations

from maverick import async_compaction as ac


def test_pending_queue_is_bounded(monkeypatch):
    # A burst of distinct conversation keys must not grow _pending without limit
    # (each entry holds a prefix copy). Suppress the drain worker so the queue
    # accumulates, then assert the cap holds.
    bc = ac.BackgroundCompactor()
    monkeypatch.setattr(bc, "_ensure_worker", lambda: None)

    for i in range(ac._MAX_KEYS + 50):
        bc._schedule(f"key-{i}", [{"role": "user", "content": "x"}], 10)

    assert len(bc._pending) <= ac._MAX_KEYS


def test_pending_last_write_wins_same_key(monkeypatch):
    # Re-scheduling the same key overwrites (doesn't grow the queue).
    bc = ac.BackgroundCompactor()
    monkeypatch.setattr(bc, "_ensure_worker", lambda: None)
    for _ in range(10):
        bc._schedule("k", [{"role": "user", "content": "x"}], 10)
    assert len(bc._pending) == 1
